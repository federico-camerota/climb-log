# SPDX-License-Identifier: GPL-3.0-or-later
"""A view's widgets with their data (03 §2.7, D-072, D-083), for `GET /api/modules/{m}/views/{v}`.

Each widget reads the records of one entity on or before the day asked (today by default; later
records are ignored, as for the recommendation, D-076), in (date, key) order, so a day's second
session comes after its first. The journal's widgets reproduce the legacy `Summary - Trends`
sheet (00-current-state §1): the status board looks at the last 12 sessions, compares the
average of the last 4 with the 4 before (from 5 sessions on; averages of the values present,
rounded to one decimal as the sheet's ROUND), calls a change of at least `settings.trend_delta`
improving or declining, and counts the LOW statuses among the 12. Widgets the app doesn't draw
yet come back as `planned`.
"""

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from climblog.expr import Value
from climblog.expr.functions import sheet_round
from climblog.modules.compute import Timeline
from climblog.modules.schema import (
    Band,
    KpiWidget,
    LineWidget,
    Module,
    Otherwise,
    StatusBoardWidget,
    Widget,
)

Row = Mapping[str, Value]
Tables = Mapping[str, Sequence[Row]]

# The widgets of #78 (the rest of the journal's dashboard); the other planned ones are M4/M5.
NEXT_ISSUE = {"heatmap_calendar", "side_by_side", "text_feed", "table", "monthly"}


@dataclass(frozen=True)
class _Records:
    """An entity's records up to the day, in (date, key) order, with their dates."""

    days: list[dt.date]
    rows: list[Row]
    key: list[str]  # the key parts other than the date (session_no)


Records = Callable[[str], _Records]


def compute_view(
    module: Module,
    widgets: Sequence[Widget],
    tables: Tables,
    settings: Mapping[str, Value],
    day: dt.date,
) -> list[dict[str, Any]]:
    """Each widget's data, in order. `tables[entity]` holds each record's stored and derived
    values (deleted ones left out)."""
    found: dict[str, _Records] = {}

    def records(entity: str) -> _Records:
        if entity not in found:
            ent = module.entities[entity]
            timeline = Timeline(ent, list(tables.get(entity, ())))
            upto = [i for i, d in enumerate(timeline.days) if d != dt.date.min and d <= day]
            found[entity] = _Records(
                [timeline.days[i] for i in upto],
                [timeline.rows[i] for i in upto],
                [p for p in ent.key or [] if p != ent.date_field],
            )
        return found[entity]

    result: list[dict[str, Any]] = []
    for widget in widgets:
        if any(_split(m)[0] not in module.entities for m in _metrics(widget)):
            result.append(_planned(widget, "a view of aggregates comes with M5"))
        elif isinstance(widget, KpiWidget):
            result.append(_kpi(widget, records, day))
        elif isinstance(widget, StatusBoardWidget):
            result.append(_status_board(widget, records, settings))
        elif isinstance(widget, LineWidget):
            result.append(_line(widget, records, settings))
        else:
            result.append(_planned(widget))
    return result


def _metrics(widget: Widget) -> list[str]:
    if isinstance(widget, KpiWidget):
        return [widget.metric]
    if isinstance(widget, StatusBoardWidget):
        return [m for row in widget.classes for m in (row.score, row.status)]
    if isinstance(widget, LineWidget):
        return [series.metric for series in widget.series]
    return []


def _split(metric: str) -> tuple[str, str]:
    entity, _, name = metric.partition(".")
    return entity, name  # checked at load (`checks._views`)


def _kpi(widget: KpiWidget, records: Records, day: dt.date) -> dict[str, Any]:
    entity, name = _split(widget.metric)
    found = records(entity)
    value: Value = None
    if found.rows:
        latest = found.rows[-1].get(name)
        if widget.agg == "latest":
            value = latest
        elif isinstance(latest, dt.date):
            value = (day - _as_day(latest)).days
    return {"widget": "kpi", "label": widget.label, "agg": widget.agg, "value": _json(value)}


def _status_board(
    widget: StatusBoardWidget, records: Records, settings: Mapping[str, Value]
) -> dict[str, Any]:
    delta = settings.get("trend_delta")
    threshold = float(delta) if isinstance(delta, int | float) else 0.5
    rows = []
    for row in widget.classes:
        score_entity, score = _split(row.score)
        status_entity, status = _split(row.status)
        window = records(score_entity).rows[-widget.window :]
        statuses = records(status_entity).rows[-widget.window :]
        n, k = len(window), widget.compare_last
        last = _mean([r.get(score) for r in window[max(0, n - k) :]])
        previous = (
            _mean([r.get(score) for r in window[max(0, n - 2 * k) : n - k]]) if n > k else None
        )
        change = None if last is None or previous is None else sheet_round(last - previous, 1)
        direction = None
        if change is not None:
            direction = "up" if change >= threshold else "down" if change <= -threshold else "flat"
        rows.append(
            {
                "label": row.label,
                "status": _json(statuses[-1].get(status)) if statuses else None,
                "score": _json(window[-1].get(score)) if window else None,
                "average_last": last,
                "average_previous": previous,
                "change": change,
                "direction": direction,
                "low": sum(1 for r in statuses if r.get(status) == "LOW"),
            }
        )
    return {
        "widget": "status_board",
        "label": widget.label,
        "compare_last": widget.compare_last,
        "window": widget.window,
        "rows": rows,
    }


def _line(widget: LineWidget, records: Records, settings: Mapping[str, Value]) -> dict[str, Any]:
    if widget.split_by:
        return _planned(widget, "a line per protocol (split_by) comes with M4")
    if widget.x is not None:
        return _planned(widget, "an x axis other than the date comes with M4")
    entity = _split(widget.series[0].metric)[0]
    found = records(entity)
    points = [
        {"date": day.isoformat(), "key": {p: _json(row.get(p)) for p in found.key}}
        for day, row in zip(found.days, found.rows, strict=True)
    ]
    series = []
    for item in widget.series:
        name = _split(item.metric)[1]
        values = [_number(row.get(name)) for row in found.rows]
        series.append(
            {
                "metric": item.metric,
                "label": item.label or name,
                "values": values,
                "rolling": _rolling(values, widget.rolling) if widget.rolling else None,
            }
        )
    return {
        "widget": "line",
        "label": widget.label,
        "points": points,
        "series": series,
        "bands": _bands(widget, settings),
        "rolling": widget.rolling,
        "last": widget.last,
    }


def _planned(widget: Widget, why: str | None = None) -> dict[str, Any]:
    name = widget.widget
    if why is None:
        why = "comes with #78" if name in NEXT_ISSUE else "comes with M4"
    return {"widget": "planned", "label": getattr(widget, "label", None), "kind": name, "why": why}


def _bands(widget: LineWidget, settings: Mapping[str, Value]) -> list[dict[str, Any]]:
    """The status bands as ranges: up to the first threshold, between thresholds, the rest."""
    bands: list[dict[str, Any]] = []
    low: float | None = None
    for item in widget.bands:
        if isinstance(item, Band):
            high = _threshold(item.le, settings)
            bands.append({"label": item.label, "from": low, "to": high})
            low = high
        elif isinstance(item, Otherwise):
            bands.append({"label": item.else_, "from": low, "to": None})
    return bands


def _threshold(value: float | str, settings: Mapping[str, Value]) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    found = settings.get(value.removeprefix("settings."))
    return float(found) if isinstance(found, int | float) else None


def _rolling(values: Sequence[float | None], n: int) -> list[float | None]:
    """The mean of the values present among each record and the n - 1 before it."""
    out: list[float | None] = []
    for i in range(len(values)):
        out.append(_mean(list(values[max(0, i - n + 1) : i + 1])))
    return out


def _mean(values: Sequence[Value]) -> float | None:
    """AVERAGE of the numbers present, rounded to one decimal (the sheet's ROUND)."""
    numbers = [float(v) for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    return sheet_round(sum(numbers) / len(numbers), 1) if numbers else None


def _number(value: Value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _as_day(value: dt.date) -> dt.date:
    return value.date() if isinstance(value, dt.datetime) else value


def _json(value: Value) -> Any:
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    return value
