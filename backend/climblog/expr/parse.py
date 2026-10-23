# SPDX-License-Identifier: GPL-3.0-or-later
"""Parse expression text into the tree of `nodes.py` (03-module-framework.md §2.2).

Python's own parser reads the text (the syntax is a subset of Python's), then an allow-list
turns each `ast` node into ours. Anything not on the list is an error; nothing is ever run.
Names and function names are not checked here: that is `check`'s job.
"""

import ast
import math

from climblog.expr.nodes import (
    Attr,
    Binary,
    BoolOp,
    Call,
    Compare,
    Cond,
    ExprError,
    ListNode,
    Literal,
    Name,
    Node,
    Unary,
)

_BINARY = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
_COMPARE = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}


def parse(source: str) -> Node:
    """Parse one expression. Raises `ExprError` with the position of the problem."""
    # The brackets let the text start with spaces or span lines; positions on the first line
    # are shifted back by one.
    try:
        tree = ast.parse(f"({source}\n)", mode="eval")
    except SyntaxError as error:
        line, column = error.lineno or 1, (error.offset or 1) - 1
        if line > source.count("\n") + 1:  # on the closing bracket: the text ended too soon
            at = len(source)
        else:
            at = _position(source, line, column - (line == 1), in_bytes=False)
        raise ExprError(f"invalid expression: {error.msg}", at) from None
    return _Converter(source).node(tree.body)


def _position(source: str, line: int, column: int, *, in_bytes: bool) -> int:
    """Character index in `source` of a 1-based line and 0-based column.

    `ast` columns count UTF-8 bytes; a string literal with accents shifts them.
    """
    lines = source.split("\n")
    line = min(max(line, 1), len(lines))
    text = lines[line - 1]
    if in_bytes:
        column = len(text.encode()[: max(column, 0)].decode(errors="ignore"))
    start = sum(len(previous) + 1 for previous in lines[: line - 1])
    return start + min(max(column, 0), len(text))


class _Converter:
    def __init__(self, source: str) -> None:
        self.source = source

    def at(self, node: ast.expr) -> int:
        column = node.col_offset - (node.lineno == 1)
        return _position(self.source, node.lineno, column, in_bytes=True)

    def node(self, node: ast.expr) -> Node:
        at = self.at(node)
        match node:
            case ast.Constant(value=bool() | int() | float() | str() as value):
                if isinstance(value, float) and not math.isfinite(value):  # 1e999
                    raise ExprError("not a finite number", at)
                return Literal(at, value)
            case ast.Constant(value=None):
                raise ExprError("there is no blank literal; use notnull(x)", at)
            case ast.Name(id=name):
                return Name(at, name)
            case ast.Attribute(value=obj, attr=name):
                return Attr(at, self.node(obj), name)
            case ast.UnaryOp(op=ast.USub(), operand=operand):
                return Unary(at, "-", self.node(operand))
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                return Unary(at, "not", self.node(operand))
            case ast.BinOp(op=op, left=left, right=right) if type(op) in _BINARY:
                return Binary(at, _BINARY[type(op)], self.node(left), self.node(right))  # type: ignore[arg-type]
            case ast.Compare(left=left, ops=[op], comparators=[right]) if type(op) in _COMPARE:
                return Compare(at, _COMPARE[type(op)], self.node(left), self.node(right))  # type: ignore[arg-type]
            case ast.Compare(ops=[_, _, *_]):
                raise ExprError("write `a < b and b < c` instead of `a < b < c`", at)
            case ast.BoolOp(op=op, values=values):
                items = tuple(self.node(v) for v in values)
                return BoolOp(at, "and" if isinstance(op, ast.And) else "or", items)
            case ast.IfExp(test=test, body=then, orelse=orelse):
                return Cond(at, self.node(test), self.node(then), self.node(orelse))
            case ast.Call(func=ast.Name(id=func), args=args, keywords=keywords):
                return self.call(at, func, args, keywords)
            case _:
                raise ExprError(f"{_describe(node)} is not allowed in an expression", at)

    def call(self, at: int, func: str, args: list[ast.expr], keywords: list[ast.keyword]) -> Call:
        for arg in args:
            if isinstance(arg, ast.Starred):
                raise ExprError("`*` is not allowed in an expression", self.at(arg))
        kwargs: list[tuple[str, Node]] = []
        for keyword in keywords:
            if keyword.arg is None:
                raise ExprError("`**` is not allowed in an expression", self.at(keyword.value))
            value = keyword.value
            if isinstance(value, ast.List):
                items = tuple(self.node(item) for item in value.elts)
                kwargs.append((keyword.arg, ListNode(self.at(value), items)))
            else:
                kwargs.append((keyword.arg, self.node(value)))
        return Call(at, func, tuple(self.node(arg) for arg in args), tuple(kwargs))


def _describe(node: ast.expr) -> str:
    """A short name for a construct that is not allowed."""
    match node:
        case ast.Constant():
            return f"the literal {node.value!r}"
        case ast.BinOp() | ast.UnaryOp():
            symbols = {
                ast.Pow: "**",
                ast.FloorDiv: "//",
                ast.Mod: "%",
                ast.UAdd: "unary +",
                ast.Invert: "~",
                ast.MatMult: "@",
                ast.LShift: "<<",
                ast.RShift: ">>",
                ast.BitAnd: "&",
                ast.BitOr: "|",
                ast.BitXor: "^",
            }
            return f"`{symbols.get(type(node.op), type(node.op).__name__)}`"
        case ast.Compare():
            return "`in` / `is`"
        case ast.Subscript():
            return "indexing (`x[...]`)"
        case ast.List() | ast.Tuple() | ast.Set() | ast.Dict():
            return "a list or tuple"
        case ast.Call():
            return "calling something other than a function name"
        case _:
            return type(node).__name__
