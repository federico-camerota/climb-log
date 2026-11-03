# SPDX-License-Identifier: GPL-3.0-or-later
"""Grade charts (05-analytics.md §3.1, D-094) from a grade field: the journal's hardest grade
*tried* per session (not sends, so every chart says "tried").

French and gym grades are never converted (D-017, D-047): they are separate series on
separate axes. Gym grades are each gym's own scale, so they are one series per venue; French
grades are one series. Per period (month or week) the sessions are counted by grade, per
series (a "pyramid" of the hardest grade tried). By setting and by venue: sessions, the
hardest grade and the median one. A value that isn't a grade of the field's systems is left
out and counted.
"""

import datetime as dt
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from climblog.expr import Value
from climblog.grades import Grade, GradeError, parse_grade
from climblog.modules.compute import Timeline
from climblog.modules.schema import GradeField, GradesWidget, Module
from climblog.storage.cells import VALUE_ISSUES

Row = Mapping[str, Value]
Tables = Mapping[str, Sequence[Row]]
_LETTERS = ["a", "a+", "b", "b+", "c", "c+"]


def french_label(index: float) -> str:
    """6a for 30, 6a+ for 31, …; a half step (a slash grade's middle) rounds down."""
    step = int(index)
    return f"{step // 6 + 1}{_LETTERS[step % 6]}"


def grade_charts(
    module: Module, widget: GradesWidget, tables: Tables, day: dt.date
) -> dict[str, Any]:
    entity, name = widget.grade.split(".", 1)
    field = module.entities[entity].fields[name]
    systems = field.systems if isinstance(field, GradeField) else []
    venue = widget.venue.split(".", 1)[1] if widget.venue else None
    setting = widget.setting.split(".", 1)[1] if widget.setting else None
    timeline = Timeline(module.entities[entity], list(tables.get(entity, ())))
    points: list[dict[str, Any]] = []
    unparsed = 0
    for when, row in zip(timeline.days, timeline.rows, strict=True):
        text = row.get(name)
        if when > day:
            continue
        if name in str(row.get(VALUE_ISSUES) or "").split(","):
            unparsed += 1  # not a grade: a data issue, blanked on load
            continue
        if text in (None, ""):
            continue
        try:
            grade = parse_grade(str(text), systems)
        except GradeError:
            unparsed += 1
            continue
        points.append(
            {
                "date": when,
                "grade": grade,
                "venue": _text(row.get(venue)) if venue else None,
                "setting": _text(row.get(setting)) if setting else None,
            }
        )
    series = _series(points, venue is not None)
    return {
        "widget": "grades",
        "label": widget.label,
        "series": [
            {
                "system": system,
                "venue": where,
                "label": "French" if system == "french" else f"Gym · {where}" if where else "Gym",
                "points": [
                    {
                        "date": p["date"].isoformat(),
                        "index": p["grade"].index,
                        "grade": p["grade"].text,
                        "setting": p["setting"],
                        "venue": p["venue"],
                    }
                    for p in found
                ],
            }
            for (system, where), found in series.items()
        ],
        "french_ticks": _french_ticks(points),
        "pyramid": _pyramid(series, widget.group),
        "by_setting": _table(points, "setting", gym_by_venue=venue is not None) if setting else [],
        "by_venue": _table(points, "venue") if venue else [],
        "unparsed": unparsed,
        "last": widget.last,
    }


def _series(
    points: list[dict[str, Any]], by_venue: bool
) -> dict[tuple[str, str | None], list[dict[str, Any]]]:
    """French first, then gym grades per venue (A to Z), each oldest first."""
    found: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for p in points:
        grade: Grade = p["grade"]
        where = p["venue"] if grade.system == "gym" and by_venue else None
        found.setdefault((grade.system, where), []).append(p)
    return dict(sorted(found.items(), key=lambda kv: (kv[0][0] != "french", kv[0][1] or "")))


def _french_ticks(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A label for every French step between the easiest and hardest grade logged."""
    indexes = [p["grade"].index for p in points if p["grade"].system == "french"]
    if not indexes:
        return []
    low, high = int(min(indexes)), int(max(indexes) + 0.5)
    return [{"index": i, "label": french_label(i)} for i in range(low, high + 1)]


def _pyramid(
    series: Mapping[tuple[str, str | None], list[dict[str, Any]]], group: str
) -> dict[str, Any]:
    starts = sorted({_period(p["date"], group) for found in series.values() for p in found})
    periods = _all_periods(starts, group)
    index = {p: i for i, p in enumerate(periods)}
    rows = []
    for (system, where), found in series.items():
        grades = sorted({p["grade"].index for p in found})
        counts = [[0 for _ in periods] for _ in grades]
        for p in found:
            counts[grades.index(p["grade"].index)][index[_period(p["date"], group)]] += 1
        texts = {p["grade"].index: p["grade"].text for p in found}  # a slash grade as logged
        rows.append(
            {
                "label": "French" if system == "french" else f"Gym · {where}" if where else "Gym",
                "grades": [texts[g] for g in grades],
                "counts": counts,  # [grade][period], easiest grade first
            }
        )
    return {"periods": [_period_label(p, group) for p in periods], "rows": rows}


def _period(day: dt.date, group: str) -> dt.date:
    return day.replace(day=1) if group == "month" else day - dt.timedelta(days=day.weekday())


def _all_periods(starts: list[dt.date], group: str) -> list[dt.date]:
    if not starts:
        return []
    out, current = [], starts[0]
    while current <= starts[-1]:
        out.append(current)
        current = (
            (current + dt.timedelta(days=32)).replace(day=1)
            if group == "month"
            else current + dt.timedelta(days=7)
        )
    return out


def _period_label(start: dt.date, group: str) -> str:
    if group == "month":
        return start.strftime("%Y-%m")
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def _table(
    points: list[dict[str, Any]], key: str, gym_by_venue: bool = False
) -> list[dict[str, Any]]:
    """Per value of `key` and grade system: sessions, the hardest grade and the median one.
    With `gym_by_venue`, gym grades also per venue: each gym grades its own way (D-094)."""
    groups: dict[tuple[str, str, str], list[Grade]] = {}
    for p in points:
        if p[key] is not None:
            system = p["grade"].system
            where = (p["venue"] or "") if gym_by_venue and system == "gym" else ""
            groups.setdefault((p[key], system, where), []).append(p["grade"])
    rows = []
    for (value, system, where), grades in sorted(
        groups.items(), key=lambda kv: (kv[0][1] != "french", kv[0][0], kv[0][2])
    ):
        indexes = [g.index for g in grades]
        texts = {g.index: g.text for g in grades}
        rows.append(
            {
                key: value,
                **({"venue": where or None} if gym_by_venue else {}),
                "system": system,
                "sessions": len(grades),
                "hardest": texts[max(indexes)],
                "median": texts[statistics.median_low(indexes)],
            }
        )
    return rows


def _text(value: Value) -> str | None:
    return None if value is None or value == "" else str(value)
