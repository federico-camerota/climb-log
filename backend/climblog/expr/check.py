# SPDX-License-Identifier: GPL-3.0-or-later
"""Check an expression against what a record has: names, settings, types (D-043).

`check` runs when a module loads. It reports unknown names with a suggestion, works out the
type of every part, resolves `settings.x` and `fields(...)`, and returns the names the
expression reads (derived fields are computed in that order, #10).
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
    Compare,
    Cond,
    ExprError,
    FieldRef,
    Fields,
    Kind,
    ListNode,
    Literal,
    Name,
    Node,
    Setting,
    Unary,
    ValueType,
)
from climblog.expr.parse import parse

_SELECTORS = ("section", "tag", "type")


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


@dataclass(frozen=True)
class Env:
    """The names an expression can use."""

    names: Mapping[str, NameInfo]
    settings: Mapping[str, ValueType] = field(default_factory=dict)
    date_field: str = "date"


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
            case Attr():
                raise ExprError("`x.y` is only valid as settings.<name>", node.at)
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
                resolved = replace(node, test=test_node, then=then_node, orelse=else_node)
                return resolved, Kind(then_kind.type, scale=scale)
            case Call(func="fields"):
                return self.fields(node)
            case Call():
                return self.call(node)
        raise ExprError(f"unexpected {type(node).__name__}", node.at)  # pragma: no cover

    def name(self, node: Node, name: str) -> Kind:
        info = self.env.names.get(name)
        if info is None:
            if name == "settings":
                raise ExprError("write settings.<name>", node.at)
            raise ExprError(
                f"unknown field '{name}'{_suggest(name, list(self.env.names))}", node.at
            )
        self.names.add(name)
        return Kind(info.type, scale=info.scale)

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
            if isinstance(named, Name) and isinstance(other, Literal):
                choices = self.env.names[named.name].choices
                if choices is not None and other.value not in choices:
                    raise ExprError(
                        f"{other.value!r} is not a choice of '{named.name}' "
                        f"(choices: {', '.join(choices)})",
                        other.at,
                    )
        return replace(node, left=lhs, right=rhs)

    def call(self, node: Call) -> tuple[Node, Kind]:
        function = FUNCTIONS.get(node.func)
        if function is None:
            known = [*FUNCTIONS, "fields"]
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
            resolved_call = replace(resolved_call, bounds=arg_kinds[0].scale)
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

        refs = tuple(FieldRef(name, meta.since, meta.retired) for name, meta in selected.items())
        self.names.update(selected)
        types = {self.env.names[name].type for name in selected}
        scales = {self.env.names[name].scale for name in selected}
        kind = Kind(
            types.pop() if len(types) == 1 else "any",
            many=True,
            scale=scales.pop() if len(scales) == 1 else None,
        )
        return Fields(node.at, refs, self.env.date_field), kind


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
