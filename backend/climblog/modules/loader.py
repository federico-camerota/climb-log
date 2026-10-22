# SPDX-License-Identifier: GPL-3.0-or-later
"""Load and validate module YAML files, reporting every problem with its line (D-041).

ruamel.yaml's round-trip loader follows YAML 1.2 (`No` stays a string, not `false`) and
records the line and column of every key, which the error messages point at.
"""

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from climblog.modules.checks import cross_check, expand_templates
from climblog.modules.schema import Module, Problem

# Friendlier wording for the most common pydantic errors.
_MESSAGES = {
    "extra_forbidden": "unknown key (typo?)",
    "missing": "required key is missing",
}


class ModuleError(Exception):
    """A module file that cannot be used, with all its problems."""

    def __init__(self, file: Path, problems: list[Problem]) -> None:
        self.file = file
        self.problems = problems
        super().__init__("\n".join(self.lines()))

    def lines(self) -> list[str]:
        return [_format(self.file, p) for p in self.problems]


def load_module(file: Path) -> Module:
    """Read, validate and expand one module file. Raises `ModuleError` listing every problem.

    Reference checks need a well-formed module, so they run only when there are no shape problems.
    """
    try:
        doc = YAML(typ="rt").load(file.read_text(encoding="utf-8"))
    except YAMLError as error:
        raise ModuleError(file, [_syntax_problem(error)]) from None
    if not isinstance(doc, CommentedMap):
        raise ModuleError(file, [Problem((), "a module file must be a mapping (key: value)", 1, 1)])

    try:
        module = Module.model_validate(_plain(doc))
    except ValidationError as error:
        problems = [_from_pydantic(doc, e) for e in error.errors()]
    else:
        problems = cross_check(module)
    if problems:
        raise ModuleError(file, [_locate(doc, p) for p in problems])
    return expand_templates(module)


def _plain(node: Any) -> Any:
    """ruamel's round-trip types (CommentedMap, ScalarFloat, …) → plain Python values."""
    if isinstance(node, dict):
        return {key: _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(item) for item in node]
    for kind in (bool, int, float, str):  # bool first: it is a subclass of int
        if isinstance(node, kind):
            return kind(node)
    return node


def _syntax_problem(error: YAMLError) -> Problem:
    mark = error.problem_mark if isinstance(error, MarkedYAMLError) else None
    message = (error.problem if isinstance(error, MarkedYAMLError) else None) or str(error)
    if mark is None:
        return Problem((), f"invalid YAML: {message}")
    return Problem((), f"invalid YAML: {message}", mark.line + 1, mark.column + 1)


def _from_pydantic(doc: CommentedMap, error: ErrorDetails) -> Problem:
    """Keep only the location parts that exist in the file.

    pydantic adds parts of its own (the union tag, `[key]` for an invalid dict key); a missing
    key is kept so the message names it.
    """
    loc = error["loc"]
    path: list[str | int] = []
    node: Any = doc
    for i, part in enumerate(loc):
        child = _child(node, part)
        if child is not _ABSENT:
            path.append(part)
            node = child
        elif error["type"] == "missing" and i == len(loc) - 1:
            path.append(part)
    message = _MESSAGES.get(error["type"], error["msg"].removeprefix("Value error, "))
    return Problem(tuple(path), message)


_ABSENT = object()


def _child(node: Any, part: str | int) -> Any:
    if isinstance(node, dict) and part in node:
        return node[part]
    if isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
        return node[part]
    return _ABSENT


def _locate(doc: CommentedMap, problem: Problem) -> Problem:
    """Add the line and column of the deepest part of the problem's path found in the file."""
    if problem.line is not None:
        return problem
    line, column = 0, 0
    node: Any = doc
    for part in problem.path:
        child = _child(node, part)
        if child is _ABSENT:
            break
        if isinstance(node, CommentedMap):
            line, column = node.lc.key(part)
        elif isinstance(node, CommentedSeq):
            line, column = node.lc.item(part)
        node = child
    return Problem(problem.path, problem.message, line + 1, column + 1)


def _format(file: Path, problem: Problem) -> str:
    where = f"{file}:{problem.line}:{problem.column}" if problem.line else str(file)
    path = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in problem.path).lstrip(".")
    return f"{where} {path}: {problem.message}" if path else f"{where} {problem.message}"
