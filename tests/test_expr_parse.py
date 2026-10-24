# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsing expressions: the allowed syntax, positions in errors, and the draft modules (D-043)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from climblog.expr import ExprError, parse
from climblog.expr.nodes import (
    Attr,
    Binary,
    BoolOp,
    Call,
    Compare,
    Cond,
    ListNode,
    Literal,
    Name,
    Unary,
)

DRAFTS = Path(__file__).parent.parent / "design" / "modules"


def test_precedence_and_positions() -> None:
    assert parse("a + b * 2") == Binary(
        0, "+", Name(0, "a"), Binary(4, "*", Name(4, "b"), Literal(8, 2))
    )


def test_constructs() -> None:
    assert parse("-x") == Unary(0, "-", Name(1, "x"))
    assert parse("not done") == Unary(0, "not", Name(4, "done"))
    assert parse("a >= 3") == Compare(0, ">=", Name(0, "a"), Literal(5, 3))
    assert parse("a and b or c") == BoolOp(
        0, "or", (BoolOp(0, "and", (Name(0, "a"), Name(6, "b"))), Name(11, "c"))
    )
    assert parse("1 if t else 2.5") == Cond(0, Name(5, "t"), Literal(0, 1), Literal(12, 2.5))
    assert parse("settings.low_max") == Attr(0, Name(0, "settings"), "low_max")
    assert parse("True") == Literal(0, True)
    assert parse("'Max hangs'") == Literal(0, "Max hangs")


def test_calls_with_options_and_selector_lists() -> None:
    assert parse("min(a, missing_as=10)") == Call(
        0, "min", (Name(4, "a"),), (("missing_as", Literal(18, 10)),)
    )
    assert parse("fields(section=[a, b])") == Call(
        0, "fields", (), (("section", ListNode(15, (Name(16, "a"), Name(19, "b")))),)
    )


def test_surrounding_spaces_and_line_breaks_are_fine() -> None:
    assert parse("  a +\n  b") == Binary(2, "+", Name(2, "a"), Name(8, "b"))


def test_positions_count_characters_not_bytes() -> None:
    # "è" is two bytes in UTF-8; the position of `x` must still be its character index.
    assert parse("'è' == x") == Compare(0, "==", Literal(0, "è"), Name(7, "x"))
    with pytest.raises(ExprError) as error:
        parse("'più' == x[0]")
    assert error.value.at == 9


@pytest.mark.parametrize(
    ("source", "message", "at"),
    [
        ("mean(a,", "invalid expression: '(' was never closed", 0),
        ("a +", "invalid expression: invalid syntax", 3),
        ("a = 1", "invalid expression", 0),
        ("a < b < c", "write `a < b and b < c` instead of `a < b < c`", 0),
        ("2 ** 3", "`**` is not allowed", 0),
        ("a % 2", "`%` is not allowed", 0),
        ("x in y", "`in` / `is` is not allowed", 0),
        ("x[0]", "indexing (`x[...]`) is not allowed", 0),
        ("[1, 2]", "a list or tuple is not allowed", 0),
        ("a, b", "a list or tuple is not allowed", 0),
        ("None", "there is no blank literal; use notnull(x)", 0),
        ("1e999", "not a finite number", 0),
        ("b'x'", "the literal b'x' is not allowed", 0),
        ("f'{a}'", "JoinedStr is not allowed", 0),
        ("lambda: 1", "Lambda is not allowed", 0),
        ("__import__('os')", "", -1),  # parses as an ordinary call; `check` rejects the name
        ("a.b()", "calling something other than a function name is not allowed", 0),
        ("mean(*xs)", "`*` is not allowed", 5),
        ("mean(**xs)", "`**` is not allowed", 7),
    ],
)
def test_syntax_errors(source: str, message: str, at: int) -> None:
    if at < 0:
        parse(source)
        return
    with pytest.raises(ExprError) as error:
        parse(source)
    assert error.value.message.startswith(message), error.value.message
    assert error.value.at == at


# Draft expressions that use syntax of later milestones (reference tables, M5).
_LATER = {"reference.exercises[exercise_id].prescription[program.week]"}
_EXPRESSION_KEYS = {"if", "bands_of", "require", "expr", "le", "lt", "ge", "gt", "visible_if"}


def _expressions(node: Any) -> Iterator[str]:
    """Expression strings in a module file: `derived` values and conditions in them."""
    if isinstance(node, dict):
        for k, value in node.items():
            if k == "derived":
                for d_value in value.values():
                    if isinstance(d_value, str):
                        yield d_value
                    else:
                        yield from _expressions(d_value)
            elif k in _EXPRESSION_KEYS and isinstance(value, str):
                yield value
            else:
                yield from _expressions(value)
    elif isinstance(node, list):
        for item in node:
            yield from _expressions(item)


@pytest.mark.parametrize("file", sorted(DRAFTS.glob("*.yaml")), ids=lambda f: f.name)
def test_draft_expressions_parse(file: Path) -> None:
    """Every expression in the drafts is valid syntax (names are checked per issue, #10, #11)."""
    found = [e for e in _expressions(YAML(typ="safe").load(file)) if e not in _LATER]
    assert found
    for source in found:
        parse(source)
