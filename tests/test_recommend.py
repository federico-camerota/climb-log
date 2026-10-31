# SPDX-License-Identifier: GPL-3.0-or-later
"""The next-session recommendation (D-071, D-076): the journal's rule, branch by branch, on
fictional rows, and the problems of a `recommendation:` block."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml, Problems

from climblog.expr import Value
from climblog.modules import load_module
from climblog.modules.checks import recommendation_plan
from climblog.modules.recommend import Advice, recommend

JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
DAY = dt.date(2026, 10, 30)


def day(n: int) -> dt.date:
    return DAY - dt.timedelta(days=n)


def advice(*sessions: tuple[dt.date, Value] | tuple[dt.date, Value, int]) -> Advice:
    """The recommendation for DAY from sessions (date, overall status[, session_no])."""
    rows = [
        {"date": s[0], "session_no": s[2] if len(s) > 2 else 1, "overall_status": s[1]}
        for s in sessions
    ]
    plan = recommendation_plan(JOURNAL)
    assert plan is not None
    return recommend(JOURNAL, plan, {"session": rows}, {}, DAY)


def test_no_session_yet() -> None:
    found = advice()
    assert (found.headline, found.message) == (None, "Log a session to get guidance")
    assert found.text == "Log a session to get guidance"


@pytest.mark.parametrize(
    ("sessions", "headline"),
    [
        ([(day(2), "LOW")], "RECOVER"),
        ([(day(9), "LOW"), (day(5), "LOW"), (day(1), "GOOD")], "RECOVER"),  # 2 LOW in 14 days
        ([(day(14), "LOW"), (day(5), "LOW"), (day(1), "GOOD")], "RECOVER"),  # the 14th counts
        ([(day(15), "LOW"), (day(5), "LOW"), (day(1), "GOOD")], "GREEN LIGHT"),  # the 15th not
        ([(day(1), "WATCH")], "MODERATE"),
        ([(day(1), "GOOD")], "GREEN LIGHT"),
        ([(day(0), "LOW", 1), (day(0), "GOOD", 2)], "GREEN LIGHT"),  # the day's 2nd session
        ([(day(1), "GOOD"), (day(-1), "LOW")], "GREEN LIGHT"),  # after the day: not yet
        ([(day(3), "LOW"), (day(2), "LOW"), (day(1), None)], "RECOVER"),  # 2 LOW, latest blank
    ],
)
def test_the_journal_rule(sessions: list[tuple[dt.date, Value]], headline: str) -> None:
    assert advice(*sessions).headline == headline


def test_a_latest_session_without_a_status() -> None:
    found = advice((day(1), None))
    assert found.headline is None
    assert found.message == "Fill in the remaining tabs for your latest session to get guidance"


def test_the_reasons_and_the_text_as_the_legacy_sheet() -> None:
    found = advice((day(9), "LOW"), (day(5), "LOW"), (day(1), "GOOD"))
    assert [(r.label, r.value) for r in found.reasons] == [
        ("Last session", day(1)),
        ("Latest overall status", "GOOD"),
        ("LOW sessions in the last 14 days", 2),
    ]
    assert found.text == (
        "RECOVER — rest day or easy technical climbing. No limit attempts or max hangs until "
        "your recovery scores come back up."
    )


MODULE = """\
module: test_recommend
name: Test recommend
version: 1
kind: journal
entities:
  session:
    label: Session
    tab: Sessions
    key: [date]
    fields:
      date: {type: date, required: true}
      effort: {type: number}
    derived:
      hard: "effort >= 8"
recommendation:
BLOCK
"""
VALID = """\
  values:
    hard_days: "count(window(session.hard, days=7, until=date), equals=True)"
    last_effort: "last(session.effort, until=date)"
  rules:
    - {if: "hard_days >= 3", headline: REST, message: Three hard days.}
    - {message: Go on.}
  reasons: {hard_days: Hard days}"""


def test_a_recommendation_reads_derived_values(load: LoadYaml) -> None:
    module = load(MODULE.replace("BLOCK", VALID))
    plan = recommendation_plan(module)
    assert plan is not None
    rows: list[dict[str, Value]] = [{"date": day(d), "effort": 9, "hard": True} for d in (6, 3, 0)]
    found = recommend(module, plan, {"session": rows}, {}, DAY)
    assert (found.headline, found.text) == ("REST", "REST — Three hard days.")
    assert [r.value for r in found.reasons] == [3]


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (
            "  rules:\n    - {message: Always.}\n    - {if: 'true', message: Never.}",
            ["recommendation: only the last rule can leave out `if`"],
        ),
        (
            "  values:\n    n: 'count(window(session.effort, days=7, until=date))'\n"
            "  rules:\n    - {if: 'n + 1', message: x}",
            ["recommendation.rules[0].if: `if` must be a condition (true or false)"],
        ),
        (
            "  rules:\n    - {if: 'efort > 3', message: x}",
            ["recommendation.rules[0].if: unknown field 'efort'"],
        ),
        (
            "  values:\n    n: 'last(session.efort, until=date)'\n  rules:\n    - {message: x}",
            ["recommendation.values.n: 'session' has no field 'efort' (did you mean 'effort'?)"],
        ),
        (
            "  rules:\n    - {message: x}\n  reasons: {n: N}",
            ["recommendation.reasons.n: 'n' is not a value of the recommendation"],
        ),
    ],
)
def test_problems(problems: Problems, block: str, expected: list[str]) -> None:
    found = problems(MODULE.replace("BLOCK", block))
    assert [p.split(" ", 1)[1].split(" (at character")[0] for p in found] == expected
