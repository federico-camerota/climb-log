# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived values of whole tables, with the values records read from each other (D-045).

Child entities are computed before their parents, so `children(e).x` can read the children's
derived values. Within an entity, rows are computed in (date, key fields, row) order, so
`prev(x)` reads rows that are already complete. `parent.x`, `last(e.x, ...)` and
`window(e.x, ...)` read stored fields only, which need no order (the recommendation, computed
after every entity, reads derived values too: `recommend.py`).
"""

import datetime as dt
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from typing import Any

from climblog.expr import Value
from climblog.modules.checks import derived_plan
from climblog.modules.derived import DerivedPlan, compute
from climblog.modules.schema import Entity, Module

Row = Mapping[str, Value]
Table = Sequence[Row]


def compute_module(
    module: Module, tables: Mapping[str, Table], settings: Mapping[str, Value]
) -> dict[str, list[dict[str, Value]]]:
    """The derived values of every row of every entity, in the rows' order.

    `tables[entity]` holds the stored values of its rows (a missing entity has none);
    `settings` holds every setting of the module. Deferred entries are left out.
    """
    order = sorted(module.entities, key=lambda name: module.entities[name].parent is None)
    full: dict[str, list[dict[str, Value]]] = {}  # stored and derived values of each row
    result: dict[str, list[dict[str, Value]]] = {}
    for name in order:  # children first
        entity = module.entities[name]
        rows = tables.get(name, ())
        table = _Table(module, name, entity, rows, tables, full)
        plan = derived_plan(module, name)
        derived = table.run(plan, settings)
        full[name] = [{**row, **values} for row, values in zip(rows, derived, strict=True)]
        result[name] = derived
    return result


class Timeline:
    """An entity's dated rows in (date, key fields, row) order, for `last` and `window`."""

    def __init__(self, entity: Entity, rows: Table) -> None:
        order = _dated(entity, rows)
        self.days = [_row_day(entity, rows[i]) or dt.date.min for i in order]
        self.rows = [rows[i] for i in order]

    def last(self, name: str, day: dt.date, inclusive: bool = False) -> Value:
        """`name` in the latest row dated before `day` (on or before, `inclusive`)."""
        found = (bisect_right if inclusive else bisect_left)(self.days, day)
        return self.rows[found - 1].get(name) if found else None

    def window(self, name: str, start: dt.date, end: dt.date) -> list[Value]:
        """`name` in every row dated from `start` to `end`."""
        low, high = bisect_left(self.days, start), bisect_right(self.days, end)
        return [row.get(name) for row in self.rows[low:high]]


def _day(value: Any) -> dt.date | None:
    """A date or datetime as a day; anything else is no date."""
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else None


def _sort_key(value: Value) -> tuple[bool, Any]:
    """Blanks first; dates and datetimes as days."""
    day = _day(value)
    return (value is not None, day if day is not None else value)


class _Table:
    """One entity's rows, computing their derived values; it is the `Related` of each row."""

    def __init__(
        self,
        module: Module,
        name: str,
        entity: Entity,
        rows: Table,
        tables: Mapping[str, Table],
        full: Mapping[str, list[dict[str, Value]]],
    ) -> None:
        self.module = module
        self.entity = entity
        self.rows = rows
        self.tables = tables
        # Dated rows in (date, key, row) order: what prev() walks back through.
        self.dated = _dated(entity, rows)
        self.position = {index: i for i, index in enumerate(self.dated)}
        self.parent_rows = self._parents()
        self.child_rows = {
            child: _by_parent_key(other, full.get(child, []))
            for child, other in module.entities.items()
            if other.parent is not None and other.parent.entity == name
        }
        self.timelines: dict[str, Timeline] = {}  # for last() and window()
        self.done: dict[int, dict[str, Value]] = {}  # row index → stored and derived values
        self.current = 0

    def run(self, plan: DerivedPlan, settings: Mapping[str, Value]) -> list[dict[str, Value]]:
        undated = [i for i in range(len(self.rows)) if i not in self.position]
        derived: dict[int, dict[str, Value]] = {}
        for index in [*self.dated, *undated]:
            self.current = index
            values = compute(plan, self.rows[index], settings, self)
            derived[index] = values
            self.done[index] = {**self.rows[index], **values}
        return [derived[i] for i in range(len(self.rows))]

    # ---- Related ----

    def prev(self, name: str, n: int) -> Value:
        i = self.position.get(self.current)
        if i is None or i - n < 0:
            return None  # an undated row has no previous row
        return self.done[self.dated[i - n]].get(name)

    def parent(self, name: str) -> Value:
        parent = self.parent_rows.get(self.current)
        return None if parent is None else parent.get(name)

    def children(self, entity: str) -> Sequence[Mapping[str, Value]]:
        child = self.module.entities[entity]
        assert child.parent is not None
        row = self.rows[self.current]
        if any(row.get(k) != v for k, v in child.parent.fixed.items()):
            return ()
        key = tuple(_sort_key(row.get(k)) for k in child.parent.key)
        return self.child_rows[entity].get(key, ())

    def last(self, entity: str, name: str, day: dt.date, inclusive: bool = False) -> Value:
        return self.timeline(entity).last(name, day, inclusive)

    def window(self, entity: str, name: str, start: dt.date, end: dt.date) -> list[Value]:
        return self.timeline(entity).window(name, start, end)

    def timeline(self, entity: str) -> "Timeline":
        if entity not in self.timelines:
            self.timelines[entity] = Timeline(
                self.module.entities[entity], self.tables.get(entity, ())
            )
        return self.timelines[entity]

    # ---- Indexes ----

    def _parents(self) -> dict[int, Row]:
        """Each row's parent row, matched on `parent.key` and `parent.fixed`; none for orphans."""
        link = self.entity.parent
        if link is None:
            return {}
        parents = self.tables.get(link.entity, ())
        by_key: dict[tuple[Any, ...], Row] = {}
        for row in parents:
            if all(row.get(k) == v for k, v in link.fixed.items()):
                by_key.setdefault(tuple(_sort_key(row.get(k)) for k in link.key), row)
        found = {}
        for index, row in enumerate(self.rows):
            parent = by_key.get(tuple(_sort_key(row.get(k)) for k in link.key))
            if parent is not None:
                found[index] = parent
        return found


def _row_day(entity: Entity, row: Row) -> dt.date | None:
    return _day(row.get(entity.date_field))


def _dated(entity: Entity, rows: Table) -> list[int]:
    """Indexes of the rows that have a date, in (date, key fields, row) order."""
    dated = [i for i, row in enumerate(rows) if _row_day(entity, row) is not None]
    key = entity.key or []
    return sorted(
        dated,
        key=lambda i: (
            _row_day(entity, rows[i]),
            tuple(_sort_key(rows[i].get(k)) for k in key),
            i,
        ),
    )


def _by_parent_key(
    child: Entity, rows: list[dict[str, Value]]
) -> dict[tuple[Any, ...], list[dict[str, Value]]]:
    """A child entity's rows grouped by the parent key columns they repeat, in (date, key) order."""
    assert child.parent is not None
    groups: dict[tuple[Any, ...], list[dict[str, Value]]] = {}
    for i in _dated(child, rows) + [i for i, r in enumerate(rows) if _row_day(child, r) is None]:
        row = rows[i]
        groups.setdefault(tuple(_sort_key(row.get(k)) for k in child.parent.key), []).append(row)
    return groups
