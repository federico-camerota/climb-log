# SPDX-License-Identifier: GPL-3.0-or-later
"""Modules and their records (02-architecture.md API sketch, D-058).

`GET /api/modules`: every configured module with its schema (or the problems of its YAML).
`GET /api/modules/{module}/{entity}`: the entity's records with their derived values and the
data issues of its tabs, read through the local snapshot. Paging and filters come with the UI.
"""

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from climblog.catalog import Catalog, Entry, served
from climblog.storage import StorageError

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
    entry = current.entries.get(module)
    if entry is None:
        raise HTTPException(404, f"no module '{module}' in the app config")
    if entry.module is None:
        raise HTTPException(
            409, {"message": f"module '{module}' doesn't load", "problems": entry.problems}
        )
    if entity not in entry.module.entities:
        raise HTTPException(404, f"module '{module}' has no entity '{entity}'")
    try:
        data = current.records(entry, entity)
    except StorageError as error:
        raise HTTPException(503, str(error)) from None
    return Records(
        module=module,
        entity=entity,
        records=[
            Record(values=values, derived=derived, rows=rows)
            for values, derived, rows in zip(data.records, data.derived, data.rows, strict=True)
        ],
        issues=[Issue(tab=i.tab, row=i.row, field=i.field, message=i.message) for i in data.issues],
        as_of=data.as_of,
        offline=data.offline,
    )


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
