# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate a checked expression on one record (D-043).

Blank cells are None. Arithmetic with a blank gives a blank, and so does division by zero.
`<`, `<=`, `>`, `>=` with a blank are false; `==` and `!=` treat blank as a value equal only
to blank. In `and`, `or`, `not` and conditions, only True counts as true (a blank Yes/No is no).

Values from other records (`prev`, `parent.x`, `children(...)`, `last`) come from a `Related`
given by the caller (the table computation, `modules/compute.py`); without one, the record is
on its own: no previous record, no parent, no children (D-045).
"""

import datetime as dt
import operator
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from climblog.expr.check import Checked
from climblog.expr.functions import FUNCTIONS, Arg
from climblog.expr.nodes import (
    Binary,
    BoolOp,
    Call,
    Children,
    Compare,
    Cond,
    Fields,
    Last,
    Literal,
    Name,
    Node,
    ParentRef,
    Prev,
    Setting,
    Unary,
    Value,
    Window,
)

_ORDER: dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


class Related(Protocol):
    """The other records an expression can read (03 §2.1b, §2.3)."""

    def prev(self, name: str, n: int) -> Value:
        """`name` in the n-th previous record of the same entity; blank if there is none."""
        ...

    def parent(self, name: str) -> Value:
        """`name` in the parent record; blank if there is none."""
        ...

    def children(self, entity: str) -> Sequence[Mapping[str, Value]]:
        """The rows of a child entity that belong to this record (stored and derived values)."""
        ...

    def last(self, entity: str, name: str, day: dt.date, inclusive: bool = False) -> Value:
        """`name` in the latest record of `entity` dated before `day` (or on it, `inclusive`);
        blank if none."""
        ...

    def window(self, entity: str, name: str, start: dt.date, end: dt.date) -> list[Value]:
        """`name` in every record of `entity` dated from `start` to `end`, in date order."""
        ...


class _Alone:
    """A record on its own: no previous record, no parent, no children."""

    def prev(self, name: str, n: int) -> Value:
        return None

    def parent(self, name: str) -> Value:
        return None

    def children(self, entity: str) -> Sequence[Mapping[str, Value]]:
        return ()

    def last(self, entity: str, name: str, day: dt.date, inclusive: bool = False) -> Value:
        return None

    def window(self, entity: str, name: str, start: dt.date, end: dt.date) -> list[Value]:
        return []


ALONE: Related = _Alone()


def evaluate(
    expr: Checked,
    values: Mapping[str, Value],
    settings: Mapping[str, Value],
    related: Related = ALONE,
) -> Value | list[Value]:
    """The expression's value for a record. A name missing from `values` counts as blank.

    `settings` must hold every setting the expression uses (`expr.settings`).
    """
    return _Evaluator(values, settings, related).eval(expr.tree)


class _Evaluator:
    def __init__(
        self, values: Mapping[str, Value], settings: Mapping[str, Value], related: Related
    ) -> None:
        self.values = values
        self.settings = settings
        self.related = related

    def one(self, node: Node) -> Value:
        """A single value (`check` guarantees the node is not a list)."""
        value = self.eval(node)
        assert not isinstance(value, list)
        return value

    def eval(self, node: Node) -> Arg:
        match node:
            case Literal(value=literal):
                return literal
            case Name(name=name):
                return self.values.get(name)
            case Setting(name=name):
                return self.settings[name]
            case Unary(op="-", operand=operand):
                value = self.one(operand)
                return -value if isinstance(value, int | float) else None
            case Unary(operand=operand):
                return self.one(operand) is not True
            case Binary():
                return self.binary(node)
            case Compare():
                return self.compare(node)
            case BoolOp(op="and", values=values):
                return all(self.one(v) is True for v in values)
            case BoolOp(values=values):
                return any(self.one(v) is True for v in values)
            case Cond(test=test, then=then, orelse=orelse):
                return self.eval(then if self.one(test) is True else orelse)
            case Fields():
                return self.fields(node)
            case Prev(name=name, n=n):
                return self.related.prev(name, n)
            case ParentRef(name=name):
                return self.related.parent(name)
            case Children(entity=entity, field=None):
                return [True for _ in self.related.children(entity)]  # one item per row
            case Children(entity=entity, field=str() as name):
                return [row.get(name) for row in self.related.children(entity)]
            case Last(entity=entity, field=name, before=before, inclusive=inclusive):
                day = self.day(before)
                return None if day is None else self.related.last(entity, name, day, inclusive)
            case Window(entity=entity, field=name, days=days, until=until):
                end = self.day(until)
                if end is None:
                    return []
                return self.related.window(entity, name, end - dt.timedelta(days=days), end)
            case Call(func="flip_all", args=(Fields() as fields,)):
                return self.fields(fields, flip=node)
            case Call():
                args = [self.eval(arg) for arg in node.args]
                kwargs = {key: self.one(value) for key, value in node.kwargs}
                return FUNCTIONS[node.func].run(args, kwargs, node)
        raise TypeError(f"cannot evaluate {type(node).__name__}")  # pragma: no cover

    def day(self, node: Node) -> dt.date | None:
        value = self.one(node)
        if isinstance(value, dt.datetime):
            return value.date()
        return value if isinstance(value, dt.date) else None

    def binary(self, node: Binary) -> Value:
        left, right = self.one(node.left), self.one(node.right)
        if not isinstance(left, int | float) or not isinstance(right, int | float):
            return None
        match node.op:
            case "+":
                return left + right
            case "-":
                return left - right
            case "*":
                return left * right
        return None if right == 0 else left / right

    def compare(self, node: Compare) -> bool:
        left, right = _comparable(self.one(node.left), self.one(node.right))
        if node.op == "==":
            return left == right
        if node.op == "!=":
            return left != right
        if left is None or right is None:
            return False
        return _ORDER[node.op](left, right)

    def fields(self, node: Fields, flip: Call | None = None) -> list[Value]:
        """The values of the matched fields this record counts (`since`, `retired`); with
        `flip`, those on a lower-is-better scale turned around (`flip_all`)."""
        day = self.values.get(node.date_field)
        if isinstance(day, dt.datetime):
            day = day.date()
        values = []
        for i, ref in enumerate(node.refs):
            if ref.since is not None and isinstance(day, dt.date) and day < ref.since:
                continue
            value = self.values.get(ref.name)
            if ref.retired and value is None:
                continue
            if flip is not None and flip.flips[i] and flip.bounds is not None:
                low, high = flip.bounds
                value = low + high - value if isinstance(value, int | float) else None
            values.append(value)
        return values


def _comparable(left: Value, right: Value) -> tuple[Value, Value]:
    """A date and a datetime compare as datetimes (a date is its midnight)."""
    if isinstance(left, dt.datetime) and _plain_date(right):
        right = dt.datetime.combine(right, dt.time())  # type: ignore[arg-type]
    elif isinstance(right, dt.datetime) and _plain_date(left):
        left = dt.datetime.combine(left, dt.time())  # type: ignore[arg-type]
    return left, right


def _plain_date(value: Value) -> bool:
    return isinstance(value, dt.date) and not isinstance(value, dt.datetime)
