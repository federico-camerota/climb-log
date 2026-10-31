# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived fields of an entity: load-time check, order and computation (03 §2.2, D-044).

`check_derived` checks every entry of an entity's `derived:` block against its fields, the
settings and the derived values it reads, in dependency order, and returns a `DerivedPlan`.
`compute` runs the plan on one record.

Entries that need what later issues add (the program, reference tables and the fields made
from them, plugins) are deferred: accepted, but neither checked nor computed, and so is every
entry that reads one of them. Values from other records come from a `Related`
(`modules/compute.py` computes whole tables).
"""

import ast
import dataclasses
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from climblog.expr import (
    ALONE,
    Checked,
    Env,
    ExprError,
    Kind,
    NameInfo,
    Related,
    Value,
    evaluate,
    parse,
    prepare,
)
from climblog.expr.nodes import Attr, Call, Levels, Name, Node
from climblog.modules.schema import (
    Band,
    BandsDerived,
    Case,
    Derived,
    ExprDerived,
    MapDerived,
    Module,
    Otherwise,
    PluginDerived,
    Problem,
    ReferenceGroupDerived,
    WhenDerived,
    YamlPath,
)

# Names that only M5 (program, reference tables) gives meaning to.
LATER_NAMES = frozenset({"program", "reference"})


@dataclass(frozen=True)
class Step:
    key: str
    kind: Kind  # the result type, for the sheet column's number format (#18)
    require: Checked | None


@dataclass(frozen=True)
class ExprStep(Step):
    expr: Checked


@dataclass(frozen=True)
class BandsStep(Step):
    value: Checked
    bands: tuple[tuple[float | Checked, str], ...]  # (upper limit, label), first match wins
    otherwise: str | None


@dataclass(frozen=True)
class WhenStep(Step):
    cases: tuple[tuple[Checked, str], ...]  # (condition, label), first match wins
    otherwise: str | None


@dataclass(frozen=True)
class MapStep(Step):
    source: Checked
    mapping: Mapping[str, str]


@dataclass(frozen=True)
class DerivedPlan:
    """The checked derived fields of an entity, in the order they are computed."""

    steps: tuple[Step, ...]
    deferred: tuple[str, ...]  # entries left for later issues, in YAML order
    names: Mapping[str, NameInfo]  # what each computed value is, for expressions reading it


def check_derived(
    module: Module,
    e_name: str,
    derived: Mapping[str, Derived],
    env: Env,
    *,
    defer_fields: bool,
    base: YamlPath | None = None,
) -> tuple[DerivedPlan, list[Problem]]:
    """Check the entries against `env` (the entity's stored fields and the settings).

    `defer_fields`: the entity has fields from a reference table (M5), so `fields(...)` cannot
    see all its fields yet. `base`: where the entries are in the YAML, for problems (default
    the entity's `derived`).
    """
    base = base or ("entities", e_name, "derived")
    problems: list[Problem] = []

    later: set[str] = set()
    broken: set[str] = set()
    depends: dict[str, list[str]] = {}
    for key, entry in derived.items():
        reads: set[str] = set()
        for at, source in _sources(entry, (*base, key)):
            if _uses_later(source, defer_fields):
                later.add(key)
                continue
            try:
                tree = parse(source)
            except ExprError as error:
                problems.append(Problem(at, str(error)))
                broken.add(key)
                continue
            if key in _prev_names(tree):
                problems.append(Problem(at, "prev() of the entry itself is not supported yet"))
                broken.add(key)
                continue  # not also a cycle
            reads.update(_names(tree))
        if isinstance(entry, PluginDerived | ReferenceGroupDerived):
            later.add(key)
        if key in env.names:
            problems.append(Problem((*base, key), f"'{key}' is already a field of the entity"))
            broken.add(key)
        depends[key] = sorted(n for n in reads if n in derived and n not in env.names)

    order, cycles = _order(depends)
    for key, cycle in cycles.items():
        problems.append(
            Problem((*base, key), f"derived fields depend on each other: {' → '.join(cycle)}")
        )
        broken.add(key)

    names = dict(env.names)
    scope = dataclasses.replace(env, names=names)  # grows as entries are checked
    steps: list[Step] = []
    deferred: set[str] = set()
    for key in order:
        needs = depends[key]
        if key in later or any(name in deferred for name in needs):
            deferred.add(key)
            continue
        if key in broken or any(name in broken for name in needs):
            broken.add(key)  # reported where it breaks; its readers would only repeat that
            continue
        try:
            step, info = _check_entry(module, key, derived[key], scope, (*base, key))
        except _EntryError as error:
            problems.append(error.problem)
            broken.add(key)
            continue
        steps.append(step)
        names[key] = info

    computed = {step.key: names[step.key] for step in steps}
    plan = DerivedPlan(tuple(steps), tuple(k for k in derived if k in deferred), computed)
    return plan, problems


def compute(
    plan: DerivedPlan,
    values: Mapping[str, Value],
    settings: Mapping[str, Value],
    related: Related = ALONE,
) -> dict[str, Value]:
    """The derived values of one record (deferred entries are left out).

    `values` holds the record's stored fields; a missing one counts as blank. `settings` must
    hold every setting the plan uses. `related` gives the other records (default: none).
    """
    scope = dict(values)
    result: dict[str, Value] = {}
    for step in plan.steps:
        if step.require is not None and _one(step.require, scope, settings, related) is not True:
            value = None
        else:
            value = _value(step, scope, settings, related)
        scope[step.key] = result[step.key] = value
    return result


# ---- Checking ----


class _EntryError(Exception):
    def __init__(self, at: YamlPath, message: str) -> None:
        self.problem = Problem(at, message)


def _prepare(source: str, scope: Env, at: YamlPath) -> Checked:
    try:
        return prepare(source, scope)
    except ExprError as error:
        raise _EntryError(at, str(error)) from None


def _single(source: str, scope: Env, at: YamlPath, wanted: str, what: str) -> Checked:
    """A checked expression giving one value of type `wanted` ("any" for every type)."""
    checked = _prepare(source, scope, at)
    if checked.kind.many:
        raise _EntryError(at, f"{what} must be one value, not a list of fields")
    if wanted != "any" and checked.kind.type != wanted:
        raise _EntryError(at, f"{what} must give {_TYPE_NAMES[wanted]}, not {checked.kind.type}")
    return checked


_TYPE_NAMES = {"bool": "yes/no", "number": "a number"}


def _check_entry(
    module: Module, key: str, entry: Derived, scope: Env, at: YamlPath
) -> tuple[Step, NameInfo]:
    require = None
    if isinstance(entry, ExprDerived | BandsDerived | WhenDerived) and entry.require is not None:
        require = _single(entry.require, scope, (*at, "require"), "bool", "`require`")

    if isinstance(entry, str | ExprDerived):
        source, expr_at = (entry, at) if isinstance(entry, str) else (entry.expr, (*at, "expr"))
        expr = _single(source, scope, expr_at, "any", "a derived field")
        kind = expr.kind
        info = NameInfo(
            kind.type,
            scale=kind.scale,
            choices=kind.levels,
            levels=kind.levels,
            lower_better=kind.lower_better,
        )
        return ExprStep(key, kind, require, expr), info

    if isinstance(entry, BandsDerived):
        value = _single(entry.bands_of, scope, (*at, "bands_of"), "number", "`bands_of`")
        bands: list[tuple[float | Checked, str]] = []
        for i, item in enumerate(entry.bands):
            if isinstance(item, Band):
                where = (*at, "bands", i, "le")
                limit = item.le
                if isinstance(limit, str):
                    bands.append((_single(limit, scope, where, "number", "`le`"), item.label))
                else:
                    bands.append((limit, item.label))
        kind, info = _labelled(module, entry, at)
        return BandsStep(key, kind, require, value, tuple(bands), entry.otherwise), info

    if isinstance(entry, WhenDerived):
        cases: list[tuple[Checked, str]] = []
        for i, case in enumerate(entry.when):
            if isinstance(case, Case):
                where = (*at, "when", i, "if")
                cases.append((_single(case.if_, scope, where, "bool", "`if`"), case.then))
        kind, info = _labelled(module, entry, at)
        return WhenStep(key, kind, require, tuple(cases), entry.otherwise), info

    assert isinstance(entry, MapDerived)  # the deferred kinds never get here
    origin = _single(entry.map_from, scope, (*at, "map_from"), "any", "`map_from`")
    choices = scope.names[entry.map_from].choices
    if choices is None:
        raise _EntryError(
            (*at, "map_from"), f"'{entry.map_from}' has no fixed values (a status or a choice)"
        )
    for given in entry.map:
        if given not in choices:
            raise _EntryError(
                (*at, "map", given),
                f"{given!r} is not a value of '{entry.map_from}' (values: {', '.join(choices)})",
            )
    texts = tuple(dict.fromkeys(entry.map.values()))
    return MapStep(key, Kind("text"), None, origin, entry.map), NameInfo("text", choices=texts)


def _labelled(
    module: Module, entry: BandsDerived | WhenDerived, at: YamlPath
) -> tuple[Kind, NameInfo]:
    """A status on its level list, or text with the labels as its values (`type: text`)."""
    if entry.type == "text":
        return Kind("text"), NameInfo("text", choices=tuple(entry.labels()))

    lists = {"status_levels": module.status_levels, **(module.model_extra or {})}
    name = entry.levels or "status_levels"
    found = lists.get(name)
    levels: Levels = tuple(found) if isinstance(found, list) else ()  # cross_check checks lists
    if not levels:
        if entry.levels is not None:
            known = ", ".join(k for k, v in lists.items() if v) or "none defined"
            raise _EntryError((*at, "levels"), f"unknown level list '{name}' (known: {known})")
        raise _EntryError(
            at,
            "a status needs the module's `status_levels` or a `levels:` list; "
            "for a message, write `type: text`",
        )
    items = entry.bands if isinstance(entry, BandsDerived) else entry.when
    part = "bands" if isinstance(entry, BandsDerived) else "when"
    for i, item in enumerate(items):
        label, where = _label(item)
        if label not in levels:
            raise _EntryError(
                (*at, part, i, where),
                f"label '{label}' is not in {name} ({', '.join(levels)})",
            )
    return Kind("text", levels=levels), NameInfo("text", choices=levels, levels=levels)


def _label(item: Band | Case | Otherwise) -> tuple[str, str]:
    """The label an item gives, and the key it is written under."""
    if isinstance(item, Band):
        return item.label, "label"
    if isinstance(item, Case):
        return item.then, "then"
    return item.else_, "else"


def _sources(entry: Derived, at: YamlPath) -> Iterator[tuple[YamlPath, str]]:
    """Every expression of an entry, with where it is written."""
    if isinstance(entry, str):
        yield at, entry
        return
    if isinstance(entry, ExprDerived | BandsDerived | WhenDerived) and entry.require is not None:
        yield (*at, "require"), entry.require
    if isinstance(entry, ExprDerived):
        yield (*at, "expr"), entry.expr
    elif isinstance(entry, BandsDerived):
        yield (*at, "bands_of"), entry.bands_of
        for i, item in enumerate(entry.bands):
            if isinstance(item, Band) and isinstance(item.le, str):
                yield (*at, "bands", i, "le"), item.le
    elif isinstance(entry, WhenDerived):
        for i, case in enumerate(entry.when):
            if isinstance(case, Case):
                yield (*at, "when", i, "if"), case.if_
    elif isinstance(entry, MapDerived):
        yield (*at, "map_from"), entry.map_from


def _uses_later(source: str, defer_fields: bool) -> bool:
    """Whether the text names something of a later issue. Python's own parser reads it, as it
    also accepts what ours rejects (`reference.exercises[exercise_id]`)."""
    try:
        tree = ast.parse(f"({source}\n)", mode="eval")
    except SyntaxError:
        return False  # `parse` reports it
    later = LATER_NAMES | {"fields"} if defer_fields else LATER_NAMES
    return any(isinstance(node, ast.Name) and node.id in later for node in ast.walk(tree))


def _names(node: object) -> Iterator[str]:
    """Every name of the record the tree reads, to order the entries.

    `fields(section=x)` selects by section, it reads no `x`; `children(...)`, `last(...)` and
    `parent.x` read other records. `prev(x)` counts: x must be checked first for its type.
    """
    if isinstance(node, Name):
        yield node.name
    elif _reads_no_names(node):
        return
    elif isinstance(node, tuple):
        for item in node:
            yield from _names(item)
    elif isinstance(node, Node):
        for part in dataclasses.fields(node):
            yield from _names(getattr(node, part.name))


def _reads_no_names(node: object) -> bool:
    if isinstance(node, Call):
        return node.func in ("fields", "children", "last")
    return isinstance(node, Attr) and isinstance(node.obj, Name) and node.obj.name == "parent"


def _prev_names(node: object) -> Iterator[str]:
    """The names read through `prev(...)`."""
    if isinstance(node, Call) and node.func == "prev" and node.args:
        yield from _names(node.args[0])
    elif isinstance(node, tuple):
        for item in node:
            yield from _prev_names(item)
    elif isinstance(node, Node):
        for part in dataclasses.fields(node):
            yield from _prev_names(getattr(node, part.name))


def _order(depends: Mapping[str, list[str]]) -> tuple[list[str], dict[str, list[str]]]:
    """Keys with what they read first, otherwise in YAML order; and the cycles found."""
    order: list[str] = []
    cycles: dict[str, list[str]] = {}
    state: dict[str, str] = {}  # "open" while its dependencies are visited, then "done"

    def visit(key: str, path: list[str]) -> None:
        if state.get(key) == "done":
            return
        if state.get(key) == "open":
            start = path.index(key)
            cycles.setdefault(path[start], [*path[start:], key])
            return
        state[key] = "open"
        for name in depends[key]:
            visit(name, [*path, key])
        state[key] = "done"
        order.append(key)

    for key in depends:
        visit(key, [])
    return order, cycles


# ---- Computation ----


def _one(
    expr: Checked, scope: Mapping[str, Value], settings: Mapping[str, Value], related: Related
) -> Value:
    value = evaluate(expr, scope, settings, related)
    assert not isinstance(value, list)  # checked: derived expressions give one value
    return value


def _value(
    step: Step, scope: Mapping[str, Value], settings: Mapping[str, Value], related: Related
) -> Value:
    match step:
        case ExprStep(expr=expr):
            return _one(expr, scope, settings, related)
        case BandsStep(value=value_expr, bands=bands, otherwise=otherwise):
            value = _one(value_expr, scope, settings, related)
            if not isinstance(value, int | float):
                return None  # a blank is not in the lowest band (D-044)
            for limit, label in bands:
                upper = (
                    limit
                    if isinstance(limit, int | float)
                    else _one(limit, scope, settings, related)
                )
                if isinstance(upper, int | float) and value <= upper:
                    return label
            return otherwise
        case WhenStep(cases=cases, otherwise=otherwise):
            for condition, label in cases:
                if _one(condition, scope, settings, related) is True:
                    return label
            return otherwise
        case MapStep(source=source, mapping=mapping):
            value = _one(source, scope, settings, related)
            return mapping.get(value) if isinstance(value, str) else None
    raise TypeError(f"unknown step {type(step).__name__}")  # pragma: no cover
