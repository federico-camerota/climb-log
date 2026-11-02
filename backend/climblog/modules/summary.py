# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet's Summary tab (`summary:`, D-085): values of a day and the latest records side by
side, written by schema sync with formulas compiled from the YAML (`summary_cells`), so the sheet
on the phone shows what the app shows (the legacy Summary - Recent, 00-current-state §1).

Its values are derived entries of the day, as the recommendation's (`date` is the day, TODAY() in
the sheet; the recommendation's values can be read by name); `summarize` computes them in the
app, for the parity tests and the drift check.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from climblog.expr import Value
from climblog.modules.compute import Timeline
from climblog.modules.derived import DerivedPlan, check_derived, compute
from climblog.modules.schema import (
    BaseField,
    Module,
    Problem,
    SummaryRow,
    SummarySessions,
    TemplateUse,
    YamlPath,
)

# What a row can show besides the values: the recommendation's headline and text.
ADVICE = ("headline", "text")
RESERVED_TABS = ("_settings", "_meta")


@dataclass(frozen=True)
class SummaryPlan:
    tab: str
    title: str
    values: DerivedPlan  # the summary's own values, in order
    rows: tuple[SummaryRow, ...]
    side_by_side: SummarySessions | None


def summary_problems(module: Module) -> list[Problem]:
    """What is wrong with the module's `summary:` (checked at load)."""
    return _summary(module)[1]


def summary_plan(module: Module) -> SummaryPlan | None:
    """The summary of a loaded module, if it has one."""
    plan, problems = _summary(module)
    assert not problems, problems  # `load_module` reported them
    return plan


def _summary(module: Module) -> tuple[SummaryPlan | None, list[Problem]]:
    from climblog.modules.checks import _recommendation, recommendation_env  # they import us

    found = module.summary
    if found is None:
        return None, []
    base: YamlPath = ("summary",)
    problems: list[Problem] = []
    tabs = {tab.casefold() for e in module.entities.values() for tab in e.tab_fields()}
    if found.tab.casefold() in tabs or found.tab in RESERVED_TABS:
        problems.append(Problem((*base, "tab"), f"'{found.tab}' is already a tab of the module"))
    advice, _ = _recommendation(module)
    env = recommendation_env(module)
    if advice is not None:
        env = replace(env, names={**env.names, **advice.values.names})
    values, found_problems = check_derived(
        module, "", found.values, env, defer_fields=False, base=(*base, "values")
    )
    problems += found_problems
    known = (
        set(values.names)
        | set(advice.values.names if advice else ())
        | set(ADVICE if advice else ())
    )
    for i, row in enumerate(found.rows):
        for name in row.names():
            if name not in known:
                hint = "" if advice else " (the module has no recommendation:)"
                problems.append(Problem((*base, "rows", i, "value"), f"no value '{name}'{hint}"))
    sessions = found.side_by_side
    if sessions is not None:
        at: YamlPath = (*base, "side_by_side")
        if sessions.entity not in module.entities:
            entities = ", ".join(module.entities)
            problems.append(Problem((*at, "entity"), f"no entity '{sessions.entity}' ({entities})"))
        else:
            names = _names(module, sessions.entity)
            for j, group in enumerate(sessions.groups):
                for k, name in enumerate(group.fields):
                    if name not in names:
                        problems.append(
                            Problem(
                                (*at, "groups", j, "fields", k),
                                f"'{sessions.entity}' has no field or derived value '{name}'",
                            )
                        )
    plan = SummaryPlan(found.tab, found.title, values, tuple(found.rows), sessions)
    return plan, problems


def _names(module: Module, entity: str) -> set[str]:
    """Fields and derived values, templates expanded (the checks see the module as written)."""
    found = module.entities[entity]
    names = set(found.derived)
    for name, field in found.fields.items():
        if isinstance(field, TemplateUse):
            names |= {name + key for key in module.templates.get(field.template, {})}
        else:
            names.add(name)
    return names


# ---- In the app ----


@dataclass(frozen=True)
class Summarized:
    values: dict[str, Value]  # every value by name: the recommendation's, its headline and
    # text, the summary's
    sessions: list[dict[str, Value]]  # the latest records, newest first, `last` of them


def summarize(
    module: Module,
    tables: Mapping[str, Sequence[Mapping[str, Value]]],
    settings: Mapping[str, Value],
    day: dt.date,
) -> Summarized:
    """The summary for `day`. `tables[entity]` holds each record's stored and derived values."""
    from climblog.modules.checks import recommendation_plan
    from climblog.modules.recommend import recommend, records_of

    plan = summary_plan(module)
    assert plan is not None
    values: dict[str, Value] = {}
    advice_plan = recommendation_plan(module)
    if advice_plan is not None:
        advice = recommend(module, advice_plan, tables, settings, day)
        values |= dict(advice.values) | {"headline": advice.headline, "text": advice.text}
    related = records_of(module, tables)
    values |= compute(plan.values, {"date": day, **values}, settings, related)
    sessions: list[dict[str, Value]] = []
    if plan.side_by_side is not None:
        found = plan.side_by_side
        entity = module.entities[found.entity]
        timeline = Timeline(entity, list(tables.get(found.entity, ())))
        names = [entity.date_field, *(f for g in found.groups for f in g.fields)]
        for n in range(1, found.last + 1):
            sessions.append({f: timeline.last(f, day, True, n) for f in names})
    return Summarized(values, sessions)


def row_label(module: Module, entity: str, name: str, labels: Mapping[str, str]) -> str:
    """A side-by-side row's label: the given one, the form's, or the derived name."""
    from climblog.modules.forms import field_label

    if name in labels:
        return labels[name]
    field = module.entities[entity].fields.get(name)
    if isinstance(field, BaseField):
        return field_label(name, field)
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]
