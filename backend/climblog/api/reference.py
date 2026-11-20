# SPDX-License-Identifier: GPL-3.0-or-later
"""A module's reference tables (03-module-framework.md §2.5, D-112).

`GET /api/modules/{module}/reference`: the tables, with their columns.
`GET /api/modules/{module}/reference/{table}`: the rows and the tab's data issues.
`POST` there adds a row; `PATCH …/{table}/row?key=A3` changes one (retiring it included). A row's
key can't change and the app deletes none: records point at the keys.
"""

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from climblog.api.modules import (
    _WRITE_ERRORS,
    Issue,
    _issue,
    _problem,
    _write_errors,
    _writer,
    catalog,
)
from climblog.catalog import Catalog, Entry
from climblog.expr import Value
from climblog.modules.reference import (
    RETIRED,
    per_week_label,
    reference_columns,
    reference_weeks,
    table_label,
)
from climblog.storage import StorageError

router = APIRouter()


class ReferenceTableInfo(BaseModel):
    name: str
    label: str
    tab: str
    key: str  # the key column
    columns: list[str]  # every column in sheet order: key, fields, w1…wN, retired
    week_columns: list[str]  # the per-week columns, w1…wN (none without `per_week`)
    per_week_label: str | None  # what each week's column holds ("Prescription")


class ReferenceList(BaseModel):
    module: str
    tables: list[ReferenceTableInfo]


class ReferenceRow(BaseModel):
    values: dict[str, Any]  # every column; `retired` is true or false
    row: int  # the sheet row


class ReferenceTableRows(BaseModel):
    module: str
    table: ReferenceTableInfo
    rows: list[ReferenceRow]
    issues: list[Issue]  # the tab's
    as_of: dt.datetime | None
    offline: bool


class NewReferenceRow(BaseModel):
    values: dict[str, Any]  # the key and any other columns


class ReferenceChanges(BaseModel):
    values: dict[str, Any]  # the columns to change; null clears one
    expected: dict[str, Any] | None = None  # as read: a 409 when one has changed since


@router.get("/modules/{module}/reference", responses={404: {"description": "No such module"}})
def list_tables(request: Request, module: str) -> ReferenceList:
    """The module's reference tables (none for most modules)."""
    entry = _module_entry(catalog(request), module)
    assert entry.module is not None
    return ReferenceList(
        module=module, tables=[_info(entry, name) for name in entry.module.reference or {}]
    )


@router.get(
    "/modules/{module}/reference/{table}", responses={404: {"description": "No such table"}}
)
def list_rows(request: Request, module: str, table: str) -> ReferenceTableRows:
    """A reference table's rows, retired ones included, and its tab's data issues."""
    current = catalog(request)
    entry = _table_entry(current, module, table)
    return _rows(current, entry, table)


@router.post("/modules/{module}/reference/{table}", status_code=201, responses=_WRITE_ERRORS)
def add_row(request: Request, module: str, table: str, body: NewReferenceRow) -> ReferenceTableRows:
    """Add a row, with a key no row has yet."""
    current = catalog(request)
    entry = _table_entry(current, module, table)
    with entry.lock, _write_errors():
        _writer(entry).add_reference_row(table, body.values)
    return _rows(current, entry, table)


@router.patch("/modules/{module}/reference/{table}/row", responses=_WRITE_ERRORS)
def update_row(
    request: Request, module: str, table: str, key: str, body: ReferenceChanges
) -> ReferenceTableRows:
    """Change some columns of the row with this key (`?key=A3`); `retired: true` retires it."""
    current = catalog(request)
    entry = _table_entry(current, module, table)
    with entry.lock, _write_errors():
        _writer(entry).update_reference_row(table, key, body.values, body.expected)
    return _rows(current, entry, table)


def _module_entry(current: Catalog, module: str) -> Entry:
    entry = current.entries.get(module)
    if entry is None:
        raise HTTPException(404, f"no module '{module}' in the app config")
    if entry.module is None:
        raise HTTPException(
            409, {"message": f"module '{module}' doesn't load", "problems": entry.problems}
        )
    return entry


def _table_entry(current: Catalog, module: str, table: str) -> Entry:
    entry = _module_entry(current, module)
    assert entry.module is not None
    if table not in (entry.module.reference or {}):
        raise HTTPException(404, f"module '{module}' has no reference table '{table}'")
    return entry


def _info(entry: Entry, name: str) -> ReferenceTableInfo:
    assert entry.module is not None
    module = entry.module
    table = (module.reference or {})[name]
    return ReferenceTableInfo(
        name=name,
        label=table_label(name, table),
        tab=table.tab,
        key=table.key,
        columns=list(reference_columns(module, name)),
        week_columns=table.week_columns(reference_weeks(module)),
        per_week_label=per_week_label(table),
    )


def _rows(current: Catalog, entry: Entry, table: str) -> ReferenceTableRows:
    assert entry.repo is not None
    try:
        found, issues = current.reference(entry, table)
    except StorageError as error:
        raise _problem(503, error) from None
    return ReferenceTableRows(
        module=entry.name,
        table=_info(entry, table),
        rows=[
            ReferenceRow(values=_values(values), row=row)
            for values, row in zip(found.rows, found.places, strict=True)
        ],
        issues=[_issue(i) for i in issues],
        as_of=entry.repo.as_of,
        offline=entry.repo.offline,
    )


def _values(values: dict[str, Value]) -> dict[str, Any]:
    return {**values, RETIRED: values.get(RETIRED) is True}
