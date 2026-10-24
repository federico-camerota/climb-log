# SPDX-License-Identifier: GPL-3.0-or-later
"""Whole tables: prev, parent.x, children(e).x and last across records (03 §2.1b, §2.3, D-045)."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml

from climblog.expr import Value
from climblog.modules import Module, load_module
from climblog.modules.compute import compute_module

DRAFTS = Path(__file__).parent.parent / "design" / "modules"

# A fictional module: sessions keyed by date and type, sets of the hang sessions, rest days.
BASE = """\
module: test_records
name: Test records
version: 1
kind: journal
entities:
  session:
    label: Session
    tab: Sessions
    key: [date, session_type]
    fields:
      date: {type: date}
      session_type: {type: choice, choices: [Curls, Hangs]}
      target_kg: {type: number}
    derived:
      gap: "days_between(prev(date), date)"
      n_sets: "count(children(set))"
      top_kg: "max(children(set).kg)"
      volume: "sum(children(set).volume)"
      prev_top: "prev(top_kg)"
  set:
    label: Set
    tab: Sets
    key: [date, set_no]
    parent: {entity: session, key: [date], fixed: {session_type: Hangs}}
    fields:
      date: {type: date}
      set_no: {type: integer}
      kg: {type: number}
      reps: {type: integer}
    derived:
      volume: "kg * reps"
      over_target: "kg > parent.target_kg"
  rest_day:
    label: Rest day
    tab: Rest days
    key: [date]
    fields:
      date: {type: datetime}
    derived:
      since_climb: "days_between(last(session.date, before=date), date)"
"""


def day(n: int) -> dt.date:
    return dt.date(2026, 10, n)


def run(module: Module, **tables: list[dict[str, Value]]) -> dict[str, list[dict[str, Value]]]:
    return compute_module(module, tables, {})


def column(rows: list[dict[str, Value]], name: str) -> list[Value]:
    return [row[name] for row in rows]


def test_prev_follows_date_then_key_not_row_order(load: LoadYaml) -> None:
    sessions: list[dict[str, Value]] = [
        {"date": day(22), "session_type": "Hangs"},
        {"date": day(20), "session_type": "Hangs"},
        {"date": day(22), "session_type": "Curls"},  # same day: Curls sorts before Hangs
        {"date": None, "session_type": "Hangs"},  # undated: no previous row, nobody's previous
        {"date": day(25), "session_type": "Curls"},
    ]
    gaps = column(run(load(BASE), session=sessions)["session"], "gap")
    assert gaps == [0, None, 2, None, 3]


def test_children_match_the_parent_key_and_the_fixed_values(load: LoadYaml) -> None:
    sessions: list[dict[str, Value]] = [
        {"date": day(20), "session_type": "Hangs", "target_kg": 15},
        {"date": day(20), "session_type": "Curls"},  # same date, but sets are hang sets
        {"date": day(21), "session_type": "Hangs"},  # no sets
    ]
    sets: list[dict[str, Value]] = [
        {"date": day(20), "set_no": 2, "kg": 20, "reps": 1},
        {"date": day(20), "set_no": 1, "kg": 10, "reps": 3},
        {"date": day(23), "set_no": 1, "kg": 5, "reps": 1},  # orphan: no session that day
    ]
    out = run(load(BASE), session=sessions, set=sets)
    assert column(out["session"], "n_sets") == [2, 0, 0]
    assert column(out["session"], "top_kg") == [20, None, None]
    assert column(out["session"], "volume") == [50, None, None]  # children's derived values
    assert column(out["set"], "over_target") == [True, False, False]  # orphan: blank parent


def test_prev_reads_derived_values_of_the_previous_row(load: LoadYaml) -> None:
    sessions: list[dict[str, Value]] = [
        {"date": day(21), "session_type": "Hangs"},
        {"date": day(20), "session_type": "Hangs"},
    ]
    sets: list[dict[str, Value]] = [{"date": day(20), "set_no": 1, "kg": 12, "reps": 1}]
    out = run(load(BASE), session=sessions, set=sets)
    assert column(out["session"], "prev_top") == [12, None]


def test_last_is_strictly_before(load: LoadYaml) -> None:
    sessions: list[dict[str, Value]] = [
        {"date": day(20), "session_type": "Hangs"},
        {"date": day(17), "session_type": "Curls"},
    ]
    rest: list[dict[str, Value]] = [
        {"date": dt.datetime(2026, 10, 21, 8, 0)},  # a datetime counts as its day
        {"date": day(20)},  # the session the same day is not before
        {"date": day(15)},
        {"date": None},
    ]
    since = column(run(load(BASE), session=sessions, rest_day=rest)["rest_day"], "since_climb")
    assert since == [1, 3, None, None]


def test_missing_tables_have_no_rows(load: LoadYaml) -> None:
    out = run(load(BASE))
    assert out == {"session": [], "set": [], "rest_day": []}


# ---- The drafts ----


def settings_of(module: Module) -> dict[str, Value]:
    return {key: setting.default for key, setting in module.settings.items()}


def test_shoulder_review_flag_follows_the_legacy_trend_rules() -> None:
    """00-current-state §3: next-AM pain rising, and three non-decreasing values ending ≥ 2."""
    shoulder = load_module(DRAFTS / "shoulder.yaml")
    pain: list[Value] = [1, 2, 2, 2, None, 1]
    rows: list[dict[str, Value]] = [
        {"date": day(14 + i), "pain_next_am": p} for i, p in enumerate(pain)
    ]
    out = compute_module(shoulder, {"checkin": rows}, settings_of(shoulder))
    assert column(out["checkin"], "review_flag") == [
        "OK — monitor",
        "REVIEW — next-morning pain rising",
        "REVIEW — repeated upward pain trend",
        "REVIEW — repeated upward pain trend",
        "OK — monitor",
        "OK — monitor",  # the day before is blank: not rising
    ]


def test_finger_strength_session_aggregates() -> None:
    fingers = load_module(DRAFTS / "finger-strength.yaml")
    tables: dict[str, list[dict[str, Value]]] = {
        "session": [
            {"date": day(20), "session_type": "Max hangs"},
            {"date": day(21), "session_type": "Finger curls"},
        ],
        "hang_set": [
            {"date": day(20), "set_no": 1, "added_kg": 10},
            {"date": day(20), "set_no": 2, "added_kg": 12.5},
        ],
        "curl_set": [
            {"date": day(21), "set_no": 1, "load_left_kg": 30, "reps_left": 10,
             "load_right_kg": 28, "reps_right": 10},
        ],
    }  # fmt: skip
    hangs, curls = compute_module(fingers, tables, settings_of(fingers))["session"]
    assert (hangs["n_sets"], hangs["top_added_kg"], hangs["curl_volume"]) == (2, 12.5, None)
    assert (curls["n_sets"], curls["est_1rm_left"], curls["curl_volume"]) == (1, 40.0, 580)
    assert curls["lr_imbalance_pct"] == 6.8  # 40 vs 37.3 (Epley), left stronger


@pytest.mark.parametrize(
    ("rest_date", "expected"),
    [(day(21), 1), (day(23), 1), (day(20), None)],
)
def test_journal_days_since(rest_date: dt.date, expected: int | None) -> None:
    journal = load_module(DRAFTS / "journal.yaml")
    tables: dict[str, list[dict[str, Value]]] = {
        "session": [{"date": day(20), "session_no": 1}, {"date": day(22), "session_no": 2}],
        "rest_day": [{"date": rest_date}],
    }
    out = compute_module(journal, tables, settings_of(journal))
    assert column(out["session"], "days_since_prev") == [None, 2]
    assert column(out["rest_day"], "days_since_climb") == [expected]
