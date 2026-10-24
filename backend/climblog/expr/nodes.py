# SPDX-License-Identifier: GPL-3.0-or-later
"""The expression tree, value types and errors (03-module-framework.md §2.2, D-043).

`parse` builds the tree from the text; `check` resolves names and returns a tree where
`settings.x` is a `Setting` and `fields(...)` is a `Fields` node with the matched fields.
Every node keeps `at`, its position in the expression text, for error messages.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal as Choice

Value = int | float | str | bool | dt.date | dt.time | None
"""A cell value as the evaluator sees it (dt.datetime is a dt.date). None is a blank cell."""

ValueType = Choice["number", "text", "bool", "date", "time", "any"]
"""What an expression gives. `any` appears only as the item type of a mixed `fields(...)`."""

Bounds = tuple[float, float]
"""(min, max) of a numeric scale, used by `flip`."""


class ExprError(Exception):
    """A problem in an expression, at a 0-based character position in its text."""

    def __init__(self, message: str, at: int = 0) -> None:
        self.message = message
        self.at = at
        super().__init__(f"{message} (at character {at + 1})")


@dataclass(frozen=True)
class Kind:
    """The type of an expression, found by `check`."""

    type: ValueType
    many: bool = False  # a list of values: the result of fields(...) or flip_all(...)
    scale: Bounds | None = None  # the scale the value lies on, if any (for flip)


@dataclass(frozen=True)
class Node:
    at: int


@dataclass(frozen=True)
class Literal(Node):
    value: int | float | str | bool


@dataclass(frozen=True)
class Name(Node):
    """A field or derived value of the same record."""

    name: str


@dataclass(frozen=True)
class Attr(Node):
    """`obj.name`. Only `settings.name` is valid for now; `check` turns it into a `Setting`."""

    obj: Node
    name: str


@dataclass(frozen=True)
class ListNode(Node):
    """`[a, b]`: only as a selector value in `fields(section=[a, b])`."""

    items: tuple[Node, ...]


@dataclass(frozen=True)
class Unary(Node):
    op: Choice["-", "not"]
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: Choice["+", "-", "*", "/"]
    left: Node
    right: Node


@dataclass(frozen=True)
class Compare(Node):
    op: Choice["==", "!=", "<", "<=", ">", ">="]
    left: Node
    right: Node


@dataclass(frozen=True)
class BoolOp(Node):
    op: Choice["and", "or"]
    values: tuple[Node, ...]


@dataclass(frozen=True)
class Cond(Node):
    """`then if test else orelse`."""

    test: Node
    then: Node
    orelse: Node


@dataclass(frozen=True)
class Call(Node):
    func: str
    args: tuple[Node, ...]
    kwargs: tuple[tuple[str, Node], ...] = ()
    bounds: Bounds | None = None  # set by `check` for functions that use the scale (flip)


# ---- Nodes made by `check` ----


@dataclass(frozen=True)
class Setting(Node):
    name: str


@dataclass(frozen=True)
class FieldRef:
    """A field matched by `fields(...)`, with what decides whether a record counts it."""

    name: str
    since: dt.date | None = None  # records dated before this leave the field out
    retired: bool = False  # counted only in records that have a value for it


@dataclass(frozen=True)
class Fields(Node):
    refs: tuple[FieldRef, ...]
    date_field: str
