# SPDX-License-Identifier: GPL-3.0-or-later
"""Modules and their records (02-architecture.md API sketch, D-058).

`GET /api/modules`: every configured module with its schema (or the problems of its YAML).
`GET /api/modules/{module}/{entity}`: the entity's records with their derived values and the
data issues of its tabs, read through the local snapshot. Paging and filters come with the UI.
`POST` there adds a record; `GET`, `PATCH` and `DELETE` on `…/{entity}/record?<key>` read, change
and soft delete one (D-075), through `RecordWriter`.
"""

import datetime as dt
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from climblog.catalog import Catalog, EntityRecords, Entry, served
from climblog.expr import Value
from climblog.storage import (
    DataIssue,
    KeyTaken,
    RecordNotFound,
    RecordWriter,
    StorageError,
    WorkbookLocked,
    WriteConflict,
    WriteError,
)

router = APIRouter()


class ModuleInfo(BaseModel):
    id: str
    name: str | None = None
    version: int | None = None
    kind: str | None = None
    description: str | None = None
    problems: list[str] = []  # why the YAML didn't load (then no schema)
    module_schema: dict[str, Any] | None = None  # the module YAML as JSON


class ModuleList(BaseModel):
    modules: list[ModuleInfo]
    problems: list[str] = []  # the app config's own


class Issue(BaseModel):
    tab: str
    row: int | None
    field: str | None
    message: str
    # value, required, left_out, orphan, orphan_child, column, tab, setting (D-082): what can
    # be done about it (a left-out or orphan row can be deleted, an orphan section row adopted)
    kind: str = "value"
    value: str | None = None  # a bad cell as typed, to show it in the form


class Record(BaseModel):
    values: dict[str, Any]  # stored fields
    derived: dict[str, Any]  # derived fields (app-computed)
    rows: dict[str, int]  # tab → sheet row


class Records(BaseModel):
    module: str
    entity: str
    records: list[Record]
    issues: list[Issue]
    as_of: dt.datetime | None  # when the data in use was read
    offline: bool  # the workbook couldn't be reached: the snapshot is shown, read-only


def catalog(request: Request) -> Catalog:
    """The app's catalog, loaded from the app config on first use."""
    return served(request.app.state)


@router.get("/modules")
def list_modules(request: Request) -> ModuleList:
    current = catalog(request)
    return ModuleList(
        modules=[_info(entry) for entry in current.entries.values()],
        problems=current.problems,
    )


@router.get("/modules/{module}/{entity}")
def list_records(request: Request, module: str, entity: str) -> Records:
    current = catalog(request)
    entry = _entry(current, module, entity)
    try:
        data = current.records(entry, entity)
    except StorageError as error:
        raise HTTPException(503, str(error)) from None
    return Records(
        module=module,
        entity=entity,
        records=[_record(data, index) for index in range(len(data.records))],
        issues=[_issue(i) for i in data.issues],
        as_of=data.as_of,
        offline=data.offline,
    )


# ---- Writing (D-075) ----


class NewRecord(BaseModel):
    values: dict[str, Any]  # stored fields; the key's blank parts take their defaults


class RecordChanges(BaseModel):
    values: dict[str, Any]  # the fields to change; null clears one
    # The fields as the caller read them: a 409 when one has changed since (a hand edit in the
    # sheet, another window), D-027. Leave out to write regardless.
    expected: dict[str, Any] | None = None


class Written(BaseModel):
    record: Record  # as read back from the workbook
    as_of: dt.datetime | None


class FieldProblem(BaseModel):
    field: str
    message: str


class WriteProblem(BaseModel):
    message: str  # the first problem's, when there are several
    field: str | None = None  # the (first) field at fault, when there is one
    problems: list[FieldProblem] = []  # every field at fault, e.g. two bad values (D-079)


_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": WriteProblem, "description": text}
    for status, text in [
        (404, "No such module, entity or record"),
        (409, "The key is taken, the record changed since it was read, or the module doesn't load"),
        (422, "An unknown field or a bad value"),
        (423, "The workbook is open in Excel or LibreOffice"),
        (503, "The workbook can't be reached: offline, read-only"),
    ]
}

# The record's key goes in the query string, one parameter per key field (D-075):
# `/api/modules/journal/session/record?date=2026-10-30&session_no=2`.
KEY_HELP = "One query parameter per key field, e.g. ?date=2026-10-30&session_no=2"


@router.post("/modules/{module}/{entity}", status_code=201, responses=_WRITE_ERRORS)
def add_record(request: Request, module: str, entity: str, body: NewRecord) -> Written:
    """Add a record."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    with entry.lock, _write_errors():
        key = _writer(entry).add(entity, body.values)
    return _written(current, entry, entity, key)


@router.get("/modules/{module}/{entity}/record", responses=_WRITE_ERRORS, description=KEY_HELP)
def get_record(request: Request, module: str, entity: str) -> Written:
    """One record, by its key."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    with _write_errors():
        key = _writer(entry).key_of(entity, dict(request.query_params))
    return _written(current, entry, entity, key)


@router.patch("/modules/{module}/{entity}/record", responses=_WRITE_ERRORS, description=KEY_HELP)
def update_record(request: Request, module: str, entity: str, body: RecordChanges) -> Written:
    """Change some fields of a record."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    with entry.lock, _write_errors():
        key = _writer(entry).update(entity, dict(request.query_params), body.values, body.expected)
    return _written(current, entry, entity, key)


@router.delete(
    "/modules/{module}/{entity}/record",
    status_code=204,
    responses=_WRITE_ERRORS,
    description=KEY_HELP,
)
def delete_record(request: Request, module: str, entity: str) -> None:
    """Soft delete a record (and its children): `deleted` is filled on its rows."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    with entry.lock, _write_errors():
        _writer(entry).delete(entity, dict(request.query_params))


# A row that is no record (a data issue): `?tab=Session&row=6`, as the issue gives them (D-082).
ROW_HELP = "The row of a data issue, e.g. ?tab=Session&row=6"


@router.delete(
    "/modules/{module}/{entity}/row", status_code=204, responses=_WRITE_ERRORS, description=ROW_HELP
)
def delete_row(request: Request, module: str, entity: str, tab: str, row: int) -> None:
    """Soft delete a row the app leaves out (no key, a duplicate key) or an orphan row."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    with entry.lock, _write_errors():
        _writer(entry).delete_row(entity, tab, row)


@router.post(
    "/modules/{module}/{entity}/row/record",
    status_code=201,
    responses=_WRITE_ERRORS,
    description=ROW_HELP,
)
def adopt_row(request: Request, module: str, entity: str, tab: str, row: int) -> Written:
    """Give an orphan section row its record: the main-tab row with the orphan's key."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    with entry.lock, _write_errors():
        key = _writer(entry).adopt_row(entity, tab, row)
    return _written(current, entry, entity, key)


def _entry(current: Catalog, module: str, entity: str) -> Entry:
    """The module's entry, refused when it is unknown or doesn't load, or has no such entity."""
    entry = current.entries.get(module)
    if entry is None:
        raise HTTPException(404, f"no module '{module}' in the app config")
    if entry.module is None:
        raise HTTPException(
            409, {"message": f"module '{module}' doesn't load", "problems": entry.problems}
        )
    if entity not in entry.module.entities:
        raise HTTPException(404, f"module '{module}' has no entity '{entity}'")
    return entry


def _writer(entry: Entry) -> RecordWriter:
    assert entry.module is not None and entry.repo is not None
    # One look at the source for the writer's checks; the save itself goes to the workbook.
    return RecordWriter(entry.module, entry.repo.pinned())


@contextmanager
def _write_errors() -> Iterator[None]:
    """A storage error as the HTTP status a client can act on."""
    try:
        yield
    except RecordNotFound as error:
        raise _problem(404, error) from None
    except (KeyTaken, WriteConflict) as error:
        raise _problem(409, error) from None
    except WriteError as error:
        raise _problem(422, error) from None
    except WorkbookLocked as error:
        raise _problem(423, error) from None
    except StorageError as error:  # offline (the snapshot is read-only), unreachable
        raise _problem(503, error) from None


def _problem(status: int, error: StorageError) -> HTTPException:
    field = error.field if isinstance(error, WriteError) else None
    found = error.problems if isinstance(error, WriteError) else []
    problems = [FieldProblem(field=name, message=text) for name, text in found]
    problem = WriteProblem(message=str(error), field=field, problems=problems)
    return HTTPException(status, problem.model_dump())


def _written(current: Catalog, entry: Entry, entity: str, key: Sequence[Value]) -> Written:
    """The record as read back: the next read after a write takes a new snapshot."""
    try:
        found = current.record(entry, entity, key)
    except StorageError as error:
        raise _problem(503, error) from None
    if found is None:  # pragma: no cover - written, then deleted by hand at once
        raise HTTPException(404, WriteProblem(message="the record is gone").model_dump())
    data, index = found
    return Written(record=_record(data, index), as_of=data.as_of)


def _issue(issue: DataIssue) -> Issue:
    raw = issue.value
    value = None if raw is None else raw.isoformat() if hasattr(raw, "isoformat") else str(raw)
    return Issue(
        tab=issue.tab,
        row=issue.row,
        field=issue.field,
        message=issue.message,
        kind=issue.kind,
        value=value,
    )


def _record(data: EntityRecords, index: int) -> Record:
    return Record(values=data.records[index], derived=data.derived[index], rows=data.rows[index])


def _info(entry: Entry) -> ModuleInfo:
    module = entry.module
    if module is None:
        return ModuleInfo(id=entry.name, problems=entry.problems)
    return ModuleInfo(
        id=entry.name,
        name=module.name,
        version=module.version,
        kind=module.kind,
        description=module.description,
        module_schema=module.model_dump(mode="json", by_alias=True, exclude_defaults=True),
    )
