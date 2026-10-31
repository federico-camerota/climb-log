# SPDX-License-Identifier: GPL-3.0-or-later
"""Check an expression against what a record has: names, settings, types (D-043).

`check` runs when a module loads. It reports unknown names with a suggestion, works out the
type of every part, resolves `settings.x`, `fields(...)` and the cross-record forms (`prev`,
`parent.x`, `children(...)`, `last`, D-045), and returns the names the expression reads in the
same record (derived fields are computed in that order, #10).
"""

import datetime as dt
import difflib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from climblog.expr.functions import FUNCTIONS
from climblog.expr.nodes import (
    Attr,
    Binary,
    BoolOp,
    Bounds,
    Call,
    Children,
    Compare,
    Cond,
    ExprError,
    FieldRef,
    Fields,
    Kind,
    Last,
    Levels,
    ListNode,
    Literal,
    Name,
    Node,
    ParentRef,
    Prev,
    Setting,
    Unary,
    ValueType,
    Window,
)
from climblog.expr.parse import parse

_SELECTORS = ("section", "tag", "type")
_SPECIAL = ("fields", "prev", "children", "last", "window")  # forms checked here, not in FUNCTIONS


@dataclass(frozen=True)
class FieldMeta:
    """What `fields(...)` selects on, for a name that is a stored field."""

    type: str  # the field's `type:` in the YAML (scale, number, choice, …)
    section: str | None = None
    tags: tuple[str, ...] = ()
    since: dt.date | None = None
    retired: bool = False


@dataclass(frozen=True)
class NameInfo:
    type: ValueType
    scale: Bounds | None = None
    choices: tuple[str, ...] | None = None  # a closed choice list, checked in comparisons
    field: FieldMeta | None = None  # None for derived values
    levels: Levels | None = None  # a status (a derived `bands:` or `when:`), best first
    lower_better: bool | None = None  # on a lower-is-better scale (None: not on a scale)


@dataclass(frozen=True)
class Env:
    """The names an expression can use."""

    names: Mapping[str, NameInfo]
    settings: Mapping[str, ValueType] = field(default_factory=dict)
    date_field: str = "date"
    # Other records (D-045): the parent's stored fields (child entities only), each child
    # entity's stored fields and derived values, and every entity's stored fields (for last).
    parent: Mapping[str, NameInfo] | None = None
    children: Mapping[str, Mapping[str, NameInfo]] = field(default_factory=dict)
    entities: Mapping[str, Mapping[str, NameInfo]] = field(default_factory=dict)


@dataclass(frozen=True)
class Checked:
    """An expression ready to evaluate (or compile to a sheet formula)."""

    source: str
    tree: Node
    kind: Kind
    names: frozenset[str]  # fields and derived values it reads
    settings: frozenset[str]


def prepare(source: str, env: Env) -> Checked:
    """Parse and check. Raises `ExprError`."""
    return check(parse(source), env, source)


def check(tree: Node, env: Env, source: str = "") -> Checked:
    checker = _Checker(env)
    resolved, kind = checker.visit(tree)
    return Checked(source, resolved, kind, frozenset(checker.names), frozenset(checker.settings))


def _suggest(name: str, known: list[str]) -> str:
    close = difflib.get_close_matches(name, known, n=1)
    return f" (did you mean '{close[0]}'?)" if close else ""


class _Checker:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.names: set[str] = set()
        self.settings: set[str] = set()

    def single(self, node: Node, types: tuple[ValueType, ...], what: str) -> tuple[Node, Kind]:
        resolved, kind = self.visit(node)
        if kind.many:
            raise ExprError(f"{what} takes a single value, not a list of fields", node.at)
        if kind.type not in types:
            raise ExprError(f"{what} needs {' or '.join(types)}, not {kind.type}", node.at)
        return resolved, kind

    def visit(self, node: Node) -> tuple[Node, Kind]:
        match node:
            case Literal(value=value):
                if isinstance(value, bool):
                    return node, Kind("bool")
                return node, Kind("text" if isinstance(value, str) else "number")
            case Name(name=name):
                return node, self.name(node, name)
            case Attr(obj=Name(name="settings"), name=name):
                return Setting(node.at, name), self.setting(node, name)
            case Attr(obj=Name(name="parent"), name=name):
                return ParentRef(node.at, name), self.parent(node, name)
            case Attr(obj=Call(func="children") as call, name=name):
                return self.children(call, name)
            case Attr():
                raise ExprError(
                    "`x.y` is only valid as settings.<name>, parent.<name> or "
                    "children(<entity>).<name>",
                    node.at,
                )
            case ListNode():
                raise ExprError("a list is only valid in fields(section=[...])", node.at)
            case Unary(op="-", operand=operand):
                inner, _ = self.single(operand, ("number",), "`-`")
                return replace(node, operand=inner), Kind("number")
            case Unary(operand=operand):
                inner, _ = self.single(operand, ("bool",), "`not`")
                return replace(node, operand=inner), Kind("bool")
            case Binary(op=op, left=left, right=right):
                lhs, _ = self.single(left, ("number",), f"`{op}`")
                rhs, _ = self.single(right, ("number",), f"`{op}`")
                return replace(node, left=lhs, right=rhs), Kind("number")
            case Compare():
                return self.compare(node), Kind("bool")
            case BoolOp(op=op, values=values):
                items = tuple(self.single(v, ("bool",), f"`{op}`")[0] for v in values)
                return replace(node, values=items), Kind("bool")
            case Cond(test=test, then=then, orelse=orelse):
                test_node, _ = self.single(test, ("bool",), "the condition of `if`")
                then_node, then_kind = self.visit(then)
                else_node, else_kind = self.visit(orelse)
                if then_kind.many or else_kind.many or then_kind.type != else_kind.type:
                    raise ExprError(
                        "both sides of `x if c else y` must be single values of one type "
                        f"(got {then_kind.type} and {else_kind.type})",
                        node.at,
                    )
                scale = then_kind.scale if then_kind.scale == else_kind.scale else None
                levels = then_kind.levels if then_kind.levels == else_kind.levels else None
                lower = then_kind.lower_better
                lower = lower if lower == else_kind.lower_better else None
                resolved = replace(node, test=test_node, then=then_node, orelse=else_node)
                kind = Kind(then_kind.type, scale=scale, levels=levels, lower_better=lower)
                return resolved, kind
            case Call(func="fields"):
                return self.fields(node)
            case Call(func="prev"):
                return self.prev(node)
            case Call(func="children"):
                return self.children(node, None)
            case Call(func="last"):
                return self.last(node)
            case Call(func="window"):
                return self.window(node)
            case Call():
                return self.call(node)
        raise ExprError(f"unexpected {type(node).__name__}", node.at)  # pragma: no cover

    def name(self, node: Node, name: str) -> Kind:
        info = self.env.names.get(name)
        if info is None:
            if name in ("settings", "parent"):
                raise ExprError(f"write {name}.<name>", node.at)
            raise ExprError(
                f"unknown field '{name}'{_suggest(name, list(self.env.names))}", node.at
            )
        self.names.add(name)
        return _kind(info)

    def setting(self, node: Node, name: str) -> Kind:
        value_type = self.env.settings.get(name)
        if value_type is None:
            known = list(self.env.settings)
            hint = _suggest(name, known) or f" (known: {', '.join(known) or 'none defined'})"
            raise ExprError(f"unknown setting '{name}'{hint}", node.at)
        self.settings.add(name)
        return Kind(value_type)

    def compare(self, node: Compare) -> Compare:
        lhs, left = self.visit(node.left)
        rhs, right = self.visit(node.right)
        if left.many or right.many:
            raise ExprError("a comparison takes single values, not a list of fields", node.at)
        if left.type != right.type:
            raise ExprError(f"cannot compare {left.type} with {right.type}", node.at)
        if node.op not in ("==", "!=") and left.type not in ("number", "date", "time"):
            raise ExprError(
                f"`{node.op}` compares numbers, dates or times, not {left.type}", node.at
            )
        for named, other in ((lhs, rhs), (rhs, lhs)):
            if isinstance(named, Name | ParentRef) and isinstance(other, Literal):
                if isinstance(named, Name):
                    label, choices = named.name, self.env.names[named.name].choices
                else:
                    assert self.env.parent is not None
                    label, choices = f"parent.{named.name}", self.env.parent[named.name].choices
                if choices is not None and other.value not in choices:
                    raise ExprError(
                        f"{other.value!r} is not a choice of '{label}' "
                        f"(choices: {', '.join(choices)})",
                        other.at,
                    )
        return replace(node, left=lhs, right=rhs)

    def call(self, node: Call) -> tuple[Node, Kind]:
        function = FUNCTIONS.get(node.func)
        if function is None:
            known = [*FUNCTIONS, *_SPECIAL]
            raise ExprError(f"unknown function '{node.func}'{_suggest(node.func, known)}", node.at)
        args, arg_kinds = [], []
        for arg in node.args:
            resolved, kind = self.visit(arg)
            args.append(resolved)
            arg_kinds.append(kind)
        kwargs, kw_kinds = [], {}
        for key, value in node.kwargs:
            resolved, kind = self.visit(value)
            kwargs.append((key, resolved))
            kw_kinds[key] = kind
        resolved_call = replace(node, args=tuple(args), kwargs=tuple(kwargs))
        kind = function.check(resolved_call, arg_kinds, kw_kinds)
        if function.uses_scale:
            flips = _flips(args[0], arg_kinds[0])
            resolved_call = replace(resolved_call, bounds=arg_kinds[0].scale, flips=flips)
        if function.uses_levels:
            resolved_call = replace(resolved_call, levels=kind.levels)
        return resolved_call, kind

    def fields(self, node: Call) -> tuple[Node, Kind]:
        """`fields(section=…, tag=…, type=…)`: the record's stored fields matching every selector.

        A selector takes a name or a list of names (any of them matches). Each name must match
        some field on its own, so a typo in a list is not hidden by the other names.
        """
        if node.args:
            raise ExprError("fields() takes only section=, tag= or type=", node.args[0].at)
        if not node.kwargs:
            raise ExprError("fields() needs at least one of section=, tag=, type=", node.at)
        stored = {k: info.field for k, info in self.env.names.items() if info.field is not None}
        selected = dict(stored)
        for key, value in node.kwargs:
            if key not in _SELECTORS:
                raise ExprError(
                    f"fields() has no selector `{key}` (use section, tag, type)", value.at
                )
            wanted = set()
            for name, at in _selector_names(value):
                if not any(_matches(meta, key, name) for meta in stored.values()):
                    raise ExprError(f"no field has {key} '{name}'", at)
                wanted.add(name)
            selected = {
                k: meta
                for k, meta in selected.items()
                if any(_matches(meta, key, name) for name in wanted)
            }
        if not selected:
            raise ExprError("fields(...) matches no field", node.at)

        refs = tuple(
            FieldRef(name, meta.since, meta.retired, self.env.names[name].lower_better is True)
            for name, meta in selected.items()
        )
        self.names.update(selected)
        types = {self.env.names[name].type for name in selected}
        scales = {self.env.names[name].scale for name in selected}
        directions = {self.env.names[name].lower_better for name in selected}
        kind = Kind(
            types.pop() if len(types) == 1 else "any",
            many=True,
            scale=scales.pop() if len(scales) == 1 else None,
            lower_better=directions.pop() if len(directions) == 1 else None,
        )
        return Fields(node.at, refs, self.env.date_field), kind

    # ---- Other records (D-045) ----

    def prev(self, node: Call) -> tuple[Node, Kind]:
        """`prev(x)`, `prev(x, n)`: x in the n-th previous record of the same entity."""
        if node.kwargs:
            raise ExprError("prev() takes no options", node.kwargs[0][1].at)
        if not 1 <= len(node.args) <= 2:
            raise ExprError(f"prev() takes 1 to 2 values, got {len(node.args)}", node.at)
        target = node.args[0]
        if not isinstance(target, Name):
            raise ExprError("prev() takes a field or derived value, e.g. prev(date)", target.at)
        n = 1
        if len(node.args) == 2:
            count = node.args[1]
            if not (isinstance(count, Literal) and type(count.value) is int and count.value >= 1):
                raise ExprError("prev() counts back by a whole number, 1 or more", count.at)
            n = count.value
        return Prev(node.at, target.name, n), self.name(target, target.name)

    def parent(self, node: Node, name: str) -> Kind:
        if self.env.parent is None:
            raise ExprError(
                "parent.<name> is only valid in derived fields of a child entity", node.at
            )
        info = self.env.parent.get(name)
        if info is None:
            hint = _suggest(name, list(self.env.parent))
            raise ExprError(f"the parent has no field '{name}'{hint}", node.at)
        return _kind(info)

    def children(self, node: Call, name: str | None) -> tuple[Node, Kind]:
        """`children(e)`: one item per child row (for count); `children(e).x`: their x values."""
        if node.kwargs or len(node.args) != 1 or not isinstance(node.args[0], Name):
            raise ExprError("children() takes a child entity, e.g. children(set)", node.at)
        entity = node.args[0].name
        fields = self.env.children.get(entity)
        if fields is None:
            known = list(self.env.children)
            hint = _suggest(entity, known) or f" (child entities: {', '.join(known) or 'none'})"
            raise ExprError(f"'{entity}' is not a child entity of this one{hint}", node.args[0].at)
        if name is None:
            return Children(node.at, entity), Kind("any", many=True)
        info = fields.get(name)
        if info is None:
            raise ExprError(
                f"'{entity}' has no field '{name}'{_suggest(name, list(fields))}", node.at
            )
        kind = replace(_kind(info), many=True)
        return Children(node.at, entity, name), kind

    def last(self, node: Call) -> tuple[Node, Kind]:
        """`last(e.x, before=d)`: x in the latest record of entity e dated before d; with
        `until=d`, dated on or before d."""
        usage = (
            "last() takes an entity's field and a date, e.g. last(session.date, before=date) "
            "or last(session.date, until=date)"
        )
        entity, name, info = self.entity_field(node, usage)
        options = dict(node.kwargs)
        if set(options) not in ({"before"}, {"until"}):
            raise ExprError(usage, node.at)
        option = "until" if "until" in options else "before"
        day, _ = self.single(options[option], ("date",), f"`{option}`")
        return Last(node.at, entity, name, day, inclusive=option == "until"), _kind(info)

    def window(self, node: Call) -> tuple[Node, Kind]:
        """`window(e.x, days=n, until=d)`: x in every record of entity e dated from n days
        before d to d, for an aggregate (`count(window(...), equals='LOW')`)."""
        usage = (
            "window() takes an entity's field, a number of days and a date, e.g. "
            "window(session.overall_status, days=14, until=date)"
        )
        entity, name, info = self.entity_field(node, usage)
        options = dict(node.kwargs)
        if set(options) != {"days", "until"}:
            raise ExprError(usage, node.at)
        days = options["days"]
        if not (isinstance(days, Literal) and type(days.value) is int and days.value >= 0):
            raise ExprError("days must be a whole number of days, e.g. days=14", days.at)
        until, _ = self.single(options["until"], ("date",), "`until`")
        kind = replace(_kind(info), many=True)
        return Window(node.at, entity, name, days.value, until), kind

    def entity_field(self, node: Call, usage: str) -> tuple[str, str, NameInfo]:
        """The `e.x` that `last` and `window` take: an entity and one of its fields."""
        target = node.args[0] if len(node.args) == 1 else None
        if not (isinstance(target, Attr) and isinstance(target.obj, Name)):
            raise ExprError(usage, node.at)
        entity, name = target.obj.name, target.name
        fields = self.env.entities.get(entity)
        if fields is None:
            known = list(self.env.entities)
            raise ExprError(f"unknown entity '{entity}'{_suggest(entity, known)}", target.at)
        info = fields.get(name)
        if info is None:
            raise ExprError(
                f"'{entity}' has no field '{name}'{_suggest(name, list(fields))}", target.at
            )
        return entity, name, info


def _selector_names(value: Node) -> list[tuple[str, int]]:
    items = value.items if isinstance(value, ListNode) else (value,)
    names = []
    for item in items:
        match item:
            case Name(name=name) | Literal(value=str() as name):
                names.append((name, item.at))
            case _:
                raise ExprError("a fields() selector takes names, e.g. section=[a, b]", item.at)
    return names


def _matches(meta: FieldMeta, selector: str, name: str) -> bool:
    if selector == "section":
        return meta.section == name
    if selector == "tag":
        return name in meta.tags
    return meta.type == name


def _kind(info: NameInfo) -> Kind:
    return Kind(info.type, scale=info.scale, levels=info.levels, lower_better=info.lower_better)


def _flips(arg: Node, kind: Kind) -> tuple[bool, ...]:
    """Which values `flip`/`flip_all` turn around: those on a lower-is-better scale. A value on
    a higher-is-better (or neutral) scale already has the orientation flip gives (03 §2.2)."""
    if isinstance(arg, Fields):
        return tuple(ref.lower_better for ref in arg.refs)
    return (kind.lower_better is True,)
