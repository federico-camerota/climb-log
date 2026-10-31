# SPDX-License-Identifier: GPL-3.0-or-later
"""What to log on a day (D-078): `GET /api/today?date=2026-10-30` (default today).

For each module with forms: each form due on the day (done / partial / missing, with what is
missing and the record's own log check), whether the items are alternatives (nothing logged
yet: a session or a rest day), and the latest record up to the day. The recommendation is
`GET /api/recommendation`.
"""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from climblog.catalog import served
from climblog.modules.forms import forms_of
from climblog.storage import StorageError

router = APIRouter()


class DueForm(BaseModel):
    form: str
    label: str  # "Pre session"
    key: dict[str, Any]  # the record's key (the date alone for a new record)
    status: str  # done / partial / missing
    missing: list[str]  # sections (or fields) still to fill
    log_check: Any = None  # the record's own check, when the entity has one


class ModuleDay(BaseModel):
    module: str
    name: str
    items: list[DueForm]
    any_one: bool  # nothing logged yet: the items are alternatives
    last: dt.date | None  # the latest record (of the first form's entity) up to the day
    last_label: str | None  # e.g. "Session"
    days_since: int | None
    notes: list[str]  # forms left out, and why
    as_of: dt.datetime | None
    offline: bool


class Today(BaseModel):
    date: dt.date
    modules: list[ModuleDay]  # modules with forms, in config order
    problems: list[str]  # modules whose data can't be read now


@router.get("/today")
def get_today(request: Request, date: dt.date | None = None) -> Today:
    """Each module's forms on the day (default today)."""
    day = date or dt.date.today()
    current = served(request.app.state)
    found, problems = [], []
    for name, entry in current.entries.items():
        if entry.module is None or not forms_of(entry.module):
            continue
        try:
            result = current.due(entry, day)
        except StorageError as error:
            problems.append(f"{name}: {error}")
            continue
        assert entry.repo is not None
        found.append(
            ModuleDay(
                module=name,
                name=entry.module.name,
                items=[DueForm(**vars(item)) for item in result.items],
                any_one=result.any_one,
                last=result.last,
                last_label=result.last_label,
                days_since=(day - result.last).days if result.last is not None else None,
                notes=result.notes,
                as_of=entry.repo.as_of,
                offline=entry.repo.offline,
            )
        )
    return Today(date=day, modules=found, problems=problems)
