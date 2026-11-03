# SPDX-License-Identifier: GPL-3.0-or-later
"""Correlations between metrics (05-analytics.md §0 and §3.2, D-096): small-data honesty first.

Every statistic comes with n and a 95% confidence interval, and is flagged `too_few` under the
app's minimum n (default 10); the words stay descriptive ("goes with"), never causal.

- **Pair**: X and Y lined up per record (one entity, no lag) or per day (D-088), Y read `lag`
  days later; Pearson r with its CI by Fisher's z (SE = 1 / sqrt(n - 3)), Spearman rho with
  the Bonett-Wright SE (sqrt((1 + rho^2 / 2) / (n - 3))), the p-values of scipy.stats, and the
  least-squares line.
- **Matrix**: Spearman (default) or Pearson for every pair of the metrics, each over the points
  where both have a value; a cell under the minimum n is hidden.
- **What goes with a good session**: each pre-session metric (asked before climbing, or
  computed from such answers and the date only) against a session score, ranked by |r|, so it
  can be read *before* a session. With many metrics some associations appear by chance: the
  page says so (no correction).
"""

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from scipy import stats

from climblog.analytics.metrics import Metric, Query, QueryError, Source, catalogue, run_query
from climblog.modules.checks import derived_plan
from climblog.modules.schema import BaseField, Module

Method = Literal["pearson", "spearman"]
Z95 = 1.959963984540054  # the normal distribution's 97.5% point


@dataclass(frozen=True)
class Stat:
    r: float | None
    low: float | None  # the 95% CI
    high: float | None
    p: float | None


@dataclass(frozen=True)
class Pair:
    x: str
    y: str
    lag: int
    n: int
    too_few: bool
    pearson: Stat
    spearman: Stat
    slope: float | None
    intercept: float | None
    points: list[tuple[float, float, str]]  # x, y, the day (or the record's day)


def aligned(
    x: str,
    y: str,
    sources: Mapping[str, Source],
    today: dt.date,
    *,
    lag: int = 0,
    group: Literal["none", "day", "week", "month"] | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    filters: Mapping[str, Sequence[str]] | None = None,
) -> list[tuple[float, float, str]]:
    """The (x, y, day) pairs where both have a value: per record within one entity without a
    lag, else per day (or the given group), y read `lag` days later."""
    same = x.rpartition(".")[0] == y.rpartition(".")[0]
    chosen = group or ("none" if same and lag == 0 else "day")
    if chosen == "none" and not (same and lag == 0):
        raise QueryError("one point per record needs both metrics of one entity and no lag")
    # a filter applies to its entity's metrics: those of other entities are left out here (a
    # matrix pair of rest days and finger sessions under an "only Climbing" filter)
    entities = {x.rpartition(".")[0], y.rpartition(".")[0]}
    kept = {f: v for f, v in (filters or {}).items() if f.rpartition(".")[0] in entities}
    query = Query([x, y], start=start, end=end, group=chosen, lag=lag, filters=kept)
    result = run_query(query, sources, today)
    xs, ys = result.series
    return [
        (a, b, p.start.isoformat())
        for p, a, b in zip(result.points, xs.values, ys.values, strict=True)
        if a is not None and b is not None
    ]


def pair(
    x: str,
    y: str,
    points: list[tuple[float, float, str]],
    min_n: int,
    lag: int = 0,
) -> Pair:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    n = len(points)
    pearson, spearman = _stat(xs, ys, "pearson"), _stat(xs, ys, "spearman")
    slope = intercept = None
    if n >= 3 and _spread(xs):
        mean_x, mean_y = sum(xs) / n, sum(ys) / n
        slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(xs, ys, strict=True)) / sum(
            (a - mean_x) ** 2 for a in xs
        )
        intercept = mean_y - slope * mean_x
        slope, intercept = round(slope, 6), round(intercept, 6)
    return Pair(x, y, lag, n, n < min_n, pearson, spearman, slope, intercept, points)


def _spread(values: Sequence[float]) -> bool:
    return len(set(values)) > 1


def _stat(xs: Sequence[float], ys: Sequence[float], method: Method) -> Stat:
    """r with its 95% CI and p; none under 4 points (no CI) or without spread."""
    n = len(xs)
    if n < 4 or not _spread(xs) or not _spread(ys):
        return Stat(None, None, None, None)
    if method == "pearson":
        found = stats.pearsonr(xs, ys)
        r, p = float(found.statistic), float(found.pvalue)
        se = 1 / math.sqrt(n - 3)
    else:
        found = stats.spearmanr(xs, ys)
        r, p = float(found.statistic), float(found.pvalue)
        se = math.sqrt((1 + r * r / 2) / (n - 3))  # Bonett & Wright (2000)
    if abs(r) >= 1:
        return Stat(round(r, 4), round(r, 4), round(r, 4), round(p, 6))
    z = math.atanh(r)
    low, high = math.tanh(z - Z95 * se), math.tanh(z + Z95 * se)
    return Stat(round(r, 4), round(low, 4), round(high, 4), round(p, 6))


@dataclass(frozen=True)
class Cell:
    r: float | None  # hidden (None) under the minimum n
    n: int


def matrix(
    metrics: Sequence[str],
    sources: Mapping[str, Source],
    today: dt.date,
    min_n: int,
    method: Method = "spearman",
    start: dt.date | None = None,
    end: dt.date | None = None,
    filters: Mapping[str, Sequence[str]] | None = None,
) -> list[list[Cell]]:
    """Every pair of metrics (pairwise: each over its own common points); the diagonal is 1."""
    if not 2 <= len(metrics) <= 12:
        raise QueryError("a matrix needs 2 to 12 metrics")
    cells = [[Cell(1.0, 0) for _ in metrics] for _ in metrics]
    for i, a in enumerate(metrics):
        for j in range(i + 1, len(metrics)):
            points = aligned(
                a, metrics[j], sources, today, group="day", start=start, end=end, filters=filters
            )
            found = _stat([p[0] for p in points], [p[1] for p in points], method)
            shown = found.r if len(points) >= min_n else None
            cells[i][j] = cells[j][i] = Cell(shown, len(points))
        cells[i][i] = Cell(
            1.0,
            len(aligned(a, a, sources, today, group="day", start=start, end=end, filters=filters)),
        )
    return cells


@dataclass(frozen=True)
class Predictor:
    metric: str
    n: int
    too_few: bool
    stat: Stat


def pre_session(module: Module, name: str, entity: str) -> list[Metric]:
    """The entity's metrics known before a session: stored fields asked before it (their own
    phase or their section's is `pre`), and derived values that read only those, the key and
    the date (e.g. days since the previous session, readiness)."""
    ent = module.entities[entity]
    sections = ent.sections or {}
    known = set(ent.key or []) | {ent.date_field}
    for f_name, f in ent.fields.items():
        if isinstance(f, BaseField):
            phase = (
                f.phase
                if f.phase != "any"
                else getattr(sections.get(f.section or ""), "phase", "any")
            )
            if phase == "pre":
                known.add(f_name)
    for step in derived_plan(module, entity).steps:
        reads = set()
        for part in ("expr", "value", "require"):
            checked = getattr(step, part, None)
            if checked is not None:
                reads |= set(checked.names)
        if reads and reads <= known:
            known.add(step.key)
    return [
        m
        for m in catalogue(name, module).metrics
        if m.entity == entity and m.field in known and m.field not in (ent.key or [])
    ]


def predictors(
    target: str,
    sources: Mapping[str, Source],
    today: dt.date,
    min_n: int,
    method: Method = "spearman",
    start: dt.date | None = None,
    end: dt.date | None = None,
    filters: Mapping[str, Sequence[str]] | None = None,
) -> list[Predictor]:
    """Each pre-session metric of the target's entity against it, ranked: the ones with enough
    points by |r| (largest first), then the others by n."""
    name, entity, _ = target.split(".", 2)
    if name not in sources:
        raise QueryError(f"unknown metric(s): {target}")
    module = sources[name][0]
    found = []
    for metric in pre_session(module, name, entity):
        if metric.id == target:
            continue
        points = aligned(metric.id, target, sources, today, start=start, end=end, filters=filters)
        stat = _stat([p[0] for p in points], [p[1] for p in points], method)
        found.append(Predictor(metric.id, len(points), len(points) < min_n, stat))
    return sorted(
        found,
        key=lambda p: (p.too_few or p.stat.r is None, -abs(p.stat.r or 0), -p.n),
    )
