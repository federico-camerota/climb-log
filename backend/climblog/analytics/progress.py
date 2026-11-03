# SPDX-License-Identifier: GPL-3.0-or-later
"""Before/after changes and body maps (05-analytics.md §3.1, D-093).

- `pre_post`: for each pair of the same question asked before and after a session (mood,
  each body part's soreness), the mean before, after and of the change over the records that
  have both (n), for all records and per value of `by` (the session type). A lower-is-better
  scale says so, so the page can tell a drop in soreness is good.
- `body_heatmap`: a template's fields (the body parts) by week, each cell the week's mean of
  the values present, per source (before sessions, after them, rest days).
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from climblog.expr import Value
from climblog.modules.compute import Timeline
from climblog.modules.forms import field_label
from climblog.modules.schema import (
    BaseField,
    BodyHeatmapWidget,
    ChoiceField,
    Module,
    NumericScale,
    PrePostWidget,
    ScaleField,
)

Row = Mapping[str, Value]
Tables = Mapping[str, Sequence[Row]]


def pre_post(module: Module, widget: PrePostWidget, tables: Tables, day: dt.date) -> dict[str, Any]:
    pairs = _pairs(module, widget)
    entity = pairs[0][1].partition(".")[0]
    rows = _rows(module, entity, tables, day)
    by = widget.by.partition(".")[2] if widget.by else None
    groups: list[str] = []
    if by is not None:
        seen = list(dict.fromkeys(str(r.get(by)) for r in rows if r.get(by) not in (None, "")))
        field = module.entities[entity].fields.get(by)
        order = field.choices if isinstance(field, ChoiceField) and field.choices else sorted(seen)
        groups = [g for g in order if g in seen] + [g for g in seen if g not in order]
    out = []
    for label, pre, post in pairs:
        pre_name, post_name = pre.partition(".")[2], post.partition(".")[2]
        out.append(
            {
                "label": label,
                "lower_better": _lower_better(module, entity, pre_name),
                "all": _stats(rows, pre_name, post_name),
                "groups": [
                    _stats([r for r in rows if str(r.get(by)) == g], pre_name, post_name)
                    for g in groups
                ]
                if by
                else [],
            }
        )
    return {"widget": "pre_post", "label": widget.label, "groups": groups, "pairs": out}


def _pairs(module: Module, widget: PrePostWidget) -> list[tuple[str, str, str]]:
    found = [(p.label, p.pre, p.post) for p in widget.pairs]
    for tp in widget.template_pairs:
        for name, f in module.templates[tp.template].items():
            label = field_label(name, f) if isinstance(f, BaseField) else name
            found.append((label, tp.pre + name, tp.post + name))
    return found


def _stats(rows: Sequence[Row], pre: str, post: str) -> dict[str, Any]:
    both = [
        (b, a)
        for r in rows
        if (b := _number(r.get(pre))) is not None and (a := _number(r.get(post))) is not None
    ]
    if not both:
        return {"n": 0, "pre": None, "post": None, "change": None}
    n = len(both)
    before, after = sum(b for b, _ in both) / n, sum(a for _, a in both) / n
    return {"n": n, "pre": _round(before), "post": _round(after), "change": _round(after - before)}


def _lower_better(module: Module, entity: str, name: str) -> bool | None:
    field = module.entities[entity].fields.get(name)
    if isinstance(field, ScaleField):
        scale = module.scales.get(field.scale)
        if isinstance(scale, NumericScale) and scale.direction != "neutral":
            return scale.direction == "lower_better"
    return None


def body_heatmap(
    module: Module, widget: BodyHeatmapWidget, tables: Tables, day: dt.date
) -> dict[str, Any]:
    parts = list(module.templates[widget.template].items())
    found: list[tuple[str, str, list[tuple[dt.date, Row]]]] = []
    for source in widget.sources:
        entity, _, prefix = source.fields.partition(".")
        timeline = Timeline(module.entities[entity], list(tables.get(entity, ())))
        dated = [(d, r) for d, r in zip(timeline.days, timeline.rows, strict=True) if d <= day]
        found.append((source.label, prefix, dated))
    firsts = [rows[0][0] for _, _, rows in found if rows]
    if not firsts:
        weeks: list[dt.date] = []
    else:
        first = min(firsts)
        start = first - dt.timedelta(days=first.weekday())
        last = day - dt.timedelta(days=day.weekday())
        weeks = [start + dt.timedelta(days=7 * i) for i in range((last - start).days // 7 + 1)]
    index = {w: i for i, w in enumerate(weeks)}
    sources = []
    for label, prefix, rows in found:
        cells: list[list[list[float]]] = [[[] for _ in weeks] for _ in parts]
        for when, row in rows:
            week = index[when - dt.timedelta(days=when.weekday())]
            for p, (name, _) in enumerate(parts):
                value = _number(row.get(prefix + name))
                if value is not None:
                    cells[p][week].append(value)
        sources.append(
            {
                "label": label,
                "values": [[_mean(c) for c in row] for row in cells],
                "n": [[len(c) for c in row] for row in cells],
            }
        )
    scale = _template_scale(module, widget.template)
    return {
        "widget": "body_heatmap",
        "label": widget.label,
        "parts": [field_label(n, f) if isinstance(f, BaseField) else n for n, f in parts],
        "weeks": [_week_label(w) for w in weeks],
        "starts": [w.isoformat() for w in weeks],
        "sources": sources,
        "scale": scale,
        "lower_better": _template_lower_better(module, widget.template),
        "shown": widget.weeks,
    }


def _template_scale(module: Module, template: str) -> tuple[float, float] | None:
    for f in module.templates[template].values():
        if isinstance(f, ScaleField):
            scale = module.scales.get(f.scale)
            if isinstance(scale, NumericScale):
                return (scale.min, scale.max)
    return None


def _template_lower_better(module: Module, template: str) -> bool | None:
    for f in module.templates[template].values():
        if isinstance(f, ScaleField):
            scale = module.scales.get(f.scale)
            if isinstance(scale, NumericScale) and scale.direction != "neutral":
                return scale.direction == "lower_better"
    return None


def _rows(module: Module, entity: str, tables: Tables, day: dt.date) -> list[Row]:
    timeline = Timeline(module.entities[entity], list(tables.get(entity, ())))
    return [r for d, r in zip(timeline.days, timeline.rows, strict=True) if d <= day]


def _week_label(start: dt.date) -> str:
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def _mean(values: list[float]) -> float | None:
    return _round(sum(values) / len(values)) if values else None


def _number(value: Value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _round(value: float) -> float:
    return round(value, 2)
