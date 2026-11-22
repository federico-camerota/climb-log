# SPDX-License-Identifier: GPL-3.0-or-later
"""The widgets of a program's dashboard (D-117): a table by program week, the program grid and
the retests before/after.

They read the latest run started on or before the day (D-109) and the reference tables (D-112).
The week table reproduces the legacy shoulder Dashboard (00-current-state.md §3): counts are 0 in
a week without records, a mean or a share of nothing is blank, and the log completion is the
records logged for a plan week ÷ the plan's exercises (the legacy Session Log had one row per
exercise and week).
"""

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from climblog.expr import Value
from climblog.modules.program import Runs
from climblog.modules.schema import (
    BeforeAfterWidget,
    ChoiceField,
    Module,
    ProgramGridWidget,
    RefField,
    WeekTableColumn,
    WeekTableWidget,
)

Row = Mapping[str, Value]
Rows = Callable[[str], Sequence[tuple[dt.date, Row]]]  # an entity's records up to the day
Reference = Mapping[str, Sequence[Row]]


def week_table(
    module: Module, widget: WeekTableWidget, rows: Rows, runs: Runs, day: dt.date, ref: Reference
) -> dict[str, Any]:
    """A row per program week of the latest run, up to the program's last week (or the
    current one, past it), with each column's value."""
    assert module.program is not None  # checked at load
    now = runs.at(day)
    columns = [{"label": c.label, "agg": c.agg} for c in widget.columns]
    base = {"widget": "week_table", "label": widget.label, "columns": columns}
    if now is None:
        return {**base, "run": None, "current": None, "weeks": []}
    last = max(module.program.weeks, now.week)
    values = [_column(c, rows, now.run, last, ref) for c in widget.columns]
    return {
        **base,
        "run": now.run,
        "current": now.week,
        "weeks": [
            {
                "week": w,
                "phase": module.program.phase(w),
                "light": module.program.is_light_week(w),
                "values": [v[w - 1] for v in values],
            }
            for w in range(1, last + 1)
        ],
    }


def _column(
    column: WeekTableColumn, rows: Rows, run: int, last: int, ref: Reference
) -> list[float | None]:
    entity, _, name = column.metric.partition(".")
    found: list[list[Value]] = [[] for _ in range(last)]
    for _, row in rows(entity):
        week = _week(row, column.week)
        if row.get("run") == run and week is not None and 1 <= week <= last:
            found[week - 1].append(row.get(name))
    if column.agg == "count":
        return [float(sum(1 for v in vs if _counted(v, column.equals))) for vs in found]
    if column.agg == "share":
        whole = len(live_rows(ref.get(column.of or "", ())))
        shares = [sum(1 for v in vs if v is True) for vs in found]
        return [n / whole if n and whole else None for n in shares]
    numbers = [[float(v) for v in vs if _is_number(v)] for vs in found]  # type: ignore[arg-type]
    if column.agg == "sum":
        return [sum(ns) if ns else None for ns in numbers]
    return [sum(ns) / len(ns) if ns else None for ns in numbers]  # unrounded, as AVERAGEIFS


def _counted(value: Value, equals: str | bool | float | None) -> bool:
    if value is None or value == "":
        return False
    if equals is None:
        return True
    if isinstance(equals, bool) or isinstance(value, bool):
        return value is equals
    return value == equals


def _week(row: Row, field: str) -> int | None:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _is_number(value: Value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def live_rows(rows: Sequence[Row]) -> list[Row]:
    """A reference table's rows, retired ones left out."""
    return [r for r in rows if r.get("retired") is not True]


def program_grid(
    module: Module,
    widget: ProgramGridWidget,
    rows: Rows,
    runs: Runs,
    day: dt.date,
    ref: Reference,
) -> dict[str, Any]:
    """The reference table's rows by the program weeks of the latest run: each cell the
    prescription, the records logged for it and their worst quality; the share logged per week
    (the legacy log completion) and, per row, the weeks logged among those prescribed so far."""
    assert module.program is not None and module.reference is not None  # checked at load
    table = module.reference[widget.reference]
    entity = module.entities[widget.entity]
    link = next(
        n
        for n, f in entity.fields.items()
        if isinstance(f, RefField) and f.reference == widget.reference
    )
    quality = entity.fields.get(widget.quality or "")
    qualities = (quality.choices or []) if isinstance(quality, ChoiceField) else []
    items = live_rows(ref.get(widget.reference, ()))
    now = runs.at(day)
    last = max(module.program.weeks, now.week if now else 0)
    logged: dict[tuple[str, int], list[Value]] = {}  # (item, week) → the qualities logged
    if now is not None:
        for _, row in rows(widget.entity):
            week = _week(row, widget.week)
            done_for = row.get(link)
            if row.get("run") != now.run or week is None or not 1 <= week <= last:
                continue
            if done_for is None:
                continue
            if widget.logged is not None and row.get(widget.logged) is not True:
                continue
            logged.setdefault((str(done_for).casefold(), week), []).append(
                row.get(widget.quality) if widget.quality else None
            )
    skip = {s.casefold() for s in widget.skip}
    current = now.week if now else 0
    out_rows = []
    for item in items:
        key = str(item.get(table.key))
        cells = []
        prescribed = done = 0
        for w in range(1, last + 1):
            text = item.get(f"w{w}")
            skipped = text is None or str(text).strip().casefold() in skip
            found = logged.get((key.casefold(), w), [])
            if not skipped and w <= current:
                prescribed += 1
                done += 1 if found else 0
            cells.append(
                {
                    "prescribed": _text_or_number(text),
                    "skip": skipped,
                    "logged": len(found),
                    "quality": _worst_of(found, qualities),
                }
            )
        out_rows.append(
            {
                "key": key,
                "name": _text_or_none(item.get("name")),
                "group": _text_or_none(item.get(widget.group)) if widget.group else None,
                "cells": cells,
                "share": done / prescribed if prescribed else None,
            }
        )
    if widget.group is not None:
        field = table.fields.get(widget.group)
        order = (field.choices or []) if isinstance(field, ChoiceField) else []
        rank = {c: i for i, c in enumerate(order)}
        out_rows.sort(key=lambda r: rank.get(str(r["group"]), len(order)))  # stable: table order
    whole = len(items)
    shares = []
    for w in range(1, last + 1):
        n = sum(len(v) for (_, week), v in logged.items() if week == w)
        shares.append(n / whole if n and whole else None)
    return {
        "widget": "program_grid",
        "label": widget.label,
        "run": now.run if now else None,
        "current": now.week if now else None,
        "qualities": qualities,
        "weeks": [
            {
                "week": w,
                "phase": module.program.phase(w),
                "light": module.program.is_light_week(w),
                "share": shares[w - 1],
            }
            for w in range(1, last + 1)
        ],
        "rows": out_rows,
    }


def _text_or_none(value: Value) -> str | None:
    return None if value is None or value == "" else str(value)


def _text_or_number(value: Value) -> str | float | None:
    if _is_number(value):
        return float(value)  # type: ignore[arg-type]
    return _text_or_none(value)


def _worst_of(found: list[Value], qualities: list[str]) -> str | None:
    """The worst quality logged: the latest in the choices' order."""
    rank = {q: i for i, q in enumerate(qualities)}
    known = [str(q) for q in found if q is not None and str(q) in rank]
    return max(known, key=lambda q: rank[q]) if known else None


def before_after(
    module: Module, widget: BeforeAfterWidget, rows: Rows, ref: Reference
) -> dict[str, Any]:
    """Each item of the reference table by the checkpoints: the latest value recorded there
    and its date; the change from the first checkpoint to the latest one with a value."""
    entity = module.entities[widget.entity]
    by, across = entity.fields[widget.by], entity.fields[widget.across]
    assert isinstance(by, RefField) and module.reference is not None  # checked at load
    checkpoints = (across.choices or []) if isinstance(across, ChoiceField) else []
    table = module.reference[by.reference]
    found: dict[tuple[str, str], tuple[dt.date, Value]] = {}
    for when, row in rows(widget.entity):
        item, point = row.get(widget.by), row.get(widget.across)
        value = row.get(widget.value)
        if item is None or point is None or value in (None, ""):
            continue
        found[(str(item).casefold(), str(point))] = (when, value)  # in date order: the latest
    out = []
    for entry in live_rows(ref.get(by.reference, ())):
        key = str(entry.get(table.key))
        kind = entry.get(widget.value_type) if widget.value_type else None
        cells: list[dict[str, Any] | None] = []
        for point in checkpoints:
            hit = found.get((key.casefold(), point))
            if hit is None:
                cells.append(None)
                continue
            when, value = hit
            number = _parse_number(value) if kind in (None, "number") else None
            cells.append(
                {"date": when.isoformat(), "value": number if number is not None else str(value)}
            )
        direction = entry.get(widget.direction) if widget.direction else None
        out.append(
            {
                "key": key,
                "label": _text_or_none(entry.get(widget.item_label)) or key,
                "cells": cells,
                "change": _change(cells, direction),
            }
        )
    return {
        "widget": "before_after",
        "label": widget.label,
        "checkpoints": checkpoints,
        "rows": out,
    }


def _parse_number(value: Value) -> float | None:
    if _is_number(value):
        return float(value)  # type: ignore[arg-type]
    try:
        return float(str(value).strip().replace(",", "."))  # a decimal comma, as typed
    except ValueError:
        return None


def _change(cells: list[dict[str, Any] | None], direction: Value) -> dict[str, Any] | None:
    """From the first checkpoint to the latest one with a value: a difference of numbers (with
    whether it is better, by the item's direction), else the two values."""
    first = cells[0] if cells else None
    latest = next((c for c in reversed(cells[1:]) if c is not None), None)
    if first is None or latest is None:
        return None
    a, b = first["value"], latest["value"]
    if isinstance(a, float) and isinstance(b, float):
        diff = round(b - a, 6)
        better = None
        if diff and direction in ("higher_better", "lower_better"):
            better = (diff > 0) == (direction == "higher_better")
        return {"diff": diff, "better": better, "first": None, "latest": None}
    return {"diff": None, "better": None, "first": str(a), "latest": str(b)}
