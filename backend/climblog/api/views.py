# SPDX-License-Identifier: GPL-3.0-or-later
"""A module's view (dashboard) with each widget's data (D-072, D-083).

`GET /api/modules/journal/views/overview?date=2026-10-30` (default today): the widgets of the
view in order, computed from the records on or before the day (`analytics/views.py`); the
frontend only draws them. A widget the app doesn't draw yet comes back as `planned`.
"""

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from climblog.analytics import compute_view
from climblog.api.modules import catalog
from climblog.storage import StorageError

router = APIRouter()


class KpiData(BaseModel):
    widget: Literal["kpi"]
    label: str | None
    agg: str  # latest, days_since_latest
    value: Any  # the latest value (a status, a score, a date), or a number of days


class StatusRow(BaseModel):
    label: str
    status: Any  # the latest record's
    score: float | None  # the latest record's
    average_last: float | None  # of the last `compare_last` records
    average_previous: float | None  # of the ones before (needs more than `compare_last`)
    change: float | None
    direction: Literal["up", "down", "flat"] | None  # by `settings.trend_delta`
    low: int  # LOW statuses among the last `window` records


class StatusBoardData(BaseModel):
    widget: Literal["status_board"]
    label: str | None
    compare_last: int
    window: int
    rows: list[StatusRow]


class Point(BaseModel):
    date: dt.date
    key: dict[str, Any]  # the key parts other than the date (session_no)


class SeriesData(BaseModel):
    metric: str
    label: str
    values: list[float | None]  # one per point
    rolling: list[float | None] | None  # the rolling mean, one per point


class BandData(BaseModel):
    label: str
    from_: float | None = Field(alias="from")
    to: float | None


class LineData(BaseModel):
    widget: Literal["line"]
    label: str | None
    points: list[Point]  # every record up to the day, oldest first
    series: list[SeriesData]
    bands: list[BandData]
    rolling: int | None
    last: int  # how many of the latest points to show at first


class PlannedData(BaseModel):
    widget: Literal["planned"]
    label: str | None
    kind: str  # the widget's name in the YAML
    why: str  # e.g. "comes with #78"


WidgetData = Annotated[
    KpiData | StatusBoardData | LineData | PlannedData, Field(discriminator="widget")
]


class View(BaseModel):
    module: str
    view: str
    date: dt.date
    widgets: list[WidgetData]
    as_of: dt.datetime | None
    offline: bool


@router.get("/modules/{module}/views/{view}")
def get_view(request: Request, module: str, view: str, date: dt.date | None = None) -> View:
    """The view's widgets with their data, for the day (default today)."""
    day = date or dt.date.today()
    current = catalog(request)
    entry = current.entries.get(module)
    if entry is None:
        raise HTTPException(404, f"no module '{module}' in the app config")
    if entry.module is None or entry.repo is None:
        raise HTTPException(409, f"module '{module}' doesn't load")
    views = entry.module.views or {}
    if view not in views:
        known = ", ".join(views) or "none"
        raise HTTPException(404, f"module '{module}' has no view '{view}' (views: {known})")
    try:
        tables, settings = current.full_tables(entry)
    except StorageError as error:
        raise HTTPException(503, str(error)) from None
    widgets = compute_view(entry.module, views[view], tables, settings, day)
    return View.model_validate(
        {
            "module": module,
            "view": view,
            "date": day,
            "widgets": widgets,
            "as_of": entry.repo.as_of,
            "offline": entry.repo.offline,
        }
    )
