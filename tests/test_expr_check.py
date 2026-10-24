# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking expressions at load: names, settings, types, fields(...) and flip (D-043)."""

import datetime as dt

import pytest
from conftest import ENV, LEVELS, S5, S10

from climblog.expr import ExprError, Kind, prepare
from climblog.expr.nodes import Call, FieldRef, Fields, Setting


def kind(source: str) -> Kind:
    return prepare(source, ENV).kind


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("mood + 1", Kind("number")),
        ("mood", Kind("number", scale=S10)),
        ("mean(mood, energy)", Kind("number", scale=S10)),
        ("round(mean(mood, energy), 1)", Kind("number", scale=S10)),
        ("sum(mood, energy)", Kind("number")),
        ("mean(mood, fun)", Kind("number")),  # different scales: none
        ("11 - mean(mood)", Kind("number")),
        ("mood >= settings.low_max", Kind("bool")),
        ("red_flag and not notnull(notes)", Kind("bool")),
        ("concat('W', minutes, ' ', session_type)", Kind("text")),
        ("coalesce(mood, energy)", Kind("number", scale=S10)),
        ("days_between(settings.start, date)", Kind("number")),
        ("weekday(date)", Kind("text")),
        ("count(fields(section=post))", Kind("number")),
        ("fields(section=post)", Kind("any", many=True)),
        ("fields(tag=soreness)", Kind("number", many=True, scale=S10)),
        ("flip_all(fields(section=pre))", Kind("number", many=True, scale=S10)),
        ("flip(max(fields(tag=soreness)))", Kind("number", scale=S10)),
        ("mood if red_flag else energy", Kind("number", scale=S10)),
        ("mood if red_flag else minutes", Kind("number")),
        ("status == 'LOW'", Kind("bool")),
        ("red_flag == True", Kind("bool")),
        ("pre_status", Kind("text", levels=LEVELS)),
        ("worst_of(pre_status, post_status)", Kind("text", levels=LEVELS)),
        ("pre_status if red_flag else post_status", Kind("text", levels=LEVELS)),
        ("pre_status if red_flag else 'LOW'", Kind("text")),
    ],
)
def test_kinds(source: str, expected: Kind) -> None:
    assert kind(source) == expected


def test_names_and_settings_read_are_collected() -> None:
    checked = prepare("mean(fields(tag=soreness)) <= settings.low_max and status == 'LOW'", ENV)
    assert checked.names == {"fingers", "elbows", "old_skin", "status"}
    assert checked.settings == {"low_max"}


def test_settings_and_fields_are_resolved() -> None:
    tree = prepare("settings.low_max", ENV).tree
    assert tree == Setting(0, "low_max")
    call = prepare("max(fields(tag=soreness))", ENV).tree
    assert isinstance(call, Call)
    assert call.args == (
        Fields(
            4,
            (
                FieldRef("fingers"),
                FieldRef("elbows", since=dt.date(2026, 10, 20)),
                FieldRef("old_skin", retired=True),
            ),
            "date",
        ),
    )


def test_flip_stores_the_scale_bounds() -> None:
    call = prepare("flip(fun)", ENV).tree
    assert isinstance(call, Call)
    assert call.bounds == S5


def test_fields_combines_selectors() -> None:
    call = prepare("count(fields(section=[pre, post], type=scale))", ENV).tree
    assert isinstance(call, Call) and isinstance(call.args[0], Fields)
    assert [r.name for r in call.args[0].refs] == ["mood", "energy", "fatigue", "fun"]


@pytest.mark.parametrize(
    ("source", "message", "at"),
    [
        # names
        ("mod + 1", "unknown field 'mod' (did you mean 'mood'?)", 0),
        ("xyz", "unknown field 'xyz'", 0),
        ("settings", "write settings.<name>", 0),
        ("settings.low", "unknown setting 'low' (did you mean 'low_max'?)", 0),
        ("settings.zzz", "unknown setting 'zzz' (known: low_max, start)", 0),
        ("program.week", "`x.y` is only valid as settings.<name>", 0),
        ("meen(mood)", "unknown function 'meen' (did you mean 'mean'?)", 0),
        ("__import__('os')", "unknown function '__import__'", 0),
        ("session_type == 'Max hang'", "'Max hang' is not a choice of 'session_type'", 16),
        ("'Curls' != session_type", "'Curls' is not a choice of 'session_type'", 0),
        # types
        ("notes + 1", "`+` needs number, not text", 0),
        ("-notes", "`-` needs number, not text", 1),
        ("mood and red_flag", "`and` needs bool, not number", 0),
        ("not mood", "`not` needs bool, not number", 4),
        ("mood == 'x'", "cannot compare number with text", 0),
        ("notes < 'b'", "`<` compares numbers, dates or times, not text", 0),
        ("1 if mood else 2", "the condition of `if` needs bool, not number", 5),
        ("mood if red_flag else notes", "both sides of `x if c else y` must be single", 0),
        ("fields(tag=soreness) > 3", "a comparison takes single values", 0),
        ("mood + fields(tag=soreness)", "`+` takes a single value, not a list", 7),
        ("min(mood, missing_as=[1])", "a list is only valid in fields(section=[...])", 21),
        # functions
        ("mean()", "mean() takes at least 1 value, got 0", 0),
        ("mean(notes)", "mean() needs number values, not text", 5),
        ("mean(fields(section=post))", "mean() needs number values, not any", 5),
        ("min(mood, missing_as='x')", "missing_as must be a single number", 21),
        ("max(mood, default=1)", "max() has no option `default` (only missing_as)", 18),
        ("count(mood, missing_as=1)", "count() has no option `missing_as`", 23),
        ("round(mood, 1, 2)", "round() takes 1 to 2 values, got 3", 0),
        ("round(mood, energy)", "round() takes the number of decimals as a whole number", 12),
        ("round(mood, 1.5)", "round() takes the number of decimals", 12),
        ("notnull(fields(tag=soreness))", "notnull() takes a single value here", 8),
        ("coalesce(mood, notes)", "coalesce() needs number values, not text", 15),
        ("concat(date)", "concat() needs text or number values, not date", 7),
        ("flip(minutes)", "flip() needs a value on a scale", 5),
        ("flip(mean(mood, fun))", "flip() needs a value on a scale", 5),
        ("flip(11 - mood)", "flip() needs a value on a scale", 5),
        ("flip_all(mood)", "flip_all() needs fields(...) on one scale", 9),
        ("flip_all(fields(type=scale))", "flip_all() needs fields(...) on one scale", 9),
        ("days_between(date)", "days_between() takes 2 values, got 1", 0),
        ("weekday(minutes)", "weekday() needs date values, not number", 8),
        ("worst_of(status, pre_status)", "worst_of() needs statuses (bands: or when: results)", 9),
        (
            "worst_of(pre_status, reflect)",
            "worst_of() needs statuses on one level list, not [GOOD, WATCH, LOW] and [GOOD, WORTH",
            0,
        ),
        ("worst_of(mood)", "worst_of() needs text values, not number", 9),
        ("pre_status == 'LOWW'", "'LOWW' is not a choice of 'pre_status'", 14),
        # fields()
        ("fields()", "fields() needs at least one of section=, tag=, type=", 0),
        ("fields(pre)", "fields() takes only section=, tag= or type=", 7),
        ("fields(group=pre)", "fields() has no selector `group`", 13),
        ("fields(section=[pre, psot])", "no field has section 'psot'", 21),
        ("fields(tag=sore)", "no field has tag 'sore'", 11),
        ("fields(section=pre, tag=soreness)", "fields(...) matches no field", 0),
        ("fields(section=[mean(mood)])", "a fields() selector takes names", 16),
        ("fields(section=status)", "no field has section 'status'", 15),
    ],
)
def test_errors(source: str, message: str, at: int) -> None:
    with pytest.raises(ExprError) as error:
        prepare(source, ENV)
    assert error.value.message.startswith(message), error.value.message
    assert error.value.at == at
    assert str(error.value).endswith(f"(at character {at + 1})")
