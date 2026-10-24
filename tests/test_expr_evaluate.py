# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluating expressions, with the legacy blank-cell rules (03-module-framework.md §2.2, D-043)."""

import datetime as dt

import pytest
from conftest import ENV

from climblog.expr import Value, evaluate, prepare

SETTINGS: dict[str, Value] = {"low_max": 4, "start": dt.date(2026, 10, 13)}
# A fictional record, logged after `elbows` started being tracked.
RECORD: dict[str, Value] = {
    "date": dt.date(2026, 10, 22),
    "session_type": "Max hangs",
    "mood": 7,
    "energy": 4,
    "fatigue": 8,
    "fun": None,
    "fingers": 3,
    "elbows": 6,
    "old_skin": None,
    "minutes": 90,
    "notes": "Più riposo tra le serie",
    "red_flag": None,
    "status": "WATCH",
    "pre_status": "WATCH",
    "post_status": "LOW",
    "reflect": None,
}


def run(source: str, **changes: Value) -> Value | list[Value]:
    return evaluate(prepare(source, ENV), RECORD | changes, SETTINGS)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # arithmetic and comparisons
        ("mood + energy * 2", 15),
        ("-mood", -7),
        ("mood / 2", 3.5),
        ("mood >= settings.low_max", True),
        ("mood < energy", False),
        ("session_type == 'Max hangs'", True),
        ("session_type != 'Max hangs'", False),
        ("days_between(settings.start, date)", 9),
        ("weekday(date)", "Thu"),
        # logic
        ("mood > 5 and energy > 5", False),
        ("mood > 5 or energy > 5", True),
        ("not mood > 5", False),
        ("'hangs' if session_type == 'Max hangs' else 'curls'", "hangs"),
        # functions
        ("mean(mood, energy)", 5.5),
        ("min(mood, energy, fatigue)", 4),
        ("max(mood, energy, fatigue)", 8),
        ("sum(mood, energy)", 11),
        ("count(mood, fun, notes)", 2),
        ("round(10 / 3, 2)", 3.33),
        ("round(mood)", 7.0),
        ("concat('W', 2, ' ', session_type)", "W2 Max hangs"),
        ("concat(minutes / 2, 'min')", "45min"),
        ("coalesce(fun, mood)", 7),
        ("notnull(mood)", True),
        ("all_present(mood, energy)", True),
        ("flip(fatigue)", 3),
        ("flip_all(fields(section=pre))", [4, 7]),
        ("min(mood, flip(fatigue))", 3),
        ("round(11 - mean(fields(tag=soreness)), 1)", 6.5),
        ("worst_of(pre_status, post_status)", "LOW"),
        ("worst_of(pre_status)", "WATCH"),
    ],
)
def test_values(source: str, expected: Value | list[Value]) -> None:
    assert run(source) == expected


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [(6.25, 1, 6.3), (6.35, 1, 6.4), (2.675, 2, 2.68), (-2.5, 0, -3.0), (0.5, 0, 1.0)],
)
def test_round_halves_away_from_zero_like_the_sheets(
    value: float, digits: int, expected: float
) -> None:
    assert run(f"round({value}, {digits})") == expected


# ---- Blank cells (D-043) ----


@pytest.mark.parametrize(
    "source",
    [
        "fun + 1",
        "11 - fun",
        "-fun",
        "round(fun, 1)",
        "flip(fun)",
        "days_between(date, settings.start)",
        "weekday(date)",
        "mean(fun)",
        "min(fun)",
        "sum(fun)",
        "coalesce(fun)",
        "mood / 0",
    ],
)
def test_blank_in_blank_out(source: str) -> None:
    assert run(source, date=None) is None


@pytest.mark.parametrize("source", ["fun < 5", "fun <= 5", "fun > 5", "fun >= 5", "5 > fun"])
def test_ordering_with_a_blank_is_false(source: str) -> None:
    assert run(source) is False
    assert run(f"not ({source})") is True


def test_equality_treats_blank_as_a_value() -> None:
    assert run("session_type == 'Max hangs'", session_type=None) is False
    assert run("session_type != 'Max hangs'", session_type=None) is True
    assert run("fun == mood", mood=None) is True


def test_a_blank_yes_no_counts_as_no() -> None:
    assert run("red_flag") is None  # the value itself stays blank
    assert run("red_flag or mood > 5") is True
    assert run("red_flag and mood > 5") is False
    assert run("not red_flag") is True
    assert run("1 if red_flag else 2") == 2


def test_aggregates_ignore_blanks() -> None:
    assert run("mean(mood, fun, energy)") == 5.5
    assert run("min(fun, energy)") == 4
    assert run("count(fun)") == 0
    assert run("all_present(mood, fun)") is False
    assert run("concat('a', fun, 'b')") == "ab"


def test_missing_as_fills_blanks_but_all_blank_stays_blank() -> None:
    assert run("min(mood, fun, missing_as=10)") == 7
    assert run("mean(mood, fun, missing_as=10)") == 8.5
    assert run("min(fun, missing_as=10)") is None
    pre = "min(flip_all(fields(section=pre)), missing_as=1)"
    assert run(pre, mood=None) == 1
    assert run(pre, mood=None, energy=None) is None


def test_fields_leaves_out_fields_not_yet_tracked() -> None:
    soreness = "fields(tag=soreness)"
    assert run(soreness) == [3, 6]  # old_skin is retired and blank: left out
    assert run(soreness, date=dt.date(2026, 10, 1), elbows=None) == [3]  # before `since`
    assert run(f"all_present({soreness})", date=dt.date(2026, 10, 1), elbows=None) is True
    assert run(f"all_present({soreness})", elbows=None) is False


def test_retired_fields_count_where_they_have_a_value() -> None:
    assert run("fields(tag=soreness)", old_skin=5) == [3, 6, 5]
    assert run("mean(fields(tag=soreness))", old_skin=6) == 5


def test_dates_and_datetimes_compare() -> None:
    later = dt.datetime(2026, 10, 22, 18, 30)
    assert run("date > settings.start", date=later) is True
    assert run("settings.start < date", date=later) is True
    assert run("days_between(settings.start, date)", date=later) == 9
    assert run("fields(tag=soreness)", date=dt.datetime(2026, 10, 1, 9), elbows=None) == [3]


def test_missing_names_count_as_blank() -> None:
    checked = prepare("notnull(mood)", ENV)
    assert evaluate(checked, {}, SETTINGS) is False


def test_worst_of_ignores_blank_statuses() -> None:
    """D-044: a section not filled in does not hide the others; all blank stays blank."""
    assert run("worst_of(pre_status, post_status)", post_status=None) == "WATCH"
    assert run("worst_of(pre_status, post_status)", pre_status=None, post_status=None) is None
