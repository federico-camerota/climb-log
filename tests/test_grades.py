# SPDX-License-Identifier: GPL-3.0-or-later
"""French and gym grades with a numeric index (D-017, D-047)."""

import pytest
from conftest import Problems

from climblog.grades import Grade, GradeError, parse_grade

BOTH = ["french", "gym"]


@pytest.mark.parametrize(
    ("text", "systems", "expected"),
    [
        # French: one step per letter or +
        ("4a", BOTH, Grade("french", 18, "4a")),
        ("6a", BOTH, Grade("french", 30, "6a")),
        ("6a+", BOTH, Grade("french", 31, "6a+")),
        ("6B", BOTH, Grade("french", 32, "6b")),
        (" 6C+ ", BOTH, Grade("french", 35, "6c+")),
        ("7a", ["french"], Grade("french", 36, "7a")),
        ("9c+", BOTH, Grade("french", 53, "9c+")),
        # gym: plain numbers
        ("5", BOTH, Grade("gym", 5, "5")),
        ("6,5", ["gym"], Grade("gym", 6.5, "6,5")),
        ("12.25", BOTH, Grade("gym", 12.25, "12.25")),
        # slash grades: halfway
        ("6a/6a+", BOTH, Grade("french", 30.5, "6a/6a+")),
        ("6b+ / 6C", BOTH, Grade("french", 33.5, "6b+/6c")),
        ("6a/6b", ["french"], Grade("french", 31, "6a/6b")),
        ("5/6", BOTH, Grade("gym", 5.5, "5/6")),
    ],
)
def test_grades(text: str, systems: list[str], expected: Grade) -> None:
    assert parse_grade(text, systems) == expected


@pytest.mark.parametrize(
    ("text", "systems", "message"),
    [
        ("5+", BOTH, "'5+' is not a French grade (e.g. 6b+) or a gym grade (a number)"),
        ("6", ["french"], "'6' is not a French grade (e.g. 6b+)"),  # bare French: an issue
        ("6a", ["gym"], "'6a' is not a gym grade (a number)"),
        ("10a", BOTH, "'10a' is not"),
        ("6d", BOTH, "'6d' is not"),
        ("0", BOTH, "'0' is not"),
        ("-3", BOTH, "'-3' is not"),
        ("V5", BOTH, "'V5' is not"),
        ("", BOTH, "'' is not"),
        ("6a/6a+/6b", BOTH, "'6a/6a+/6b' is not"),
        ("6a/hard", BOTH, "'6a/hard' is not a French grade (e.g. 6b+) or a gym grade (a "
         "number), or two close ones like 6a/6a+"),
        ("6a/6", BOTH, "'6a/6' mixes a French and a gym grade"),
        ("6a+/6a", BOTH, "'6a+/6a' has the harder grade first"),
        ("6a/6a", BOTH, "'6a/6a' has the harder grade first"),
        ("6a/7a", BOTH, "'6a/7a' has its two grades too far apart"),
        ("5/7", BOTH, "'5/7' has its two grades too far apart"),
    ],
)  # fmt: skip
def test_bad_grades(text: str, systems: list[str], message: str) -> None:
    with pytest.raises(GradeError) as error:
        parse_grade(text, systems)
    assert error.value.message.startswith(message), error.value.message


def test_indexes_order_grades_within_a_system() -> None:
    grades = ["4c", "5a", "5c+", "6a", "6a/6a+", "6a+", "6b", "6c+", "7a"]
    indexes = [parse_grade(text, ["french"]).index for text in grades]
    assert indexes == sorted(indexes)
    assert len(set(indexes)) == len(indexes)


def test_unsupported_systems_fail_to_load(problems: Problems) -> None:
    text = """\
module: test_grades
name: Test grades
version: 1
kind: journal
entities:
  session:
    label: Session
    tab: Sessions
    fields:
      date: {type: date}
      grade: {type: grade, systems: [french, uiaa, gym]}
"""
    assert problems(text) == [
        "11:46 entities.session.fields.grade.systems[1]: grade system 'uiaa' is not supported "
        "yet (supported: french, gym)"
    ]
