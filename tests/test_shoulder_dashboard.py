# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001  (prescriptions use the multiplication sign)
"""The shoulder dashboard (D-117): the week table, the program grid, the retests before/after,
the review-flag table and the status days by program week, on fictional rows; then against the
legacy Dashboard tab, computed by LibreOffice on a fictional tracker (`fictional_shoulder.py`)."""

import datetime as dt
import tempfile
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from conftest import Problems
from fastapi.testclient import TestClient
from fictional_shoulder import START, legacy_shoulder
from parity import recalculate, soffice, work_dir

from climblog.analytics import compute_view
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.importers.legacy_shoulder import (
    UNDATED_KNOWN,
    WEEK_KNOWN,
    import_legacy_shoulder,
    parity_shoulder,
    read_legacy_shoulder,
)
from climblog.main import create_app
from climblog.modules import Module, load_module
from climblog.modules.compute import compute_module
from climblog.modules.program import Run, Runs
from climblog.storage import CachedRepository, Snapshots, XlsxBackend, load_data

ROOT = Path(__file__).parent.parent
SHOULDER_FILE = ROOT / "modules" / "shoulder.yaml"
SHOULDER = load_module(SHOULDER_FILE)
MONDAY = dt.date(2026, 9, 7)
RUNS = Runs([Run(1, "2026-W37", MONDAY)])
SETTINGS: dict[str, Value] = {"yellow_min": 3, "red_min": 5}
EXERCISES: list[dict[str, Value]] = [
    {"id": "B1", "name": "[ESEMPIO] Press", "session": "B", "w1": "3×6", "w2": "Skip"},
    {"id": "P1", "name": "[ESEMPIO] Primer", "session": "Primer", "w1": "1×10", "w2": "1×12"},
    {"id": "A1", "name": "[ESEMPIO] Row", "session": "A", "w1": "3×8", "w2": "3×10"},
    {"id": "A9", "name": "[ESEMPIO] Old", "session": "A", "w1": "3×8", "retired": True},
]
MEASURES: list[dict[str, Value]] = [
    {
        "id": "M1",
        "label": "[ESEMPIO] Hang (s)",
        "value_type": "number",
        "direction": "higher_better",
    },
    {"id": "M2", "label": "[ESEMPIO] Clicking?", "value_type": "bool"},
    {"id": "M3", "label": "[ESEMPIO] Reach (cm)", "value_type": "number"},
]
REFERENCE = {"exercises": EXERCISES, "retest_measures": MEASURES}


def day(n: int) -> dt.date:
    return MONDAY + dt.timedelta(days=n)


def view(
    name: str,
    tables: dict[str, list[dict[str, Value]]],
    on: dt.date = MONDAY + dt.timedelta(days=16),
    runs: Runs = RUNS,
) -> list[dict[str, Any]]:
    derived = compute_module(SHOULDER, tables, SETTINGS, runs, REFERENCE)
    full = {
        entity: [{**row, **values} for row, values in zip(rows, derived[entity], strict=True)]
        for entity, rows in tables.items()
    }
    widgets = (SHOULDER.views or {})[name]
    return compute_view(SHOULDER, widgets, full, SETTINGS, on, runs=runs, reference=REFERENCE)


def widget(name: str, kind: str, tables: dict[str, list[dict[str, Value]]], **kw: Any) -> Any:
    return next(w for w in view(name, tables, **kw) if w["widget"] == kind)


CHECKINS: list[dict[str, Value]] = [
    {"date": day(0), "primer_done": True, "trap_fatigue": 2, "pain_during": 1, "pain_next_am": 1},
    {"date": day(2), "primer_done": False, "trap_fatigue": 4, "pain_during": 3},  # YELLOW
    {"date": day(4), "red_flag": True, "pec_fatigue": 1, "pain_next_am": 1},  # RED
    {"date": day(9), "primer_done": True, "pain_during": 0, "pain_next_am": 2},  # rising
]
LOGS: list[dict[str, Value]] = [
    {"date": day(0), "exercise_id": "P1", "actual": "1×10", "quality": "Clean"},
    {"date": day(0), "exercise_id": "A1", "actual": "3×8", "quality": "Some shrug/compensation"},
    {"date": day(1), "exercise_id": "a1", "actual": "3×8", "quality": "Stopped early"},
    {"date": day(3), "exercise_id": "B1"},  # opened, nothing typed: not logged
    {"date": day(8), "exercise_id": "B1", "plan_week": 1, "actual": "3×6", "quality": "Clean"},
]


# ---- The week table (the legacy Dashboard) ----


def test_the_week_table() -> None:
    table = widget("overview", "week_table", {"checkin": CHECKINS, "exercise_log": LOGS})
    assert (table["run"], table["current"]) == (1, 3)
    assert [c["label"] for c in table["columns"]][:3] == [
        "Log completion",
        "Sessions with primer",
        "Upper-trap fatigue",
    ]
    weeks = {w["week"]: w for w in table["weeks"]}
    assert len(weeks) == 12 and weeks[4]["light"] and weeks[1]["phase"].startswith("Block 1")
    # log completion: the records logged for the plan week ÷ the 3 live exercises (B1 late: W1)
    one, two = weeks[1]["values"], weeks[2]["values"]
    assert one == [4 / 3, 1, 3.0, 2.0, 1.0, 1.0, 1, 1, 1, 2]
    assert two == [None, 1, None, 0.0, 2.0, None, 1, 0, 0, 1]
    assert weeks[9]["values"] == [None, 0, None, None, None, None, 0, 0, 0, 0]  # counts are 0


def test_the_latest_run_only() -> None:
    runs = Runs([Run(1, "2026-W37", MONDAY), Run(2, "2026-W39", day(14))])
    table = widget("overview", "week_table", {"checkin": CHECKINS, "exercise_log": []}, runs=runs)
    assert (table["run"], table["current"]) == (2, 1)
    assert all(v in (None, 0) for w in table["weeks"] for v in w["values"])
    early = widget("overview", "week_table", {"checkin": CHECKINS}, on=day(-1))
    assert (early["run"], early["weeks"]) == (None, [])


def test_past_the_last_week() -> None:
    table = widget("overview", "week_table", {"checkin": CHECKINS}, on=day(7 * 13))
    assert table["current"] == 14 and len(table["weeks"]) == 14
    assert table["weeks"][13]["phase"] is None


# ---- The other overview widgets ----


def test_the_review_flags_and_status_days() -> None:
    found = view("overview", {"checkin": CHECKINS, "exercise_log": LOGS})
    flags = next(w for w in found if w["widget"] == "table")
    assert [r["date"] for r in flags["rows"]] == [
        day(9).isoformat(),
        day(4).isoformat(),
        day(2).isoformat(),
    ]
    assert flags["rows"][0]["review_flag"] == "REVIEW — next-morning pain rising"
    bars = next(w for w in found if w["widget"] == "weekbars")
    assert [(s["label"], s["group"]) for s in bars["stacks"]] == [
        ("GREEN", "Run 1"),
        ("YELLOW", "Run 1"),
        ("RED", "Run 1"),
    ]
    assert [s["values"][:3] for s in bars["stacks"]] == [[1, 1, None], [1, 0, None], [1, 0, None]]


def test_status_days_of_two_runs() -> None:
    runs = Runs([Run(1, "2026-W37", MONDAY), Run(2, "2026-W38", day(7))])
    bars = widget("overview", "weekbars", {"checkin": CHECKINS}, runs=runs)
    assert [(s["label"], s["group"]) for s in bars["stacks"]] == [
        ("Run 1 · GREEN", "Run 1"),
        ("Run 1 · YELLOW", "Run 1"),
        ("Run 1 · RED", "Run 1"),
        ("Run 2 · GREEN", "Run 2"),
    ]


# ---- The program grid ----


def test_the_program_grid() -> None:
    grid = widget("plan", "program_grid", {"exercise_log": LOGS})
    assert grid["qualities"][0] == "Clean" and grid["current"] == 3
    assert [(r["key"], r["group"]) for r in grid["rows"]] == [
        ("P1", "Primer"),
        ("A1", "A"),
        ("B1", "B"),
    ]  # by session, in its choices' order; the retired A9 left out
    p1, a1, b1 = grid["rows"]
    assert a1["cells"][0] == {
        "prescribed": "3×8",
        "skip": False,
        "logged": 2,
        "quality": "Stopped early",  # the worst of the two
    }
    assert b1["cells"][0]["logged"] == 1  # done late, in week 2, for week 1
    assert b1["cells"][1] == {"prescribed": "Skip", "skip": True, "logged": 0, "quality": None}
    assert p1["cells"][2]["skip"]  # nothing typed for week 3
    assert [w["share"] for w in grid["weeks"][:3]] == [4 / 3, None, None]
    assert (p1["share"], a1["share"], b1["share"]) == (0.5, 0.5, 1.0)


# ---- Retests ----


def test_before_and_after() -> None:
    retests: list[dict[str, Value]] = [
        {"date": day(0), "measure_id": "M1", "checkpoint": "Start", "value": "10"},
        {"date": day(27), "measure_id": "m1", "checkpoint": "End W4", "value": "12,5"},
        {"date": day(0), "measure_id": "M2", "checkpoint": "Start", "value": "Yes"},
        {"date": day(27), "measure_id": "M2", "checkpoint": "End W4", "value": "No"},
        {"date": day(27), "measure_id": "M3", "checkpoint": "End W4", "value": "30"},  # no Start
    ]
    found = widget("retests", "before_after", {"retest": retests}, on=day(30))
    assert found["checkpoints"] == ["Start", "End W4", "End W8", "End W12"]
    m1, m2, m3 = found["rows"]
    assert m1["cells"][:2] == [
        {"date": day(0).isoformat(), "value": 10.0},
        {"date": day(27).isoformat(), "value": 12.5},
    ]
    assert m1["change"] == {"diff": 2.5, "better": True, "first": None, "latest": None}
    assert m2["change"] == {"diff": None, "better": None, "first": "Yes", "latest": "No"}
    assert m3["change"] is None
    earlier = widget("retests", "before_after", {"retest": retests}, on=day(20))
    assert earlier["rows"][0]["cells"][1] is None  # not yet measured on that day


# ---- Checked at load ----


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("agg: share, of: exercises", "agg: share", "share goes with `of`"),
        (
            "of: exercises, week: plan_wk",
            "of: drills, week: plan_wk",
            "no reference table 'drills'",
        ),
        ("week: plan_wk}", "week: nope}", "'exercise_log' has no field or derived value 'nope'"),
        (
            "agg: mean}\n        - {label: Pain during",
            "agg: count, equals: 3, of: x}\n        - {label: Pain during",
            "share goes with `of`",
        ),
        ("by: measure_id", "by: checkpoint", "'checkpoint' is not a ref field of 'retest'"),
        ("group: session", "group: nope", "'exercises' has no field 'nope'"),
        (
            "where: {field: flagged",
            "where: {field: nope",
            "'checkin' has no field or derived value 'nope'",
        ),
    ],
)
def test_dashboard_problems(problems: Problems, old: str, new: str, message: str) -> None:
    text = SHOULDER_FILE.read_text(encoding="utf-8")
    assert old in text
    found = problems(text.replace(old, new, 1))
    assert any(message in line for line in found), found


def test_a_grid_needs_a_program(problems: Problems) -> None:
    text = SHOULDER_FILE.read_text(encoding="utf-8")
    start, end = text.index("program:"), text.index("scales:")
    found = problems(text[:start] + text[end:])
    assert any("needs a program: block" in line for line in found), found


# ---- The API ----


def test_the_views_in_the_app(tmp_path: Path) -> None:
    legacy = legacy_shoulder(tmp_path / "legacy.xlsx", seed=1)
    repo = XlsxBackend(tmp_path / "shoulder.xlsx")
    import_legacy_shoulder(legacy.path, SHOULDER, repo)
    catalog = Catalog(AppConfig())
    cached = CachedRepository("shoulder", repo, Snapshots(tmp_path / "snapshots"))
    catalog.entries["shoulder"] = Entry("shoulder", SHOULDER, [], cached)
    client = TestClient(create_app(catalog=catalog))
    on = {"date": (START + dt.timedelta(days=30)).isoformat()}
    body = client.get("/api/modules/shoulder/views/overview", params=on).json()
    assert [w["widget"] for w in body["widgets"]] == [
        "kpi",
        "kpi",
        "week_table",
        "line",
        "weekbars",
        "table",
    ]
    grid = client.get("/api/modules/shoulder/views/plan", params=on).json()["widgets"][0]
    assert len(grid["rows"]) == 17 and grid["weeks"][0]["share"] == 1.0
    retests = client.get("/api/modules/shoulder/views/retests", params=on).json()["widgets"][0]
    assert len(retests["rows"]) == 14 and retests["rows"][0]["cells"][1] is not None


# ---- Against the legacy Dashboard (LibreOffice) ----


def _recalculated(folder: Path, **kw: Any) -> Path:
    command = soffice()
    assert command is not None
    written = legacy_shoulder(folder / "legacy.xlsx", seed=4, **kw)
    recalculate(command, written.path)
    return folder / "recalculated" / "legacy.xlsx"


@pytest.mark.skipif(soffice() is None, reason="no working LibreOffice")
def test_the_week_table_is_the_legacy_dashboard() -> None:
    """Started on a Monday, the legacy weeks are the app's: every number matches, but the
    completion of week 5, where a row typed without a date isn't imported."""
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        data = read_legacy_shoulder(_recalculated(Path(folder), start=MONDAY), SHOULDER)
    columns = [c for c in parity_shoulder(data, SHOULDER) if c.entity == "dashboard"]
    assert len(columns) == 10 and sorted(data.dashboard) == list(range(1, 13))
    assert all(c.compared >= 5 for c in columns)
    assert [c.field for c in columns if c.mismatches] == ["Log completion"]
    [(monday, sheet_value, ours)] = columns[0].mismatches
    assert (monday, ours) == (MONDAY + dt.timedelta(days=28), None)
    assert sheet_value == pytest.approx(1 / 17)
    assert columns[0].known == UNDATED_KNOWN


@pytest.mark.skipif(soffice() is None, reason="no working LibreOffice")
def test_a_tuesday_start_differs_only_where_mondays_move() -> None:
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        data = read_legacy_shoulder(_recalculated(Path(folder)), SHOULDER)
    columns = [c for c in parity_shoulder(data, SHOULDER) if c.entity == "dashboard"]
    assert [c.field for c in columns if c.mismatches and not c.known] == []
    assert any(c.known == WEEK_KNOWN for c in columns)


@pytest.mark.skipif(soffice() is None, reason="no working LibreOffice")
def test_the_change_is_the_legacy_one(tmp_path: Path) -> None:
    """With End week 12 filled, the before/after change of each number is the legacy
    `Retests` Change column (End W12 - Start)."""
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        computed = _recalculated(Path(folder), w12=True)
        sheet = openpyxl.load_workbook(computed, data_only=True)["Retests"]
        legacy = {f"M{r - 4}": sheet[f"F{r}"].value for r in range(5, 19)}
        repo = XlsxBackend(tmp_path / "shoulder.xlsx")
        import_legacy_shoulder(computed, SHOULDER, repo)
    data = load_data(SHOULDER, repo)
    tables = {n: e.records for n, e in data.entities.items()}
    reference = data.reference_rows()
    derived = compute_module(SHOULDER, tables, data.settings, data.runs, reference)
    full = {
        n: [{**r, **v} for r, v in zip(rows, derived[n], strict=True)] for n, rows in tables.items()
    }
    [found] = compute_view(
        SHOULDER,
        (SHOULDER.views or {})["retests"],
        full,
        data.settings,
        START + dt.timedelta(days=100),
        runs=data.runs,
        reference=reference,
    )
    ours = {r["key"]: (r["change"] or {}).get("diff") for r in found["rows"]}
    numbers = {k: v for k, v in legacy.items() if v not in (None, "")}
    assert numbers and all(ours[k] == pytest.approx(v) for k, v in numbers.items())
    assert all(ours[k] is None for k in legacy if k not in numbers)


def test_the_module_keeps_its_views() -> None:
    module: Module = SHOULDER
    assert set(module.views or {}) == {"overview", "plan", "retests"}
