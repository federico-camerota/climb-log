# SPDX-License-Identifier: GPL-3.0-or-later
"""Training load (05-analytics.md §3.1, D-092): weekly load, the acute:chronic workload ratio,
monotony, strain and streaks, from each record's session-RPE load (duration x effort).

- **Weekly load**: the sum of the records' loads, Monday to Sunday. A record missing one of
  the `inputs` (or its load) counts as 0 and the week says how many there were, so a low week
  isn't silently wrong.
- **ACWR**: exponentially weighted moving averages of the daily load (days without a record
  are 0), lambda = 2 / (N + 1) for the acute (7 days) and chronic (28 days) windows (Williams
  et al. 2017), both starting at the mean daily load of the first `chronic` days: started at 0,
  the chronic average would still miss ~14% of a steady load on day 28, and the ratio would
  read ~16% high for weeks. It is shown from the
  first record's day + chronic - 1 on (before: "building a baseline"), at each week's last day
  (the asked day for the current week). Context with zones, not a rule.
- **Monotony** (Foster): the mean daily load of the week's days (up to the asked day, from the
  first record's) over their standard deviation (sample); none under 2 days or with no
  spread. **Strain**: the week's load x its monotony.
- **Streaks**: runs of consecutive days with a record; the current one ends on the asked day
  or the day before.
- Other modules' loads are given per week (with their records without a value), but not in
  the ratio, monotony or strain: their units differ (e.g. sets x RPE).
"""

import datetime as dt
import statistics
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from climblog.expr import Value
from climblog.modules.compute import Timeline
from climblog.modules.schema import Module, TrainingLoadWidget

Row = Mapping[str, Value]
Tables = Mapping[str, Sequence[Row]]
Other = Callable[[str], tuple[Module, Tables] | None]  # a module by its `module:` id


def training_load(
    module: Module, widget: TrainingLoadWidget, tables: Tables, day: dt.date, others: Other
) -> dict[str, Any]:
    entity, name = widget.load.split(".", 1)
    inputs = [i.split(".", 1)[1] for i in widget.inputs]
    timeline = Timeline(module.entities[entity], list(tables.get(entity, ())))
    daily: dict[dt.date, float] = {}
    missing: dict[dt.date, int] = {}
    for when, row in zip(timeline.days, timeline.rows, strict=True):
        if when > day:
            continue
        load = _number(row.get(name))
        if load is None or any(row.get(i) in (None, "") for i in inputs):
            missing[when] = missing.get(when, 0) + 1
            load = load or 0.0
        daily[when] = daily.get(when, 0.0) + load
    sessions = _count_by_day(timeline, day)
    rest_days = _rest_days(module, widget.rest, tables, day)

    stacks: list[dict[str, Any]] = []
    absent: list[str] = []
    for source in widget.others:
        found = others(source.module)
        if found is None:
            absent.append(source.label)
            continue
        other_module, other_tables = found
        o_entity, o_name = source.metric.split(".", 1)
        if o_entity not in other_module.entities:
            absent.append(source.label)
            continue
        o_timeline = Timeline(other_module.entities[o_entity], list(other_tables.get(o_entity, ())))
        per_day: dict[dt.date, float] = {}
        without: dict[dt.date, int] = {}
        for when, row in zip(o_timeline.days, o_timeline.rows, strict=True):
            if when > day:
                continue
            value = _number(row.get(o_name))
            if value is None:
                without[when] = without.get(when, 0) + 1
            else:
                per_day[when] = per_day.get(when, 0.0) + value
        stacks.append({"label": source.label, "daily": per_day, "without": without})

    firsts = [min(d) for d in [daily, *(s["daily"] | s["without"] for s in stacks)] if d]
    if not firsts:
        return _empty(widget, absent)
    first = min(firsts)
    weeks = _weeks(first, day)
    ratio = _acwr(daily, min(daily) if daily else first, day, widget.acute, widget.chronic)
    baseline = (min(daily) if daily else first) + dt.timedelta(days=widget.chronic - 1)
    rows = []
    for start in weeks:
        end = min(start + dt.timedelta(days=6), day)
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        in_range = [d for d in days if d >= first]
        loads = [daily.get(d, 0.0) for d in in_range]
        total = sum(loads)
        mono = _monotony(loads)
        rows.append(
            {
                "label": _week_label(start),
                "start": start.isoformat(),
                "load": _round(total),
                "sessions": sum(sessions.get(d, 0) for d in days),
                "days": sum(1 for d in days if d in sessions),
                "without_load": sum(missing.get(d, 0) for d in days),
                "rest_days": sum(1 for d in days if d in rest_days),
                "others": [_round(sum(s["daily"].get(d, 0.0) for d in days)) for s in stacks],
                "others_without": [sum(s["without"].get(d, 0) for d in days) for s in stacks],
                "acwr": ratio.get(end),
                "monotony": mono,
                "strain": None if mono is None else _round(total * mono),
            }
        )
    longest, current = _streaks(sorted(sessions), day)
    return {
        "widget": "training_load",
        "label": widget.label,
        "others": [s["label"] for s in stacks],
        "absent": absent,
        "zones": widget.zones,
        "acute": widget.acute,
        "chronic": widget.chronic,
        "baseline_from": baseline.isoformat(),
        "acwr_today": ratio.get(day),
        "weeks": rows,
        "shown": widget.weeks,
        "longest_streak": longest,
        "current_streak": current,
    }


def _empty(widget: TrainingLoadWidget, absent: list[str]) -> dict[str, Any]:
    return {
        "widget": "training_load",
        "label": widget.label,
        "others": [],
        "absent": absent,
        "zones": widget.zones,
        "acute": widget.acute,
        "chronic": widget.chronic,
        "baseline_from": None,
        "acwr_today": None,
        "weeks": [],
        "shown": widget.weeks,
        "longest_streak": None,
        "current_streak": 0,
    }


def _count_by_day(timeline: Timeline, day: dt.date) -> dict[dt.date, int]:
    found: dict[dt.date, int] = {}
    for when in timeline.days:
        if when <= day:
            found[when] = found.get(when, 0) + 1
    return found


def _rest_days(module: Module, rest: str | None, tables: Tables, day: dt.date) -> set[dt.date]:
    if rest is None:
        return set()
    timeline = Timeline(module.entities[rest], list(tables.get(rest, ())))
    return {d for d in timeline.days if d <= day}


def _weeks(first: dt.date, day: dt.date) -> list[dt.date]:
    start = first - dt.timedelta(days=first.weekday())
    last = day - dt.timedelta(days=day.weekday())
    return [start + dt.timedelta(days=7 * i) for i in range((last - start).days // 7 + 1)]


def _acwr(
    daily: Mapping[dt.date, float], first: dt.date, day: dt.date, acute: int, chronic: int
) -> dict[dt.date, float]:
    """The ratio of each day from the baseline on (the chronic window filled). Both averages
    start at the mean daily load of the first `chronic` days, so a steady load gives 1 from
    the start (from 0, the chronic average lags for weeks and the ratio reads high)."""
    if not daily:
        return {}
    la, lc = 2 / (acute + 1), 2 / (chronic + 1)
    seed = sum(daily.get(first + dt.timedelta(days=i), 0.0) for i in range(chronic)) / chronic
    a = c = seed
    found: dict[dt.date, float] = {}
    current = first
    while current <= day:
        load = daily.get(current, 0.0)
        a = load * la + (1 - la) * a
        c = load * lc + (1 - lc) * c
        if (current - first).days >= chronic - 1 and c > 0:
            found[current] = _round(a / c, 2)
        current += dt.timedelta(days=1)
    return found


def _monotony(loads: list[float]) -> float | None:
    if len(loads) < 2:
        return None
    spread = statistics.stdev(loads)
    return None if spread == 0 else _round(statistics.fmean(loads) / spread, 2)


def _streaks(days: list[dt.date], day: dt.date) -> tuple[dict[str, Any] | None, int]:
    """The longest run of consecutive days with a record (the latest if tied), and the length
    of the run ending on `day` or the day before."""
    if not days:
        return None, 0
    runs: list[tuple[dt.date, dt.date]] = []
    start = end = days[0]
    for current in days[1:]:
        if current == end + dt.timedelta(days=1):
            end = current
        else:
            runs.append((start, end))
            start = end = current
    runs.append((start, end))
    best = max(runs, key=lambda r: ((r[1] - r[0]).days, r[1]))
    last_start, last_end = runs[-1]
    current_run = (last_end - last_start).days + 1 if (day - last_end).days <= 1 else 0
    longest = {
        "days": (best[1] - best[0]).days + 1,
        "start": best[0].isoformat(),
        "end": best[1].isoformat(),
    }
    return longest, current_run


def _week_label(start: dt.date) -> str:
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def _number(value: Value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _round(value: float, digits: int = 1) -> float:
    return round(value, digits)
