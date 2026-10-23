# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate a checked expression on one record (D-043).

Blank cells are None. Arithmetic with a blank gives a blank, and so does division by zero.
`<`, `<=`, `>`, `>=` with a blank are false; `==` and `!=` treat blank as a value equal only
to blank. In `and`, `or`, `not` and conditions, only True counts as true (a blank Yes/No is no).
"""

import datetime as dt
import operator
from collections.abc import Callable, Mapping
from typing import Any

from climblog.expr.check import Checked
from climblog.expr.functions import FUNCTIONS, Arg
from climblog.expr.nodes import (
    Binary,
    BoolOp,
    Call,
    Compare,
    Cond,
    Fields,
    Literal,
    Name,
    Node,
    Setting,
    Unary,
    Value,
)

_ORDER: dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def evaluate(
    expr: Checked, values: Mapping[str, Value], settings: Mapping[str, Value]
) -> Value | list[Value]:
    """The expression's value for a record. A name missing from `values` counts as blank.

    `settings` must hold every setting the expression uses (`expr.settings`).
    """
    return _Evaluator(values, settings).eval(expr.tree)


class _Evaluator:
    def __init__(self, values: Mapping[str, Value], settings: Mapping[str, Value]) -> None:
        self.values = values
        self.settings = settings

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
            case Call():
                args = [self.eval(arg) for arg in node.args]
                kwargs = {key: self.one(value) for key, value in node.kwargs}
                return FUNCTIONS[node.func].run(args, kwargs, node)
        raise TypeError(f"cannot evaluate {type(node).__name__}")  # pragma: no cover

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

    def fields(self, node: Fields) -> list[Value]:
        """The values of the matched fields this record counts (`since`, `retired`)."""
        day = self.values.get(node.date_field)
        if isinstance(day, dt.datetime):
            day = day.date()
        values = []
        for ref in node.refs:
            if ref.since is not None and isinstance(day, dt.date) and day < ref.since:
                continue
            value = self.values.get(ref.name)
            if ref.retired and value is None:
                continue
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
