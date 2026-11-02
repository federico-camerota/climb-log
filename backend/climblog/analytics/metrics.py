# SPDX-License-Identifier: GPL-3.0-or-later
"""Metrics and metric queries (05-analytics.md §1, D-088, D-090).

A **metric** is a numeric stored field or derived value of an entity, named
`module.entity.field` (`journal.session.wb_score`); a **filter** is a choice field
(`journal.session.session_type`). A query takes metrics of any modules and lines them up:

- `group="none"`: one point per record (metrics of one entity only), as the line widget;
- `group="day" | "week" | "month"`: one point per period (weeks from Monday), each metric's
  values in it aggregated (`mean`, `min`, `max`, `sum`, `count` of values, or the `latest`).
  Modules are joined by the calendar day (D-088). Day points are the days with a record;
  week and month points run without gaps from the first period to the last;
- `lag=k`: every metric after the first is read k days later (its value of day d + k counts
  for day d), e.g. pain the morning after a session;
- `filters`: a choice field and the values kept; it applies to the metrics of its entity;
- `rolling=n`: the mean of each point's value and the n - 1 before it (values present).

Plain Python on the records (D-087): a few hundred records a year.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from climblog.expr import Value
from climblog.modules.checks import derived_plan
from climblog.modules.compute import Timeline
from climblog.modules.forms import field_label
from climblog.modules.schema import (
    BaseField,
    ChoiceField,
    DurationField,
    Module,
    NumberField,
    NumericScale,
    OrdinalScale,
    PercentField,
    ScaleField,
    Section,
)

Group = Literal["none", "day", "week", "month"]
Agg = Literal["mean", "min", "max", "sum", "count", "latest"]
Direction = Literal["higher_better", "lower_better", "neutral"]
Row = Mapping[str, Value]
Tables = Mapping[str, Sequence[Row]]

MAX_METRICS = 12
DIGITS = 6  # results are rounded to drop float noise (0.30000000000000004); the page formats


class QueryError(ValueError):
    """A query that can't be answered as asked (an unknown metric, a lag without groups, …)."""


@dataclass(frozen=True)
class Metric:
    id: str  # module.entity.field
    module: str
    entity: str
    field: str
    label: str  # the form's label, or the derived value's name
    section: str | None  # the section's label, to group metrics in a picker
    derived: bool
    unit: str | None  # h, kg, min, %
    scale: tuple[float, float] | None  # the values' range, if known
    direction: Direction | None  # higher or lower is better; None: unknown


@dataclass(frozen=True)
class Filter:
    id: str  # module.entity.field
    module: str
    entity: str
    field: str
    label: str
    choices: list[str]


@dataclass(frozen=True)
class Catalogue:
    metrics: list[Metric]
    filters: list[Filter]


def catalogue(name: str, module: Module) -> Catalogue:
    """The metrics and filters of a loaded module, configured as `name`, in YAML order: each
    entity's numeric fields, then its numeric derived values."""
    metrics: list[Metric] = []
    filters: list[Filter] = []
    for e_name, entity in module.entities.items():
        keys = set(entity.key or [])
        sections = entity.sections or {}

        for f_name, f in entity.fields.items():
            if f_name in keys or not isinstance(f, BaseField):
                continue
            ident = f"{name}.{e_name}.{f_name}"
            if isinstance(f, ChoiceField):
                label = field_label(f_name, f)
                choices = f.choices
                if choices is None:  # an ordinal scale's
                    ordinal = module.scales.get(f.scale or "")
                    choices = ordinal.choices if isinstance(ordinal, OrdinalScale) else []
                filters.append(Filter(ident, name, e_name, f_name, label, list(choices)))
                continue
            unit, scale, direction = _numeric(module, f)
            if unit is None and scale is None and direction is None and not _is_number(f):
                continue
            metrics.append(
                Metric(
                    ident,
                    name,
                    e_name,
                    f_name,
                    field_label(f_name, f),
                    _section_label(sections, f),
                    False,
                    unit,
                    scale,
                    direction,
                )
            )
        for step in derived_plan(module, e_name).steps:
            kind = step.kind
            if kind.type != "number" or kind.many:
                continue
            direction_: Direction | None = None
            if kind.lower_better is not None:
                direction_ = "lower_better" if kind.lower_better else "higher_better"
            text = step.key.replace("_", " ")
            metrics.append(
                Metric(
                    f"{name}.{e_name}.{step.key}",
                    name,
                    e_name,
                    step.key,
                    text[:1].upper() + text[1:],
                    None,
                    True,
                    None,
                    kind.scale,
                    direction_,
                )
            )
    return Catalogue(metrics, filters)


def _section_label(sections: Mapping[str, Section], f: BaseField) -> str | None:
    section = sections.get(f.section or "")
    return section.label if section is not None and section.label else None


def _is_number(f: BaseField) -> bool:
    return isinstance(f, NumberField | DurationField | PercentField | ScaleField)


def _numeric(
    module: Module, f: BaseField
) -> tuple[str | None, tuple[float, float] | None, Direction | None]:
    """A numeric field's unit, range and direction (all None for a field that isn't numeric)."""
    if isinstance(f, NumberField):
        scale = (f.min, f.max) if f.min is not None and f.max is not None else None
        return f.unit, scale, None
    if isinstance(f, DurationField):
        return "min", None, None
    if isinstance(f, PercentField):
        return "%", (0, 100), None
    if isinstance(f, ScaleField):
        found = module.scales.get(f.scale)
        if isinstance(found, NumericScale):
            return None, (found.min, found.max), found.direction
    return None, None, None


# ---- Queries ----


@dataclass(frozen=True)
class Query:
    metrics: Sequence[str]
    start: dt.date | None = None  # default: the first record's
    end: dt.date | None = None  # default: today; later records are left out
    group: Group = "day"
    agg: Agg = "mean"
    rolling: int | None = None
    lag: int = 0
    filters: Mapping[str, Sequence[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Point:
    start: dt.date  # the day, or the period's first day
    end: dt.date  # the period's last day (the day itself for days and records)
    label: str  # 2026-10-30, 2026-W44, 2026-10
    key: Mapping[str, Value] | None = None  # a record's key parts other than the date


@dataclass(frozen=True)
class Series:
    metric: str
    values: list[float | None]  # one per point
    n: list[int]  # the values behind each point
    rolling: list[float | None] | None  # one per point, with `rolling`


@dataclass(frozen=True)
class Result:
    group: Group
    agg: Agg
    lag: int
    points: list[Point]
    series: list[Series]


Source = tuple[Module, Tables]  # a module and its records with their derived values


def run_query(query: Query, sources: Mapping[str, Source], today: dt.date) -> Result:
    """Answer `query` from the modules' records (`sources[name]`, as configured)."""
    known = {
        m.id: m for name, (module, _) in sources.items() for m in catalogue(name, module).metrics
    }
    filters = {
        f.id: f for name, (module, _) in sources.items() for f in catalogue(name, module).filters
    }
    _check(query, known, filters)
    end = query.end or today
    wanted = [known[m] for m in query.metrics]

    def records(metric: Metric, shift: int) -> list[tuple[dt.date, Row]]:
        """The metric's entity's records kept by the filters, by the day they count for."""
        module, tables = sources[metric.module]
        timeline = Timeline(module.entities[metric.entity], list(tables.get(metric.entity, ())))
        kept = [
            (day - dt.timedelta(days=shift), row)
            for day, row in zip(timeline.days, timeline.rows, strict=True)
            if _kept(row, metric, query.filters)
        ]
        start = query.start or dt.date.min
        return [(day, row) for day, row in kept if start <= day <= end]

    found = [records(m, query.lag if i else 0) for i, m in enumerate(wanted)]
    if query.group == "none":
        entity = sources[wanted[0].module][0].entities[wanted[0].entity]
        key = [k for k in entity.key or [] if k != entity.date_field]
        return _per_record(query, wanted, found[0], key)
    first = min((day for rows in found for day, _ in rows), default=None)
    periods = _periods(query.group, query.start or first, end, found)
    series: list[Series] = []
    for metric, rows in zip(wanted, found, strict=True):
        buckets: dict[dt.date, list[float]] = {}
        for day, row in rows:
            value = _number(row.get(metric.field))
            if value is not None:
                buckets.setdefault(_period_start(query.group, day), []).append(value)
        values = [_aggregate(query.agg, buckets.get(p.start, [])) for p in periods]
        n = [len(buckets.get(p.start, [])) for p in periods]
        series.append(Series(metric.id, values, n, _rolling(values, query.rolling)))
    return Result(query.group, query.agg, query.lag, periods, series)


def _check(query: Query, known: Mapping[str, Metric], filters: Mapping[str, Filter]) -> None:
    if not query.metrics:
        raise QueryError("give at least one metric")
    if len(query.metrics) > MAX_METRICS:
        raise QueryError(f"at most {MAX_METRICS} metrics at once")
    unknown = [m for m in query.metrics if m not in known]
    if unknown:
        raise QueryError(f"unknown metric(s): {', '.join(unknown)}")
    for f_id, values in query.filters.items():
        if f_id not in filters:
            raise QueryError(f"unknown filter '{f_id}' (filters are choice fields)")
        wrong = [v for v in values if v not in filters[f_id].choices]
        if wrong:
            raise QueryError(f"'{f_id}' has no choice {', '.join(map(repr, wrong))}")
        entity = f_id.rpartition(".")[0]
        if not any(m.rpartition(".")[0] == entity for m in query.metrics):
            raise QueryError(f"filter '{f_id}' matches none of the metrics' entities")
    if query.rolling is not None and query.rolling < 2:
        raise QueryError("rolling must be 2 or more")
    if query.group == "none":
        entities = {m.rpartition(".")[0] for m in query.metrics}
        if len(entities) > 1:
            raise QueryError("one point per record needs metrics of one entity; group by day")
        if query.lag:
            raise QueryError("a lag needs points by day, week or month")
    if query.start is not None and query.end is not None and query.start > query.end:
        raise QueryError("start is after end")


def _kept(row: Row, metric: Metric, filters: Mapping[str, Sequence[str]]) -> bool:
    prefix = f"{metric.module}.{metric.entity}."
    return all(
        row.get(f_id.removeprefix(prefix)) in values
        for f_id, values in filters.items()
        if f_id.startswith(prefix) and "." not in f_id.removeprefix(prefix)
    )


def _per_record(
    query: Query, wanted: list[Metric], rows: list[tuple[dt.date, Row]], key: list[str]
) -> Result:
    points = [Point(day, day, day.isoformat(), {k: row.get(k) for k in key}) for day, row in rows]
    series = []
    for metric in wanted:
        values = [_round(_number(row.get(metric.field))) for _, row in rows]
        n = [0 if v is None else 1 for v in values]
        series.append(Series(metric.id, values, n, _rolling(values, query.rolling)))
    return Result("none", query.agg, 0, points, series)


def _period_start(group: Group, day: dt.date) -> dt.date:
    if group == "week":
        return day - dt.timedelta(days=day.weekday())
    if group == "month":
        return day.replace(day=1)
    return day


def _periods(
    group: Group, first: dt.date | None, end: dt.date, found: list[list[tuple[dt.date, Row]]]
) -> list[Point]:
    if first is None:
        return []
    if group == "day":
        days = sorted({day for rows in found for day, _ in rows})
        return [Point(d, d, d.isoformat()) for d in days]
    points: list[Point] = []
    current = _period_start(group, first)
    while current <= end:
        if group == "week":
            nxt = current + dt.timedelta(days=7)
            year, week, _ = current.isocalendar()
            label = f"{year}-W{week:02d}"
        else:
            nxt = (current + dt.timedelta(days=32)).replace(day=1)
            label = current.strftime("%Y-%m")
        points.append(Point(current, nxt - dt.timedelta(days=1), label))
        current = nxt
    return points


def _aggregate(agg: Agg, values: list[float]) -> float | None:
    if agg == "count":
        return float(len(values))
    if not values:
        return None
    if agg == "mean":
        return _round(sum(values) / len(values))
    if agg == "min":
        return min(values)
    if agg == "max":
        return max(values)
    if agg == "sum":
        return _round(sum(values))
    return values[-1]  # latest: the records are in (date, key) order


def _rolling(values: Sequence[float | None], n: int | None) -> list[float | None] | None:
    if n is None:
        return None
    out: list[float | None] = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - n + 1) : i + 1] if v is not None]
        out.append(_round(sum(window) / len(window)) if window else None)
    return out


def _number(value: Value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, DIGITS)
