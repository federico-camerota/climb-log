# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001  (prescriptions use the multiplication sign)
"""The shoulder module (D-116): the rules of 00-current-state.md §3 (status, action, review
flag), the prescription of a plan week, the activity taken from the journal, its batch forms
and next-morning item, and a round trip through a workbook. The sheet formulas are checked on
LibreOffice in `test_formula_parity.py`. Fictional data only."""

import datetime as dt
from pathlib import Path

import pytest

from climblog.expr import Value
from climblog.modules import load_module
from climblog.modules.batch import batch_rows, shared_fields
from climblog.modules.compute import compute_module
from climblog.modules.forms import due
from climblog.modules.formulas import formula_columns
from climblog.modules.prefill import parse_from, value_from
from climblog.modules.program import Run, Runs
from climblog.modules.schema import BaseField
from climblog.storage import XlsxBackend, load_data, sync_module
from climblog.storage.write import RecordWriter

ROOT = Path(__file__).parent.parent
SHOULDER = load_module(ROOT / "modules" / "shoulder.yaml")
MONDAY = dt.date(2026, 9, 7)  # week 1 of the fictional run
RUNS = Runs([Run(1, "2026-W37", MONDAY)])
SETTINGS = {"yellow_min": 3, "red_min": 5}
EXERCISES: list[dict[str, Value]] = [
    {"id": "P1", "name": "[ESEMPIO] Primer", "session": "Primer", "w1": "1×10", "w2": "1×12"},
    {"id": "A1", "name": "[ESEMPIO] Row", "session": "A", "w1": "3×8", "w2": "3×10"},
    {"id": "B1", "name": "[ESEMPIO] Press", "session": "B", "w1": "3×6", "w2": "Skip"},
]
MEASURES: list[dict[str, Value]] = [
    {"id": "M1", "label": "[ESEMPIO] Hang (s)", "value_type": "number"},
    {"id": "M2", "label": "[ESEMPIO] Clicking?", "value_type": "bool"},
]
REFERENCE = {"exercises": EXERCISES, "retest_measures": MEASURES}


def derived(entity: str, rows: list[dict[str, Value]]) -> list[dict[str, Value]]:
    tables = {entity: rows}
    return compute_module(SHOULDER, tables, SETTINGS, RUNS, REFERENCE)[entity]


def day(n: int) -> dt.date:
    return MONDAY + dt.timedelta(days=n)


# ---- The module ----


def test_every_value_has_a_sheet_formula() -> None:
    _, app_only = formula_columns(SHOULDER)
    assert app_only == []  # the review flag too: its trend reads chained prev() helpers


def test_the_forms() -> None:
    forms = SHOULDER.forms or {}
    assert shared_fields(SHOULDER, forms["session_a"]) == ["date"]
    assert shared_fields(SHOULDER, forms["retest"]) == ["date", "checkpoint"]
    rows = batch_rows(SHOULDER, forms["session_b"], EXERCISES, [], {"date": day(1)}, 1)
    assert [r.key for r in rows.rows] == ["P1", "B1"]  # the primer, then session B


# ---- Status, action and review flag (00 §3) ----


@pytest.mark.parametrize(
    ("values", "status", "flag"),
    [
        ({"red_flag": True, "pain_during": 0}, "RED", "REVIEW NOW — red-flag symptom"),
        ({"pain_during": 5}, "RED", "REVIEW NOW — pain ≥5/10"),
        ({"pain_next_am": 6, "pain_during": 1}, "RED", "REVIEW NOW — pain ≥5/10"),
        ({"pain_during": 3}, "YELLOW", "REVIEW — pain ≥3/10"),
        ({"pain_during": 2, "pain_next_am": 1}, "GREEN", "OK — monitor"),
        ({"trap_fatigue": 6}, None, "OK — monitor"),  # no front-shoulder pain: no status
    ],
)
def test_one_check_in(values: dict[str, Value], status: str | None, flag: str) -> None:
    [found] = derived("checkin", [{"date": day(1), **values}])
    assert (found["status"], found["review_flag"]) == (status, flag)
    actions = {
        "RED": "Do not progress; stop aggravating work and seek clinical advice if "
        "persistent/severe",
        "YELLOW": "Hold/reduce load; review next-morning response",
        "GREEN": "Progress only if movement quality is good and trend remains stable",
    }
    assert found["action"] == actions.get(status or "")


@pytest.mark.parametrize(
    ("mornings", "flag"),
    [
        ([1, 2], "REVIEW — next-morning pain rising"),
        ([2, 2, 2], "REVIEW — repeated upward pain trend"),
        ([1, 2, 2], "REVIEW — repeated upward pain trend"),
        ([2, 1, 2], "REVIEW — next-morning pain rising"),
        ([2, 1], "OK — monitor"),
        ([3, 2, 2], "OK — monitor"),  # not upward over the three
        ([1, 1], "OK — monitor"),  # below 2
        ([None, 2], "OK — monitor"),  # nothing the morning before
    ],
)
def test_the_next_morning_trend(mornings: list[int | None], flag: str) -> None:
    rows: list[dict[str, Value]] = [
        {"date": day(i), "pain_during": 0, "pain_next_am": m} for i, m in enumerate(mornings)
    ]
    assert derived("checkin", rows)[-1]["review_flag"] == flag


def test_the_trend_follows_the_dates_not_the_rows() -> None:
    rows: list[dict[str, Value]] = [
        {"date": day(2), "pain_next_am": 2},
        {"date": day(0), "pain_next_am": 1},  # typed later, but the day before
    ]
    assert [r["review_flag"] for r in derived("checkin", rows)] == [
        "REVIEW — next-morning pain rising",
        "OK — monitor",
    ]


def test_the_thresholds_are_settings() -> None:
    tables: dict[str, list[dict[str, Value]]] = {"checkin": [{"date": day(1), "pain_during": 3}]}
    [found] = compute_module(SHOULDER, tables, {"yellow_min": 4, "red_min": 6}, RUNS)["checkin"]
    assert (found["status"], found["review_flag"]) == ("GREEN", "OK — monitor")


# ---- The exercise log ----


@pytest.mark.parametrize(
    ("values", "prescribed", "done"),
    [
        ({"date": day(2), "exercise_id": "A1", "actual": "3×8"}, "3×8", True),  # week 1
        ({"date": day(8), "exercise_id": "A1"}, "3×10", False),  # week 2, nothing done
        ({"date": day(8), "exercise_id": "a1", "plan_week": 1}, "3×8", False),  # week 1, late
        ({"date": day(9), "exercise_id": "B1", "actual": "—", "quality": "Skipped"}, "Skip", False),
        ({"date": day(2), "exercise_id": "Z9"}, None, False),  # not in the plan
        ({"date": day(-3), "exercise_id": "A1", "actual": "3×8"}, None, True),  # before the run
    ],
)
def test_the_prescription_of_a_plan_week(
    values: dict[str, Value], prescribed: str | None, done: bool
) -> None:
    [found] = derived("exercise_log", [values])
    assert (found["prescribed"], found["done"]) == (prescribed, done)


# ---- Taken from the journal ----


@pytest.mark.parametrize(
    ("session", "activity"),
    [
        ({"setting": "Indoor", "session_type": "Climbing"}, "Climbing indoor"),
        ({"setting": "Home wall", "session_type": "Climbing"}, "Climbing indoor"),
        ({"setting": "Outdoor", "session_type": "Climbing"}, "Climbing outdoor"),
        ({"setting": "Home wall", "session_type": "Hangboard"}, "Hangboard"),
        ({"setting": "Indoor", "session_type": "Strength"}, None),  # you pick: Session A or B
        ({"setting": None, "session_type": "Climbing"}, None),
    ],
)
def test_the_activity_from_the_journal(session: dict[str, Value], activity: str | None) -> None:
    field = SHOULDER.entities["checkin"].fields["activity"]
    assert isinstance(field, BaseField)
    source = parse_from(field.from_ or "")
    assert source is not None and source.module == "journal"
    assert value_from(SHOULDER, field, source, session) == activity


def test_the_grade_from_the_journal() -> None:
    field = SHOULDER.entities["checkin"].fields["hardest_grade"]
    assert isinstance(field, BaseField)
    source = parse_from(field.from_ or "")
    assert source is not None
    assert value_from(SHOULDER, field, source, {"hardest_grade": "6b+"}) == "6b+"
    assert value_from(SHOULDER, field, source, {"hardest_grade": "6"}) == "6"  # gym numbers


# ---- Today ----


def test_the_next_morning_pain_waits_for_the_morning() -> None:
    rows: list[dict[str, Value]] = [{"date": day(1), "pain_during": 1}]
    items = [(i.form, i.key.get("date")) for i in due(SHOULDER, {"checkin": rows}, day(2)).items]
    assert ("next_morning", day(1)) in items


# ---- In a workbook ----


def test_a_round_trip(tmp_path: Path) -> None:
    repo = XlsxBackend(tmp_path / "shoulder.xlsx")
    sync_module(SHOULDER, repo)
    writer = RecordWriter(SHOULDER, repo)
    writer.add_many(
        [
            ("checkin", {"date": day(1), "pain_during": 1, "pain_next_am": 2}),
            ("exercise_log", {"date": day(1), "exercise_id": "a1", "actual": "3×8"}),
            ("retest", {"date": day(0), "measure_id": "M2", "checkpoint": "Start", "value": "No"}),
        ],
        runs=["2026-W37"],
        reference=REFERENCE,
    )
    data = load_data(SHOULDER, repo)
    assert data.issues == []
    assert [r.start_week for r in data.runs.runs] == ["2026-W37"]
    assert [r["id"] for r in data.reference["exercises"].rows] == ["P1", "A1", "B1"]
    [log] = data.entities["exercise_log"].records
    assert log["exercise_id"] == "A1"  # written as the table spells it
