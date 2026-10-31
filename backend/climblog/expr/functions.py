# SPDX-License-Identifier: GPL-3.0-or-later
"""The functions expressions can call: argument checks and evaluation (D-043).

Each `Function` has a `check`, run at load on the argument types, and a `run`, called per
record on the argument values. Blanks follow the legacy sheets: aggregates ignore them and
give a blank when every value is blank; other functions give a blank for a blank input.
`fields(...)` is not here: its arguments are selectors, not expressions (see `check.py`).
"""

import datetime as dt
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal

from climblog.expr.nodes import Bounds, Call, ExprError, Fields, Kind, Literal, Value, ValueType

Arg = Value | list[Value]
CheckFn = Callable[[Call, Sequence[Kind], Mapping[str, Kind]], Kind]
RunFn = Callable[[Sequence[Arg], Mapping[str, Value], Call], Value | list[Value]]

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class Function:
    check: CheckFn
    run: RunFn
    uses_scale: bool = False  # `check` stores the argument's scale bounds on the call node
    uses_levels: bool = False  # `check` stores the result's status levels on the call node


# ---- Checks ----


def _expect(
    call: Call, i: int, kind: Kind, types: tuple[ValueType, ...], *, many: bool = False
) -> None:
    """Argument `i` must be one of `types`; a list (from fields(...)) only if `many`."""
    at = call.args[i].at if i < len(call.args) else call.at
    if kind.many and not many:
        raise ExprError(f"{call.func}() takes a single value here, not a list of fields", at)
    if kind.type not in types:
        expected = " or ".join(types)
        raise ExprError(f"{call.func}() needs {expected} values, not {kind.type}", at)


def _arity(call: Call, low: int, high: int | None = None) -> None:
    n = len(call.args)
    if n < low or (high is not None and n > high):
        if high is None:
            wanted = f"at least {low} value{'s' * (low > 1)}"
        elif low == high:
            wanted = f"{low} value{'s' * (low > 1)}"
        else:
            wanted = f"{low} to {high} values"
        raise ExprError(f"{call.func}() takes {wanted}, got {n}", call.at)


def _keywords(call: Call, allowed: frozenset[str] = frozenset()) -> None:
    for name, node in call.kwargs:
        if name not in allowed:
            hint = f" (only {', '.join(sorted(allowed))})" if allowed else ""
            raise ExprError(f"{call.func}() has no option `{name}`{hint}", node.at)


def _common_scale(kinds: Sequence[Kind]) -> Bounds | None:
    """The scale shared by all the values, if they share one."""
    scales = {kind.scale for kind in kinds}
    return scales.pop() if len(scales) == 1 else None


def _common_direction(kinds: Sequence[Kind]) -> bool | None:
    """Whether all the values are on a lower-is-better scale (None: mixed or unknown)."""
    directions = {kind.lower_better for kind in kinds}
    return directions.pop() if len(directions) == 1 else None


def _check_aggregate(keeps_scale: bool) -> CheckFn:
    def check(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
        _arity(call, 1)
        _keywords(call, frozenset({"missing_as"}))
        for i, kind in enumerate(args):
            _expect(call, i, kind, ("number",), many=True)
        fill = kwargs.get("missing_as")
        if fill is not None and (fill.many or fill.type != "number"):
            at = dict(call.kwargs)["missing_as"].at
            raise ExprError("missing_as must be a single number", at)
        if not keeps_scale:
            return Kind("number")
        return Kind("number", scale=_common_scale(args), lower_better=_common_direction(args))

    return check


def _check_count(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1)
    _keywords(call, frozenset({"equals"}))
    equals = kwargs.get("equals")
    if equals is not None and equals.many:
        raise ExprError("equals must be a single value", dict(call.kwargs)["equals"].at)
    return Kind("number")


def _check_all_present(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1)
    _keywords(call)
    return Kind("bool")


def _check_notnull(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1, 1)
    _keywords(call)
    _expect(call, 0, args[0], ("number", "text", "bool", "date", "time"))
    return Kind("bool")


def _check_coalesce(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1)
    _keywords(call)
    for i, kind in enumerate(args):
        _expect(call, i, kind, (args[0].type,))
    return Kind(args[0].type, scale=_common_scale(args), lower_better=_common_direction(args))


def _check_concat(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1)
    _keywords(call)
    for i, kind in enumerate(args):
        _expect(call, i, kind, ("text", "number"))
    return Kind("text")


def _check_round(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1, 2)
    _keywords(call)
    _expect(call, 0, args[0], ("number",))
    if len(call.args) == 2:
        digits = call.args[1]
        if not (isinstance(digits, Literal) and type(digits.value) is int and digits.value >= 0):
            raise ExprError("round() takes the number of decimals as a whole number", digits.at)
    return Kind("number", scale=args[0].scale, lower_better=args[0].lower_better)


def _check_flip(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1, 1)
    _keywords(call)
    _expect(call, 0, args[0], ("number",))
    if args[0].scale is None:
        raise ExprError(
            "flip() needs a value on a scale: a scale field, or min/max/mean of fields "
            "on the same scale",
            call.args[0].at,
        )
    if args[0].lower_better is None:
        raise ExprError(
            "flip() needs values on scales of one direction (all lower-is-better or not)",
            call.args[0].at,
        )
    return replace(args[0], lower_better=False)  # now higher is better


def _check_flip_all(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1, 1)
    _keywords(call)
    _expect(call, 0, args[0], ("number",), many=True)
    if not isinstance(call.args[0], Fields) or args[0].scale is None:
        raise ExprError(
            "flip_all() needs fields(...) on one scale; use flip() for a single value",
            call.args[0].at,
        )
    return replace(args[0], lower_better=False)  # each value now higher-is-better


def _check_worst_of(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1)
    _keywords(call)
    for i, kind in enumerate(args):
        _expect(call, i, kind, ("text",))
        if kind.levels is None:
            raise ExprError("worst_of() needs statuses (bands: or when: results)", call.args[i].at)
    if len({kind.levels for kind in args}) > 1:
        lists = " and ".join(
            f"[{', '.join(levels)}]" for levels in dict.fromkeys(k.levels for k in args) if levels
        )
        raise ExprError(f"worst_of() needs statuses on one level list, not {lists}", call.at)
    return Kind("text", levels=args[0].levels)


def _check_days_between(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 2, 2)
    _keywords(call)
    for i, kind in enumerate(args):
        _expect(call, i, kind, ("date",))
    return Kind("number")


def _check_weekday(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1, 1)
    _keywords(call)
    _expect(call, 0, args[0], ("date",))
    return Kind("text")


def _check_month(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    _arity(call, 1, 1)
    _keywords(call)
    _expect(call, 0, args[0], ("date",))
    return Kind("text")


def _check_incomplete(call: Call, args: Sequence[Kind], kwargs: Mapping[str, Kind]) -> Kind:
    """`incomplete(Wellbeing=cond, Physical=cond, ...)`: each option a yes/no, named as shown."""
    if call.args:
        raise ExprError("incomplete() takes only named yes/no values: Name=condition", call.at)
    if not call.kwargs:
        raise ExprError("incomplete() needs at least one Name=condition", call.at)
    for name, node in call.kwargs:
        kind = kwargs[name]
        if kind.many or kind.type != "bool":
            raise ExprError(f"incomplete(): {name}= must be a yes/no, not {kind.type}", node.at)
    return Kind("text")


# ---- Evaluation ----


def _flat(args: Sequence[Arg]) -> Iterator[Value]:
    for arg in args:
        if isinstance(arg, list):
            yield from arg
        else:
            yield arg


def _numbers(args: Sequence[Arg], kwargs: Mapping[str, Value]) -> list[float] | None:
    """The values an aggregate works on: blanks left out, or filled with `missing_as`.

    None when every value is blank, even with `missing_as` (D-043).
    """
    values = list(_flat(args))
    if all(value is None for value in values):
        return None
    fill = kwargs.get("missing_as")
    if fill is not None:
        values = [fill if value is None else value for value in values]
    return [value for value in values if isinstance(value, int | float)]


def _run_mean(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    numbers = _numbers(args, kwargs)
    return None if numbers is None else sum(numbers) / len(numbers)


def _run_min(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    numbers = _numbers(args, kwargs)
    return None if numbers is None else min(numbers)


def _run_max(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    numbers = _numbers(args, kwargs)
    return None if numbers is None else max(numbers)


def _run_sum(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    numbers = _numbers(args, kwargs)
    return None if numbers is None else sum(numbers)


def _run_count(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    """The values present, or with `equals=` those equal to it (a blank `equals`: none)."""
    if "equals" in kwargs:
        wanted = kwargs["equals"]
        return sum(1 for value in _flat(args) if value is not None and value == wanted)
    return sum(1 for value in _flat(args) if value is not None)


def _run_all_present(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    return all(value is not None for value in _flat(args))


def _run_notnull(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    return args[0] is not None


def _run_coalesce(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    return next((value for value in _flat(args) if value is not None), None)


def _text(value: Value) -> str:
    """How `concat` writes a value: like the sheets do (7.0 → "7", blank → "")."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _run_concat(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    return "".join(_text(value) for value in _flat(args))


def _run_round(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    """Halves round away from zero, like ROUND in the sheets (Python's round() goes to even)."""
    value, digits = args[0], args[1] if len(args) > 1 else 0
    if not isinstance(value, int | float) or not isinstance(digits, int):
        return None
    # The sheets round the value as shown with 15 significant digits: 2.675 → 2.68, and a mean
    # of 5.824999999999999 (5.825 on paper) → 5.83. str() alone would keep the 9s (D-053).
    exact = Decimal(f"{value:.15g}").quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(exact)


def _flip(value: Value, bounds: Bounds | None) -> Value:
    if not isinstance(value, int | float) or bounds is None:
        return None
    return bounds[0] + bounds[1] - value


def _run_flip(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    """The value turned to higher-is-better: flipped if its scale is lower-is-better."""
    value = args[0]
    if isinstance(value, list):  # pragma: no cover - `check` allows a single value only
        return None
    if call.flips and not call.flips[0]:
        return value if isinstance(value, int | float) else None
    return _flip(value, call.bounds)


def _run_flip_all(
    args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call
) -> Value | list[Value]:
    """Each value turned to higher-is-better. The evaluator gives the values with their flags,
    since `fields(...)` leaves some out per record (`since`, `retired`)."""
    return list(_flat(args))  # pragma: no cover - `evaluate` handles flip_all(fields(...))


def _run_worst_of(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    """The worst status given (last in the level list); blanks are left out (D-044)."""
    assert call.levels is not None
    ranks = [call.levels.index(value) for value in _flat(args) if value in call.levels]
    return call.levels[max(ranks)] if ranks else None


def _day(value: Arg) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else None


def _run_days_between(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    start, end = _day(args[0]), _day(args[1])
    return None if start is None or end is None else (end - start).days


def _run_month(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    """The date's month as `2026-10`."""
    day = _day(args[0])
    return None if day is None else f"{day.year:04d}-{day.month:02d}"


def _run_incomplete(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    """The names whose condition doesn't hold, `Physical, Reflect`; blank when all hold."""
    missing = [name for name, value in kwargs.items() if value is not True]
    return ", ".join(missing) or None


def _run_weekday(args: Sequence[Arg], kwargs: Mapping[str, Value], call: Call) -> Value:
    day = _day(args[0])
    return None if day is None else _WEEKDAYS[day.weekday()]


FUNCTIONS: dict[str, Function] = {
    "mean": Function(_check_aggregate(keeps_scale=True), _run_mean),
    "min": Function(_check_aggregate(keeps_scale=True), _run_min),
    "max": Function(_check_aggregate(keeps_scale=True), _run_max),
    "sum": Function(_check_aggregate(keeps_scale=False), _run_sum),
    "count": Function(_check_count, _run_count),
    "round": Function(_check_round, _run_round),
    "concat": Function(_check_concat, _run_concat),
    "coalesce": Function(_check_coalesce, _run_coalesce),
    "notnull": Function(_check_notnull, _run_notnull),
    "all_present": Function(_check_all_present, _run_all_present),
    "flip": Function(_check_flip, _run_flip, uses_scale=True),
    "flip_all": Function(_check_flip_all, _run_flip_all, uses_scale=True),
    "days_between": Function(_check_days_between, _run_days_between),
    "weekday": Function(_check_weekday, _run_weekday),
    "month": Function(_check_month, _run_month),
    "incomplete": Function(_check_incomplete, _run_incomplete),
    "worst_of": Function(_check_worst_of, _run_worst_of, uses_levels=True),
}
"""Functions by name. #11 adds `prev`, `children`, … here."""
