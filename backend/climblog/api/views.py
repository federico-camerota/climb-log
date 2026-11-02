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


class HeatmapDay(BaseModel):
    date: dt.date
    status: Any  # the worst of the day's records
    records: int  # how many (0: only the extra entity's record)
    extra: Any  # the extra entity's status that day, e.g. a rest day's
    mark: str | None  # the day's letters, e.g. "O", "GO", "R"


class HeatmapMark(BaseModel):
    letter: str
    label: str  # what it stands for, e.g. Outdoor, rest day


class HeatmapData(BaseModel):
    widget: Literal["heatmap_calendar"]
    label: str | None
    start: dt.date  # the first day of the first month shown (not before the first record's)
    end: dt.date  # the day asked
    extra: str | None  # the extra entity, e.g. rest_day
    marks: list[HeatmapMark]  # the letters' legend
    days: list[HeatmapDay]  # days with records, in order


class Row(BaseModel):
    field: str
    label: str


class SideGroupData(BaseModel):
    label: str
    rows: list[Row]


class SideRecord(BaseModel):
    date: dt.date
    key: dict[str, Any]
    values: dict[str, Any]


class Note(BaseModel):
    field: str
    label: str
    text: str | None


class SideBySideData(BaseModel):
    widget: Literal["side_by_side"]
    label: str | None
    last: int  # how many to show at first
    groups: list[SideGroupData]
    records: list[SideRecord]  # the latest 12, newest first
    notes: list[Note]  # the newest record's


class FeedItem(BaseModel):
    date: dt.date
    key: dict[str, Any]
    text: str
    score: float | None


class FeedList(BaseModel):
    label: str
    items: list[FeedItem]


class AttentionItem(BaseModel):
    date: dt.date
    key: dict[str, Any]
    texts: list[str]


class Attention(BaseModel):
    label: str  # the status, e.g. NEEDS ATTENTION
    items: list[AttentionItem]


class TextFeedData(BaseModel):
    widget: Literal["text_feed"]
    label: str | None
    window_days: int
    lists: list[FeedList]
    attention: Attention | None


class Average(BaseModel):
    field: str
    label: str
    value: float | None


class LatestNote(BaseModel):
    date: dt.date
    text: str


class TableData(BaseModel):
    widget: Literal["table"]
    label: str | None
    columns: list[Row]
    rows: list[dict[str, Any]]  # newest first
    averages: list[Average]  # over the rows shown
    note: LatestNote | None


class MonthRow(BaseModel):
    month: str  # 2026-10
    count: int
    classes: list[float | None]  # one per class; none without a record counted
    overall: float | None  # the average of the class averages
    low: int | None  # LOW statuses; none without a record counted
    extra: list[float | None]  # one per extra column


class MonthlyData(BaseModel):
    widget: Literal["monthly"]
    label: str | None
    count_label: str
    classes: list[str]
    overall: str | None
    low: bool
    extra: list[str]
    months: int  # how many to show at first
    rows: list[MonthRow]  # every month from the first record's, oldest first


class PlannedData(BaseModel):
    widget: Literal["planned"]
    label: str | None
    kind: str  # the widget's name in the YAML
    why: str  # e.g. "comes with M4"


WidgetData = Annotated[
    KpiData
    | StatusBoardData
    | LineData
    | HeatmapData
    | SideBySideData
    | TextFeedData
    | TableData
    | MonthlyData
    | PlannedData,
    Field(discriminator="widget"),
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
