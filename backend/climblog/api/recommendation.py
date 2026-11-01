# SPDX-License-Identifier: GPL-3.0-or-later
"""The next-session recommendation for a day (D-071, D-076).

`GET /api/recommendation?date=2026-10-30` (default today): each module's recommendation with
its reasons, from its `recommendation:` block. Combining them into one card ("the most
conservative signal wins", 05-analytics.md §4) comes when a second module has one (M5).
"""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from climblog.catalog import served
from climblog.storage import StorageError

router = APIRouter()


class Reason(BaseModel):
    name: str
    label: str
    value: Any


class ModuleAdvice(BaseModel):
    module: str
    label: str  # e.g. "Suggested next session"
    headline: str | None  # e.g. RECOVER; None when the message stands alone
    message: str | None  # None: no rule holds
    text: str  # as the sheet shows it: "RECOVER — rest day or …"
    reasons: list[Reason]
    as_of: dt.datetime | None
    offline: bool


class Recommendation(BaseModel):
    date: dt.date
    items: list[ModuleAdvice]  # modules with a recommendation, in config order
    problems: list[str]  # modules whose data can't be read now


@router.get("/recommendation")
def get_recommendation(request: Request, date: dt.date | None = None) -> Recommendation:
    """Each module's recommendation for the day (default today)."""
    day = date or dt.date.today()
    current = served(request.app.state)
    items, problems = [], []
    for name, entry in current.entries.items():
        if entry.module is None or entry.module.recommendation is None:
            continue
        try:
            advice = current.advice(entry, day)
        except StorageError as error:
            problems.append(f"{name}: {error}")
            continue
        assert advice is not None and entry.repo is not None
        items.append(
            ModuleAdvice(
                module=name,
                label=advice.label,
                headline=advice.headline,
                message=advice.message,
                text=advice.text,
                reasons=[Reason(name=r.name, label=r.label, value=r.value) for r in advice.reasons],
                as_of=entry.repo.as_of,
                offline=entry.repo.offline,
            )
        )
    return Recommendation(date=day, items=items, problems=problems)
