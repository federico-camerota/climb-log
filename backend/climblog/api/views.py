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
from climblog.modules.schema import Module
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
    x: list[float] | None = None  # with an x axis other than the date: its values (no points)
    x_label: str | None = None


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


class BarsData(BaseModel):
    widget: Literal["bars"]
    label: str | None
    metric: str  # its label
    agg: str
    categories: list[str]  # periods (2026-W44, 2026-10, 2026-10-30) or a field's values
    values: list[float | None]
    n: list[int]  # the values behind each bar
    last: int  # bars shown at first (periods)


class Stack(BaseModel):
    label: str  # a value of the field (or "" for a single stack)
    values: list[float]  # one per week


class WeekbarsData(BaseModel):
    widget: Literal["weekbars"]
    label: str | None
    agg: str
    weeks: list[str]  # 2026-W44, every week from the first record's
    starts: list[dt.date]  # their Mondays
    stacks: list[Stack]
    shown: int  # weeks shown at first


class StackedSeries(BaseModel):
    metric: str
    label: str
    values: list[float | None]


class StackedData(BaseModel):
    widget: Literal["stacked"]
    label: str | None
    agg: str
    categories: list[str]
    series: list[StackedSeries]
    last: int


class Box(BaseModel):
    label: str
    n: int
    low: float  # the lower whisker
    q1: float
    median: float
    q3: float
    high: float
    outliers: list[float]


class BoxByData(BaseModel):
    widget: Literal["box_by"]
    label: str | None
    metric: str
    by: str
    boxes: list[Box]


class ScatterPoint(BaseModel):
    x: float
    y: float
    date: dt.date
    group: str | None  # the colour's value


class Trend(BaseModel):
    slope: float
    intercept: float
    from_: float = Field(alias="from")
    to: float


class ScatterData(BaseModel):
    widget: Literal["scatter"]
    label: str | None
    x_label: str
    y_label: str
    lag: int
    points: list[ScatterPoint]
    n: int
    trend: Trend | None  # least squares, from 3 points


class LoadWeek(BaseModel):
    label: str  # 2026-W44
    start: dt.date  # its Monday
    load: float  # the sum of the records' loads
    sessions: int
    without_load: int  # records missing an input: counted as 0
    rest_days: int
    others: list[float]  # one per other source, stacked
    acwr: float | None  # at the week's last day (or the day asked); none before the baseline
    monotony: float | None
    strain: float | None


class Streak(BaseModel):
    days: int
    start: dt.date
    end: dt.date


class TrainingLoadData(BaseModel):
    widget: Literal["training_load"]
    label: str | None
    others: list[str]  # the other sources' labels
    absent: list[str]  # other sources whose module isn't configured or doesn't load
    zones: list[float]  # low, high, very high
    acute: int
    chronic: int
    baseline_from: dt.date | None  # the ratio is shown from this day on
    acwr_today: float | None
    weeks: list[LoadWeek]  # from the first record's week, oldest first
    shown: int
    longest_streak: Streak | None
    current_streak: int


class PlannedData(BaseModel):
    widget: Literal["planned"]
    label: str | None
    kind: str  # the widget's name in the YAML
    why: str  # e.g. "program weeks come with the program modules (M5)"


WidgetData = Annotated[
    KpiData
    | StatusBoardData
    | LineData
    | HeatmapData
    | SideBySideData
    | TextFeedData
    | TableData
    | MonthlyData
    | BarsData
    | WeekbarsData
    | StackedData
    | BoxByData
    | ScatterData
    | TrainingLoadData
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

    def others(module_id: str) -> tuple[Module, Any] | None:
        """Another loaded module by its `module:` id, with its records (unreadable: none)."""
        for other in current.entries.values():
            if other.module is not None and other.module.module == module_id and other is not entry:
                try:
                    return other.module, current.full_tables(other)[0]
                except StorageError:
                    return None
        return None

    widgets = compute_view(entry.module, views[view], tables, settings, day, others)
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
