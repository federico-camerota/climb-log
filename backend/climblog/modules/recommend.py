# SPDX-License-Identifier: GPL-3.0-or-later
"""The next-session recommendation of a module for a day (`recommendation:`, D-076).

Its values are computed after every entity's derived values, so `last(e.x, until=date)` and
`window(e.x, ...)` read stored fields and derived values alike; then the first rule that holds
gives the headline and message. The sheet's Summary tab compiles the same definition
(`formulas.recommendation_formulas`).
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from climblog.expr import Value, evaluate
from climblog.modules.checks import RecommendationPlan
from climblog.modules.compute import Table, Timeline
from climblog.modules.derived import compute
from climblog.modules.schema import Module


@dataclass(frozen=True)
class Reason:
    name: str
    label: str
    value: Value


@dataclass(frozen=True)
class Advice:
    label: str  # e.g. "Suggested next session"
    headline: str | None  # e.g. RECOVER; None when a rule gives a message alone
    message: str | None  # None: no rule holds (a module without a last rule)
    reasons: list[Reason]
    values: Mapping[str, Value]  # every value, the reasons among them

    @property
    def text(self) -> str:
        """As the legacy sheet shows it: "RECOVER — rest day or …"."""
        if self.headline is None:
            return self.message or ""
        return f"{self.headline} — {self.message}" if self.message else self.headline


def recommend(
    module: Module,
    plan: RecommendationPlan,
    tables: Mapping[str, Table],
    settings: Mapping[str, Value],
    day: dt.date,
) -> Advice:
    """The recommendation for `day`. `tables[entity]` holds each row's stored and derived
    values."""
    related = _Records(module, tables)
    values = compute(plan.values, {"date": day}, settings, related)
    scope = {"date": day, **values}
    reasons = [Reason(name, label, values.get(name)) for name, label in plan.reasons]
    for condition, headline, message in plan.rules:
        if condition is None or evaluate(condition, scope, settings, related) is True:
            return Advice(plan.label, headline, message, reasons, values)
    return Advice(plan.label, None, None, reasons, values)


class _Records:
    """The records a recommendation reads: no record of its own, so no prev, parent or
    children; `last` and `window` over every entity's rows."""

    def __init__(self, module: Module, tables: Mapping[str, Table]) -> None:
        self.module = module
        self.tables = tables
        self.timelines: dict[str, Timeline] = {}

    def prev(self, name: str, n: int) -> Value:
        return None

    def parent(self, name: str) -> Value:
        return None

    def children(self, entity: str) -> Sequence[Mapping[str, Value]]:
        return ()

    def last(self, entity: str, name: str, day: dt.date, inclusive: bool = False) -> Value:
        return self._timeline(entity).last(name, day, inclusive)

    def window(self, entity: str, name: str, start: dt.date, end: dt.date) -> list[Value]:
        return self._timeline(entity).window(name, start, end)

    def _timeline(self, entity: str) -> Timeline:
        if entity not in self.timelines:
            rows = self.tables.get(entity, ())
            self.timelines[entity] = Timeline(self.module.entities[entity], rows)
        return self.timelines[entity]
