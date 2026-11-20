# SPDX-License-Identifier: GPL-3.0-or-later
"""Modules and their records (02-architecture.md API sketch, D-058).

`GET /api/modules`: every configured module with its schema (or the problems of its YAML).
`GET /api/modules/{module}/{entity}`: the entity's records with their derived values and the
data issues of its tabs, read through the local snapshot. Paging and filters come with the UI.
`POST` there adds a record; `GET`, `PATCH` and `DELETE` on `…/{entity}/record?<key>` read, change
and soft delete one (D-075), through `RecordWriter`.
"""

import datetime as dt
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from climblog.catalog import Catalog, EntityRecords, Entry, served
from climblog.expr import Value
from climblog.modules.batch import key_parts
from climblog.modules.program import Runs as ProgramRuns
from climblog.modules.program import week_text
from climblog.modules.schema import BaseField, DateField
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
from climblog.storage.cells import CellError, parse_cell

router = APIRouter()


class ModuleInfo(BaseModel):
    id: str
    name: str | None = None
    version: int | None = None
    kind: str | None = None
    description: str | None = None
    problems: list[str] = []  # why the YAML didn't load (then no schema)
    notes: list[str] = []  # what works partly: a `from:` the app config can't serve (D-114)
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
        modules=[_info(current, entry) for entry in current.entries.values()],
        problems=current.problems,
    )


class FieldProblem(BaseModel):
    field: str
    message: str


class WriteProblem(BaseModel):
    message: str  # the first problem's, when there are several
    field: str | None = None  # the (first) field at fault, when there is one
    problems: list[FieldProblem] = []  # every field at fault, e.g. two bad values (D-079)
    index: int | None = None  # a batch's row at fault: new rows first, then changed (D-115)


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


# ---- Program runs (D-109) ----


class RunInfo(BaseModel):
    number: int
    start_week: str  # 2026-W42, as typed in the Runs tab
    start: dt.date  # the Monday of week 1
    end: dt.date  # the Sunday of the program's last week


class Position(BaseModel):
    run: int
    week: int
    phase: str | None  # none after the last week or between phases
    light_week: bool


class RunList(BaseModel):
    module: str
    weeks: int  # the program's length
    runs: list[RunInfo]  # by start
    current: Position | None  # the day's run and week; none before the first run
    next_week: str  # the week a new run would start by default: the day's
    issues: list[Issue]  # the Runs tab's
    as_of: dt.datetime | None
    offline: bool


class NewRun(BaseModel):
    start_week: str  # 2026-W46


@router.get("/modules/{module}/runs", responses={404: {"description": "Not a program module"}})
def list_runs(request: Request, module: str, date: dt.date | None = None) -> RunList:
    """A program module's runs (its Runs tab) and the run and week of `date` (default today)."""
    current = catalog(request)
    entry = _program_entry(current, module)
    try:
        runs, issues = current.runs(entry)
    except StorageError as error:
        raise HTTPException(503, str(error)) from None
    return _run_list(entry, runs, issues, date or dt.date.today())


@router.post("/modules/{module}/runs", status_code=201, responses=_WRITE_ERRORS)
def start_run(request: Request, module: str, body: NewRun) -> RunList:
    """Start a new run: the next run number, from the Monday of `start_week`, which must come
    after the latest run's start. The Runs tab gets the row, as if typed in the sheet."""
    current = catalog(request)
    entry = _program_entry(current, module)
    with entry.lock, _write_errors():
        _writer(entry).start_run(body.start_week)
    try:
        runs, issues = current.runs(entry)
    except StorageError as error:
        raise _problem(503, error) from None
    return _run_list(entry, runs, issues, dt.date.today())


def _program_entry(current: Catalog, module: str) -> Entry:
    entry = current.entries.get(module)
    if entry is None:
        raise HTTPException(404, f"no module '{module}' in the app config")
    if entry.module is None:
        raise HTTPException(
            409, {"message": f"module '{module}' doesn't load", "problems": entry.problems}
        )
    if entry.module.program is None:
        raise HTTPException(404, f"module '{module}' is not a program: it has no runs")
    return entry


def _run_list(entry: Entry, runs: ProgramRuns, issues: list[DataIssue], day: dt.date) -> RunList:
    assert entry.module is not None and entry.module.program is not None and entry.repo
    program = entry.module.program
    length = dt.timedelta(weeks=program.weeks, days=-1)
    found = runs.at(day)
    return RunList(
        module=entry.name,
        weeks=program.weeks,
        runs=[
            RunInfo(number=r.number, start_week=r.start_week, start=r.start, end=r.start + length)
            for r in runs.runs
        ],
        current=None
        if found is None
        else Position(
            run=found.run,
            week=found.week,
            phase=program.phase(found.week),
            light_week=program.is_light_week(found.week),
        ),
        next_week=week_text(day),
        issues=[_issue(i) for i in issues],
        as_of=entry.repo.as_of,
        offline=entry.repo.offline,
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
        records=[_record(data, index, _weeks(entry, entity)) for index in range(len(data.records))],
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


class PrefillSource(BaseModel):
    module: str  # the other module's `module:` id
    entity: str
    label: str  # "Session 2 · Climbing indoor · 7a"
    key: dict[str, Any]
    values: dict[str, Any]  # this entity's field → the value it would start with


class Prefill(BaseModel):
    sources: list[PrefillSource]  # one: prefill it; several: the form asks which (D-114)
    notes: list[str]  # fields that can't be prefilled, and why


@router.get("/modules/{module}/{entity}/prefill")
def prefill(request: Request, module: str, entity: str, date: dt.date) -> Prefill:
    """The other modules' records of `date` that prefill the entity's `from:` fields (D-114):
    the form starts with their values (editable); nothing is written."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    found, notes = current.prefill(entry, entity, date)
    return Prefill(
        sources=[
            PrefillSource(
                module=c.module,
                entity=c.entity,
                label=c.label,
                key={k: _json(v) for k, v in c.key.items()},
                values={k: _json(v) for k, v in c.values.items()},
            )
            for c in found
        ],
        notes=notes,
    )


# ---- Batch forms (D-115) ----


class BatchRow(BaseModel):
    key: Any  # the reference row's key ("A1")
    label: str  # "A1 · Wall slides"
    hint: str | None  # "Prescription W3: 3x10"
    retired: bool  # listed only because the day has its record
    record: Record | None  # its record of the day, if logged


class BatchRows(BaseModel):
    module: str
    form: str
    entity: str
    field: str  # the entity's ref field each row fills
    table: str
    shared: list[str]  # typed once for the batch: the date (and other key parts), keep_fields
    rows: list[BatchRow]
    others: list[Record]  # the day's records of the entity that are no row of the batch
    issues: list[Issue]
    as_of: dt.datetime | None
    offline: bool


@router.get(
    "/modules/{module}/forms/{form}/batch",
    responses={404: {"description": "No such module or batch form"}},
    description="One query parameter per shared key field, e.g. ?date=2026-11-18",
)
def batch_rows(request: Request, module: str, form: str) -> BatchRows:
    """A batch form's rows (D-115): one per reference row in its filter still in use, each
    with its record of the day if there is one, and the day's records outside the batch."""
    current = catalog(request)
    entry = current.entries.get(module)
    found = None if entry is None or entry.module is None else entry.module.forms or {}
    if entry is None or found is None or form not in found or found[form].batch() is None:
        raise HTTPException(404, f"module '{module}' has no batch form '{form}'")
    assert entry.module is not None
    model = found[form]
    entity = entry.module.entities[model.entity]
    key: dict[str, Value] = {}
    for part in key_parts(entry.module, model):
        raw = request.query_params.get(part)
        field = entity.fields[part]
        assert isinstance(field, BaseField)
        try:
            key[part] = None if raw in (None, "") else parse_cell(entry.module, field, raw)
        except CellError as error:
            raise HTTPException(422, f"{part}: {error}") from None
    try:
        batch, data = current.batch(entry, form, key)
    except StorageError as error:
        raise HTTPException(503, str(error)) from None
    weeks = _weeks(entry, model.entity)
    return BatchRows(
        module=module,
        form=form,
        entity=model.entity,
        field=batch.field,
        table=batch.table,
        shared=batch.shared,
        rows=[
            BatchRow(
                key=_json(row.key),
                label=row.label,
                hint=row.hint,
                retired=row.retired,
                record=None if row.record is None else _record(data, row.record, weeks),
            )
            for row in batch.rows
        ],
        others=[_record(data, i, weeks) for i in batch.others],
        issues=[_issue(i) for i in data.issues],
        as_of=data.as_of,
        offline=data.offline,
    )


class BatchChange(BaseModel):
    key: dict[str, Any]  # the stored record's key
    values: dict[str, Any]  # the fields to change; null clears one
    expected: dict[str, Any] | None = None  # as read: a 409 when one has changed since


class BatchWrite(BaseModel):
    new: list[dict[str, Any]] = []  # new records, as `POST …/{entity}`
    changed: list[BatchChange] = []


class BatchWritten(BaseModel):
    keys: list[dict[str, Any]]  # every record written, new ones first


@router.post("/modules/{module}/{entity}/batch", responses=_WRITE_ERRORS)
def save_batch(request: Request, module: str, entity: str, body: BatchWrite) -> BatchWritten:
    """A batch form's rows in one save, all or none (D-115). A problem names its row by
    `index`: the new rows first, then the changed ones."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    assert entry.module is not None
    parts = entry.module.entities[entity].key or []
    changed = [(c.key, c.values, c.expected or {}) for c in body.changed]
    with entry.lock, _write_errors():
        keys = _writer(entry).save_batch(entity, body.new, changed)
    return BatchWritten(
        keys=[{p: _json(v) for p, v in zip(parts, key, strict=True)} for key in keys]
    )


def _json(value: Value) -> Any:
    return value.isoformat() if isinstance(value, dt.date | dt.time) else value


class FormValues(BaseModel):
    values: dict[str, Any]  # a form's values as typed so far (the API's types, as on save)


class Hidden(BaseModel):
    hidden: list[str]  # the fields whose `visible_if` doesn't hold for these values


@router.post("/modules/{module}/{entity}/hidden")
def hidden_fields(request: Request, module: str, entity: str, body: FormValues) -> Hidden:
    """The fields a form hides for its values so far (`visible_if`, 03 §2.1b): the form sends
    what is typed as it changes. A value that can't be read yet counts as blank."""
    current = catalog(request)
    entry = _entry(current, module, entity)
    assert entry.module is not None
    fields = entry.module.entities[entity].fields
    values: dict[str, Value] = {}
    for name, raw in body.values.items():
        field = fields.get(name)
        if isinstance(field, BaseField):
            try:
                values[name] = parse_cell(entry.module, field, raw)
            except CellError:
                values[name] = None
    try:
        return Hidden(hidden=current.hidden(entry, entity, values))
    except StorageError as error:
        raise HTTPException(503, str(error)) from None


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
    problem = WriteProblem(message=str(error), field=field, problems=problems, index=error.index)
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
    return Written(record=_record(data, index, _weeks(entry, entity)), as_of=data.as_of)


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


def _record(data: EntityRecords, index: int, weeks: Collection[str] = ()) -> Record:
    """A record for the API; its week fields as typed, `2026-W47` (D-110), not their Monday."""
    values = dict(data.records[index])
    for name in weeks:
        value = values.get(name)
        if isinstance(value, dt.date):
            values[name] = week_text(value)
    return Record(values=values, derived=data.derived[index], rows=data.rows[index])


def _weeks(entry: Entry, entity: str) -> set[str]:
    """The entity's week fields (D-110)."""
    assert entry.module is not None
    fields = entry.module.entities[entity].fields
    return {n for n, f in fields.items() if isinstance(f, DateField) and f.type == "week"}


def _info(current: Catalog, entry: Entry) -> ModuleInfo:
    module = entry.module
    if module is None:
        return ModuleInfo(id=entry.name, problems=entry.problems)
    return ModuleInfo(
        id=entry.name,
        name=module.name,
        version=module.version,
        kind=module.kind,
        description=module.description,
        notes=sorted(current.prefill_problems(entry).values()),
        module_schema=module.model_dump(mode="json", by_alias=True, exclude_defaults=True),
    )
