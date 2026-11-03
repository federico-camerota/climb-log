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
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from climblog.analytics.load import Other, training_load
from climblog.analytics.metrics import Query, run_query
from climblog.analytics.progress import body_heatmap, pre_post
from climblog.expr import Value
from climblog.expr.functions import sheet_round
from climblog.modules.compute import Timeline
from climblog.modules.forms import field_label
from climblog.modules.schema import (
    Band,
    BarsWidget,
    BaseField,
    BodyHeatmapWidget,
    BoxByWidget,
    ChoiceField,
    HeatmapWidget,
    KpiWidget,
    LineWidget,
    Module,
    MonthlyWidget,
    Otherwise,
    PrePostWidget,
    ScatterWidget,
    SideBySideWidget,
    StackedWidget,
    StatusBoardWidget,
    TableWidget,
    TextFeedWidget,
    TrainingLoadWidget,
    WeekbarsWidget,
    Widget,
)

Row = Mapping[str, Value]
Tables = Mapping[str, Sequence[Row]]

# The worst status first, for a day with several records (the journal's levels).
WORST = {"LOW": 0, "WATCH": 1, "GOOD": 2, "NEEDS ATTENTION": 0, "WORTH NOTING": 1}
SIDE_BY_SIDE_MAX = 12  # records sent; the page shows `last` of them at first


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
    others: Other | None = None,
) -> list[dict[str, Any]]:
    """Each widget's data, in order. `tables[entity]` holds each record's stored and derived
    values (deleted ones left out); `others` finds another module and its records by its
    `module:` id (the training load's other sources)."""
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
            result.append(_line(module, widget, records, settings))
        elif isinstance(widget, HeatmapWidget):
            result.append(_heatmap(widget, records, day))
        elif isinstance(widget, SideBySideWidget):
            result.append(_side_by_side(module, widget, records))
        elif isinstance(widget, TextFeedWidget):
            result.append(_text_feed(widget, records, day))
        elif isinstance(widget, TableWidget):
            result.append(_table(module, widget, records, day))
        elif isinstance(widget, MonthlyWidget):
            result.append(_monthly(widget, records, day))
        elif isinstance(widget, BarsWidget):
            result.append(_bars(module, widget, tables, records, day))
        elif isinstance(widget, WeekbarsWidget):
            result.append(_weekbars(module, widget, records, day))
        elif isinstance(widget, StackedWidget):
            result.append(_stacked(module, widget, tables, day))
        elif isinstance(widget, BoxByWidget):
            result.append(_box_by(module, widget, records))
        elif isinstance(widget, ScatterWidget):
            result.append(_scatter(module, widget, tables, records, day))
        elif isinstance(widget, TrainingLoadWidget):
            result.append(training_load(module, widget, tables, day, others or _none))
        elif isinstance(widget, PrePostWidget):
            result.append(pre_post(module, widget, tables, day))
        elif isinstance(widget, BodyHeatmapWidget):
            result.append(body_heatmap(module, widget, tables, day))
        else:
            result.append(_planned(widget))
    return result


def _none(_: str) -> None:
    return None


def _metrics(widget: Widget) -> list[str]:
    if isinstance(widget, KpiWidget):
        return [widget.metric]
    if isinstance(widget, StatusBoardWidget):
        return [m for row in widget.classes for m in (row.score, row.status)]
    if isinstance(widget, LineWidget):
        return [series.metric for series in widget.series] + ([widget.x] if widget.x else [])
    if isinstance(widget, HeatmapWidget):
        return [widget.metric, *([widget.extra] if widget.extra else [])]
    if isinstance(widget, BarsWidget | BoxByWidget):
        return [widget.metric]
    if isinstance(widget, WeekbarsWidget):
        return [widget.metric]
    if isinstance(widget, StackedWidget):
        return [series.metric for series in widget.series]
    if isinstance(widget, ScatterWidget):
        return [widget.x, widget.y]
    if isinstance(widget, TrainingLoadWidget):
        return [widget.load]
    if isinstance(widget, MonthlyWidget):
        means = [extra.mean for extra in widget.extra if extra.mean is not None]
        return [c.score for c in widget.classes] + ([widget.low] if widget.low else []) + means
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


def _line(
    module: Module, widget: LineWidget, records: Records, settings: Mapping[str, Value]
) -> dict[str, Any]:
    entity = _split(widget.series[0].metric)[0]
    if any(_split(f)[0] != entity for f in widget.split_by):
        return _planned(widget, "a line per value of another entity's fields is a backlog item")
    found = records(entity)
    label = _labeller(module, entity, {})
    data: dict[str, Any] = {
        "widget": "line",
        "label": widget.label,
        "points": [],
        "series": [],
        "bands": _bands(widget, settings),
        "rolling": widget.rolling,
        "last": widget.last,
        "x": None,
        "x_label": None,
    }
    splits = [_split(f)[1] for f in widget.split_by]
    combos = [" · ".join(_text(row.get(f)) for f in splits) for row in found.rows]
    groups = list(dict.fromkeys(combos)) if splits else [""]
    if widget.x is not None:
        # one point per value of x (ascending): each series' mean there
        x_name = _split(widget.x)[1]
        xs = sorted({x for row in found.rows if (x := _number(row.get(x_name))) is not None})
        data["x"], data["x_label"] = xs, label(x_name)
        for item in widget.series:
            name = _split(item.metric)[1]
            for group in groups:
                at: dict[float, list[float]] = {}
                for row, combo in zip(found.rows, combos, strict=True):
                    x, y = _number(row.get(x_name)), _number(row.get(name))
                    if x is not None and y is not None and (not splits or combo == group):
                        at.setdefault(x, []).append(y)
                values = [_aggregate("mean", at.get(x, [])) for x in xs]
                data["series"].append(
                    _series(item.metric, item.label or label(name), group, values, None)
                )
        return data
    data["points"] = [
        {"date": day.isoformat(), "key": {p: _json(row.get(p)) for p in found.key}}
        for day, row in zip(found.days, found.rows, strict=True)
    ]
    for item in widget.series:
        name = _split(item.metric)[1]
        for group in groups:
            values = [
                _number(row.get(name)) if not splits or combo == group else None
                for row, combo in zip(found.rows, combos, strict=True)
            ]
            rolling = _rolling(values, widget.rolling) if widget.rolling else None
            data["series"].append(
                _series(item.metric, item.label or label(name), group, values, rolling)
            )
    return data


def _series(
    metric: str,
    label: str,
    group: str,
    values: list[float | None],
    rolling: list[float | None] | None,
) -> dict[str, Any]:
    shown = f"{label} · {group}" if group else label
    return {"metric": metric, "label": shown, "values": values, "rolling": rolling}


def _text(value: Value) -> str:
    if value is None or value == "":
        return "(blank)"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _planned(widget: Widget, why: str = "comes with M5 or later") -> dict[str, Any]:
    label = getattr(widget, "label", None)
    return {"widget": "planned", "label": label, "kind": widget.widget, "why": why}


def _heatmap(widget: HeatmapWidget, records: Records, day: dt.date) -> dict[str, Any]:
    """Each day with records, from the first record's month (at most the last `months`
    months): the worst status of its records, how many there are, the `extra` entity's status
    that day, and its letters (the records' `mark`, else `extra_mark` on an extra-only day)."""
    entity, name = _split(widget.metric)
    found = records(entity)
    other = records(_split(widget.extra)[0]) if widget.extra is not None else None
    firsts = [d for d in [*found.days, *(other.days if other is not None else [])] if d <= day]
    start = _month_start(day, widget.months - 1)
    if firsts:  # not before the first record's month (a new journal isn't a year of blanks)
        start = max(start, _month_start(min(firsts), 0))
    mark_name = _split(widget.mark.field)[1] if widget.mark is not None else None
    days: dict[dt.date, dict[str, Any]] = {}

    def entry(when: dt.date) -> dict[str, Any]:
        return days.setdefault(
            when, {"date": when.isoformat(), "status": None, "records": 0, "marks": []}
        )

    for when, row in zip(found.days, found.rows, strict=True):
        if not start <= when <= day:
            continue
        item = entry(when)
        item["records"] += 1
        item["status"] = _worst(item["status"], row.get(name))
        if widget.mark is not None and mark_name is not None:
            letter = widget.mark.letters.get(str(row.get(mark_name)))
            if letter is not None and letter not in item["marks"]:
                item["marks"].append(letter)
    extra_label = None
    if widget.extra is not None and other is not None:
        extra_entity, extra_name = _split(widget.extra)
        extra_label = extra_entity
        for when, row in zip(other.days, other.rows, strict=True):
            if not start <= when <= day:
                continue
            entry(when)["extra"] = _json(row.get(extra_name))
    for item in days.values():
        item["status"] = _json(item["status"])
        item.setdefault("extra", None)
        marks: list[str] = item.pop("marks")
        if not marks and item["records"] == 0 and widget.extra_mark is not None:
            marks = [widget.extra_mark]
        item["mark"] = "".join(marks) or None
    legend = [
        {"letter": letter, "label": value}
        for value, letter in (widget.mark.letters.items() if widget.mark is not None else [])
    ]
    if widget.extra_mark is not None and extra_label is not None:
        legend.append({"letter": widget.extra_mark, "label": extra_label.replace("_", " ")})
    return {
        "widget": "heatmap_calendar",
        "label": widget.label,
        "entity": entity,  # whose records a day opens (with the extra entity's)
        "start": start.isoformat(),
        "end": day.isoformat(),
        "extra": extra_label,
        "marks": legend,
        "days": [days[d] for d in sorted(days)],
    }


def _side_by_side(module: Module, widget: SideBySideWidget, records: Records) -> dict[str, Any]:
    """The latest records, newest first, their grouped fields, and the latest one's notes."""
    found = records(widget.entity)
    latest = list(zip(found.days, found.rows, strict=True))[-SIDE_BY_SIDE_MAX:][::-1]
    names = [f for g in widget.groups for f in g.fields]
    label = _labeller(module, widget.entity, widget.labels)
    newest = latest[0][1] if latest else {}
    return {
        "widget": "side_by_side",
        "label": widget.label,
        "last": widget.last,
        "groups": [
            {"label": g.label, "rows": [{"field": f, "label": label(f)} for f in g.fields]}
            for g in widget.groups
        ],
        "records": [
            {
                "date": when.isoformat(),
                "key": {p: _json(row.get(p)) for p in found.key},
                "values": {f: _json(row.get(f)) for f in names},
            }
            for when, row in latest
        ],
        "notes": [
            {"field": f, "label": label(f), "text": _json(newest.get(f))} for f in widget.notes
        ],
    }


def _text_feed(widget: TextFeedWidget, records: Records, day: dt.date) -> dict[str, Any]:
    """Per list, the texts of the last `window_days` days with a score, the highest first
    (then the newest), `top` of them; and the records needing attention, newest first."""
    found = records(widget.entity)
    since = day - dt.timedelta(days=widget.window_days)
    recent = [(w, r) for w, r in zip(found.days, found.rows, strict=True) if w >= since]
    lists = []
    for item in widget.lists:
        entries = []
        for when, row in recent:
            text, score = row.get(item.text), row.get(item.score) if item.score else None
            if not isinstance(text, str) or not text.strip():
                continue
            if item.score is not None and _number(score) is None:
                continue
            entries.append((when, row, text, score))
        if item.score is not None:
            entries.sort(key=lambda e: (_number(e[3]) or 0.0, e[0]), reverse=True)
        else:
            entries.sort(key=lambda e: e[0], reverse=True)
        lists.append(
            {
                "label": item.label,
                "items": [
                    {
                        "date": when.isoformat(),
                        "key": {p: _json(row.get(p)) for p in found.key},
                        "text": text,
                        "score": _number(score),
                    }
                    for when, row, text, score in entries[: widget.top]
                ],
            }
        )
    attention = None
    if widget.attention is not None:
        spec = widget.attention
        attention = {
            "label": spec.equals,
            "items": [
                {
                    "date": when.isoformat(),
                    "key": {p: _json(row.get(p)) for p in found.key},
                    "texts": [
                        _json(row.get(f))
                        for f in spec.fields
                        if isinstance(row.get(f), str) and str(row.get(f)).strip()
                    ],
                }
                for when, row in reversed(recent)
                if row.get(spec.status) == spec.equals
            ],
        }
    return {
        "widget": "text_feed",
        "label": widget.label,
        "window_days": widget.window_days,
        "lists": lists,
        "attention": attention,
    }


def _table(module: Module, widget: TableWidget, records: Records, day: dt.date) -> dict[str, Any]:
    """The entity's records of the last `window_days` days (or the `last` ones), newest first,
    the averages of some columns over them, and the latest note up to the day."""
    found = records(widget.entity)
    pairs = list(zip(found.days, found.rows, strict=True))
    if widget.window_days is not None:
        since = day - dt.timedelta(days=widget.window_days)
        pairs = [(w, r) for w, r in pairs if w >= since]
    elif widget.last is not None:
        pairs = pairs[-widget.last :]
    pairs.reverse()
    label = _labeller(module, widget.entity, widget.labels)
    note = None
    if widget.note is not None:
        for when, row in reversed(list(zip(found.days, found.rows, strict=True))):
            text = row.get(widget.note)
            if isinstance(text, str) and text.strip():
                note = {"date": when.isoformat(), "text": text}
                break
    return {
        "widget": "table",
        "label": widget.label,
        "columns": [{"field": c, "label": label(c)} for c in widget.columns],
        "rows": [{c: _json(row.get(c)) for c in widget.columns} for _, row in pairs],
        "averages": [
            {"field": a, "label": label(a), "value": _mean([row.get(a) for _, row in pairs])}
            for a in widget.averages
        ],
        "note": note,
    }


def _monthly(widget: MonthlyWidget, records: Records, day: dt.date) -> dict[str, Any]:
    """Per calendar month from the first record to the day's, oldest first, as the legacy
    monthly table: the records counted; without one, no averages and no LOW count."""
    entities = {widget.count} | {_split(m)[0] for m in _metrics(widget)}
    entities |= {extra.count for extra in widget.extra if extra.count is not None}
    first = [records(e).days[0] for e in entities if records(e).days]
    if not first:
        months: list[dt.date] = []
    else:
        months = []
        month = min(first).replace(day=1)
        while month <= day:
            months.append(month)
            month = _next_month(month)

    def in_month(entity: str, month: dt.date) -> list[Row]:
        found = records(entity)
        end = _next_month(month)
        return [r for w, r in zip(found.days, found.rows, strict=True) if month <= w < end]

    rows = []
    for month in months:
        counted = len(in_month(widget.count, month))
        classes = []
        for c in widget.classes:
            entity, name = _split(c.score)
            values = [r.get(name) for r in in_month(entity, month)]
            classes.append(_mean(values) if counted else None)
        present = [v for v in classes if v is not None]
        overall = _mean(present) if widget.overall is not None and present else None
        low = None
        if widget.low is not None and counted:
            entity, name = _split(widget.low)
            low = sum(1 for r in in_month(entity, month) if r.get(name) == "LOW")
        extras: list[float | None] = []
        for extra in widget.extra:
            if extra.count is not None:
                extras.append(float(len(in_month(extra.count, month))))
            elif extra.mean is not None:
                entity, name = _split(extra.mean)
                found = in_month(entity, month)
                extras.append(_mean([r.get(name) for r in found]) if found else None)
        rows.append(
            {
                "month": month.isoformat()[:7],
                "count": counted,
                "classes": classes,
                "overall": overall,
                "low": low,
                "extra": extras,
            }
        )
    return {
        "widget": "monthly",
        "label": widget.label,
        "count_label": widget.count_label,
        "classes": [c.label for c in widget.classes],
        "overall": widget.overall,
        "low": widget.low is not None,
        "extra": [extra.label for extra in widget.extra],
        "months": widget.months,
        "rows": rows,
    }


SELF = "m"  # the module's name in the metric layer's ids, inside a view
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # as weekday()


def _query(module: Module, tables: Tables, day: dt.date, metrics: Sequence[str], **kw: Any) -> Any:
    """The metric layer (D-090) on this module's records up to the day."""
    asked = Query([f"{SELF}.{m}" for m in metrics], end=day, **kw)
    return run_query(asked, {SELF: (module, tables)}, day)


def _bars(
    module: Module, widget: BarsWidget, tables: Tables, records: Records, day: dt.date
) -> dict[str, Any]:
    entity, name = _split(widget.metric)
    data: dict[str, Any] = {
        "widget": "bars",
        "label": widget.label,
        "metric": _labeller(module, entity, {})(name),
        "agg": widget.agg,
        "last": widget.last,
    }
    if widget.by is None:
        result = _query(module, tables, day, [widget.metric], group=widget.group, agg=widget.agg)
        [series] = result.series
        data |= {
            "categories": [p.label for p in result.points],
            "values": series.values,
            "n": series.n,
        }
        return data
    found = records(entity)
    by = _split(widget.by)[1]
    groups: dict[str, list[float]] = {}
    for row in found.rows:
        value = _number(row.get(name))
        if value is not None and row.get(by) not in (None, ""):
            groups.setdefault(_text(row.get(by)), []).append(value)
    order = _order(module, entity, by, list(groups), [])
    data |= {
        "categories": order,
        "values": [_aggregate(widget.agg, groups[c]) for c in order],
        "n": [len(groups[c]) for c in order],
    }
    return data


def _weekbars(
    module: Module, widget: WeekbarsWidget, records: Records, day: dt.date
) -> dict[str, Any]:
    if widget.group == "program_week":
        return _planned(widget, "program weeks come with the program modules (M5)")
    entity, name = _split(widget.metric)
    found = records(entity)
    if not found.days:
        weeks: list[dt.date] = []
    else:
        first = found.days[0] - dt.timedelta(days=found.days[0].weekday())
        last = day - dt.timedelta(days=day.weekday())
        weeks = [first + dt.timedelta(days=7 * i) for i in range((last - first).days // 7 + 1)]
    index = {w: i for i, w in enumerate(weeks)}
    split = _split(widget.split_by)[1] if widget.split_by else None
    stacks: dict[str, list[list[float]]] = {}
    for when, row in zip(found.days, found.rows, strict=True):
        week = index[when - dt.timedelta(days=when.weekday())]
        if widget.agg == "count_by_value":
            if row.get(name) in (None, ""):
                continue
            stack, value = _text(row.get(name)), 1.0
        else:
            number = _number(row.get(name))
            if number is None:
                continue
            stack, value = (_text(row.get(split)) if split else ""), number
        stacks.setdefault(stack, [[] for _ in weeks])[week].append(value)
    by = name if widget.agg == "count_by_value" else split
    order = _order(module, entity, by, list(stacks), []) if by else list(stacks)
    agg = "sum" if widget.agg == "count_by_value" else widget.agg
    return {
        "widget": "weekbars",
        "label": widget.label,
        "agg": widget.agg,
        "weeks": [_week_label(w) for w in weeks],
        "starts": [w.isoformat() for w in weeks],
        "stacks": [
            {"label": stack, "values": [_week_value(agg, v) for v in stacks[stack]]}
            for stack in order
        ],
        "shown": widget.weeks,
    }


def _week_value(agg: str, values: list[float]) -> float | None:
    """A week's bar: 0 for a count or sum of nothing, no bar (a gap) for a mean of nothing."""
    if not values:
        return None if agg == "mean" else 0.0
    return _aggregate(agg, values)


def _stacked(module: Module, widget: StackedWidget, tables: Tables, day: dt.date) -> dict[str, Any]:
    metrics = [series.metric for series in widget.series]
    result = _query(module, tables, day, metrics, group=widget.group, agg=widget.agg)
    return {
        "widget": "stacked",
        "label": widget.label,
        "agg": widget.agg,
        "categories": [p.label for p in result.points],
        "series": [
            {
                "metric": item.metric,
                "label": item.label or _metric_label(module, item.metric),
                "values": found.values,
            }
            for item, found in zip(widget.series, result.series, strict=True)
        ],
        "last": widget.last,
    }


def _metric_label(module: Module, metric: str) -> str:
    entity, name = _split(metric)
    return _labeller(module, entity, {})(name)


def _box_by(module: Module, widget: BoxByWidget, records: Records) -> dict[str, Any]:
    if widget.bins:
        return _planned(widget, "a time of day in named bins is a backlog item")
    entity, name = _split(widget.metric)
    by = _split(widget.by)[1]
    groups: dict[str, list[float]] = {}
    for row in records(entity).rows:
        value = _number(row.get(name))
        if value is not None and row.get(by) not in (None, ""):
            groups.setdefault(_text(row.get(by)), []).append(value)
    order = _order(module, entity, by, list(groups), widget.order)
    label = _labeller(module, entity, {})
    return {
        "widget": "box_by",
        "label": widget.label,
        "metric": label(name),
        "by": label(by),
        "boxes": [{"label": c, **_box(groups[c])} for c in order if c in groups],
    }


def _box(values: list[float]) -> dict[str, Any]:
    """Tukey's box: quartiles (inclusive, as the sheets' QUARTILE), whiskers to the furthest
    values within 1.5 IQR of the box, the values beyond as outliers."""
    ordered = sorted(values)
    if len(ordered) == 1:
        q1 = median = q3 = ordered[0]
    else:
        q1, median, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    reach = 1.5 * (q3 - q1)
    inside = [v for v in ordered if q1 - reach <= v <= q3 + reach]
    return {
        "n": len(ordered),
        "low": inside[0],
        "q1": _round(q1),
        "median": _round(median),
        "q3": _round(q3),
        "high": inside[-1],
        "outliers": [v for v in ordered if v < inside[0] or v > inside[-1]],
    }


def _scatter(
    module: Module, widget: ScatterWidget, tables: Tables, records: Records, day: dt.date
) -> dict[str, Any]:
    if widget.color is not None and widget.color.count(".") > 1:
        return _planned(widget, "a colour through a reference comes with M5")
    (x_entity, x_name), (y_entity, y_name) = _split(widget.x), _split(widget.y)
    points: list[dict[str, Any]] = []
    if x_entity == y_entity and widget.lag == 0:
        found = records(x_entity)
        color = _split(widget.color)[1] if widget.color else None
        for when, row in zip(found.days, found.rows, strict=True):
            x, y = _number(row.get(x_name)), _number(row.get(y_name))
            if x is not None and y is not None:
                group = _text(row.get(color)) if color else None
                points.append({"x": x, "y": y, "date": when.isoformat(), "group": group})
    else:  # by day, the second metric `lag` days later (D-088)
        result = _query(module, tables, day, [widget.x, widget.y], lag=widget.lag)
        xs, ys = result.series
        for point, x, y in zip(result.points, xs.values, ys.values, strict=True):
            if x is not None and y is not None:
                points.append({"x": x, "y": y, "date": point.start.isoformat(), "group": None})
    label_x, label_y = _labeller(module, x_entity, {}), _labeller(module, y_entity, {})
    return {
        "widget": "scatter",
        "label": widget.label,
        "x_label": label_x(x_name),
        "y_label": label_y(y_name),
        "lag": widget.lag,
        "points": points,
        "n": len(points),
        "trend": _trend([p["x"] for p in points], [p["y"] for p in points]),
    }


def _trend(xs: list[float], ys: list[float]) -> dict[str, float] | None:
    """The least-squares line through the points (3 or more, x not all equal)."""
    if len(xs) < 3:
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx
    intercept = mean_y - slope * mean_x
    return {
        "slope": _round(slope),
        "intercept": _round(intercept),
        "from": min(xs),
        "to": max(xs),
    }


def _order(module: Module, entity: str, name: str, seen: list[str], given: list[str]) -> list[str]:
    """Categories in a sensible order: as given; else a choice field's choices, the status
    levels, the weekdays; else A to Z. Values not listed come last."""
    field = module.entities[entity].fields.get(name)
    if given:
        base = given
    elif isinstance(field, ChoiceField) and field.choices:
        base = field.choices
    elif seen and set(seen) <= set(module.status_levels):
        base = list(module.status_levels)
    elif seen and set(seen) <= set(WEEKDAYS):
        base = WEEKDAYS
    else:
        base = sorted(seen)
    return [c for c in base if c in seen] + [c for c in seen if c not in base]


def _aggregate(agg: str, values: list[float]) -> float | None:
    if agg == "count":
        return float(len(values))
    if not values:
        return None
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    if agg == "sum":
        return _round(sum(values))
    if agg == "latest":
        return values[-1]
    return _round(sum(values) / len(values))


def _week_label(start: dt.date) -> str:
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def _round(value: float) -> float:
    return round(value, 6)


def _labeller(module: Module, entity: str, labels: Mapping[str, str]) -> Callable[[str], str]:
    fields = module.entities[entity].fields

    def label(name: str) -> str:
        if name in labels:
            return labels[name]
        field = fields.get(name)
        if isinstance(field, BaseField):
            return field_label(name, field)
        text = name.replace("_", " ")
        return text[:1].upper() + text[1:]

    return label


def _worst(current: Value, value: Value) -> Value:
    if value is None:
        return current
    if current is None:
        return value
    return min(current, value, key=lambda v: WORST.get(str(v), 9))


def _month_start(day: dt.date, back: int) -> dt.date:
    """The first day of the month `back` months before the day's."""
    index = day.year * 12 + day.month - 1 - back
    return dt.date(index // 12, index % 12 + 1, 1)


def _next_month(month: dt.date) -> dt.date:
    return _month_start(month, -1)


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
