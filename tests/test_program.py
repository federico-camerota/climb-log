# SPDX-License-Identifier: GPL-3.0-or-later
"""Program modules (D-109): the program block, runs from the Runs tab, `program.<name>` in
expressions, the Runs tab in the workbook, weeks in charts and the metric layer, starting a run
in the app. The formula side is checked on LibreOffice in `test_formula_parity.py`."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient
from formula_module import PROGRAM_MODULE
from pydantic import TypeAdapter

from climblog.analytics import compute_view
from climblog.analytics.metrics import Query, QueryError, run_query
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import Module
from climblog.modules.compute import compute_module
from climblog.modules.formulas import GOOGLE, formula_columns
from climblog.modules.program import RUNS_TAB, Run, Runs, parse_week, week_text
from climblog.modules.schema import Widget
from climblog.storage import CachedRepository, Snapshots, XlsxBackend, load_data, sync_module
from climblog.storage.base import Append
from climblog.storage.gsheets_sync import _validation as google_validation
from climblog.storage.layout import WeekRule, workbook_layout
from climblog.storage.write import RecordWriter, WriteError

WIDGET: TypeAdapter[Widget] = TypeAdapter(Widget)
W37 = dt.date(2026, 9, 7)  # Monday of 2026-W37
RUNS = Runs([Run(1, "2026-W37", W37), Run(2, "2026-W43", dt.date(2026, 10, 19))])


@pytest.fixture
def program(load: LoadYaml) -> Module:
    return load(PROGRAM_MODULE)


# ---- Weeks and runs ----


@pytest.mark.parametrize(
    ("text", "monday"),
    [
        ("2026-W42", dt.date(2026, 10, 12)),
        ("2026-W01", dt.date(2025, 12, 29)),  # week 1 can start in the year before
        ("2020-W53", dt.date(2020, 12, 28)),  # 2020 has 53 weeks
        (" 2027-W03 ", dt.date(2027, 1, 18)),
    ],
)
def test_a_start_week_is_its_monday(text: str, monday: dt.date) -> None:
    assert parse_week(text) == monday
    assert week_text(monday) == text.strip()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("2027-W53", "2027 has weeks 1 to 52, not 53"),
        ("2026-W00", "2026 has weeks 1 to 53, not 0"),  # 2026 starts on a Thursday: 53 weeks
        ("2026-W3x", "is not a week like 2026-W42"),
        ("2026-42", "is not a week like 2026-W42"),
        ("2026-W4", "is not a week like 2026-W42"),
    ],
)
def test_a_bad_start_week(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_week(text)


def week_of(day: dt.date) -> tuple[int, int] | None:
    found = RUNS.at(day)
    return None if found is None else (found.run, found.week)


def test_the_run_and_week_of_a_day() -> None:
    assert week_of(dt.date(2026, 9, 6)) is None  # before the first run
    assert week_of(W37) == (1, 1)
    assert week_of(dt.datetime(2026, 9, 7, 18, 30)) == (1, 1)  # a datetime is its day
    assert week_of(dt.date(2026, 9, 13)) == (1, 1)
    assert week_of(dt.date(2026, 9, 14)) == (1, 2)
    assert week_of(dt.date(2026, 10, 18)) == (1, 6)  # past week 4: counts on
    assert week_of(dt.date(2026, 10, 19)) == (2, 1)
    assert RUNS.next_number() == 3


# ---- The module file ----


def test_program_values_of_a_record(program: Module) -> None:
    assert program.program is not None
    assert list(program.entities["checkin"].derived)[:2] == ["run", "week"]  # added first
    tables: dict[str, list[dict[str, Value]]] = {
        "checkin": [
            {"date": dt.date(2026, 9, 1), "minutes": 30},
            {"date": dt.date(2026, 9, 15), "minutes": 30},
            {"date": dt.date(2026, 9, 30), "minutes": 30},
            {"date": dt.date(2026, 10, 6), "minutes": 30},
        ],
        "exercise": [{"date": dt.date(2026, 9, 15), "set_no": 1, "reps": 5}],
    }
    found = compute_module(program, tables, {}, RUNS)
    checkins = [
        (r["run"], r["week"], r["phase"], r["light"], r["target"]) for r in found["checkin"]
    ]
    assert checkins == [
        (None, None, None, False, None),
        (1, 2, "Base", True, 20),
        (1, 4, "Peak · build", True, 40),
        (1, 5, None, False, 100),  # after the last week: no phase
    ]
    assert found["exercise"][0] | {} == {
        "run": 1,
        "week": 2,
        "in_base": True,
        "reps_week": 10,
    }
    # without runs nothing has a week
    assert compute_module(program, tables, {})["checkin"][1]["week"] is None


def test_every_program_value_has_a_sheet_formula(program: Module) -> None:
    placed, app_only = formula_columns(program)
    assert app_only == []
    assert ("Runs", "auto:start") in {(c.tab, c.key) for c in placed}


ENTITY = """\
entities:
  checkin:
    label: Check-in
    key: [date]
    fields:
      date: {type: date}
"""


@pytest.mark.parametrize(
    ("head", "message"),
    [
        ("kind: program\n", "program: a program module needs a program: block"),
        ("kind: journal\nprogram: {weeks: 4}\n", "only a module with kind: program"),
        (
            "kind: program\nprogram: {weeks: 4, phases: [{name: A, weeks: [1, 3]}, "
            "{name: B, weeks: [3, 4]}]}\n",
            "phase 'B' overlaps another phase",
        ),
        (
            "kind: program\nprogram: {weeks: 4, phases: [{name: A, weeks: [1, 5]}]}\n",
            "phase 'A' ends after week 4",
        ),
        ("kind: program\nprogram: {weeks: 4, light_weeks: [5]}\n", "light weeks [5] are outside"),
        (
            "kind: program\nprogram: {weeks: 4, phases: [{name: A, weeks: [3, 2]}]}\n",
            "the first ≤ the last",
        ),
        ("kind: program\nprogram: {weeks: 4, checkpoints: {W9: 9}}\n", "checkpoints ['W9']"),
    ],
)
def test_program_block_problems(problems: Problems, head: str, message: str) -> None:
    found = problems(f"module: t\nname: T\nversion: 1\n{head}{ENTITY}")
    assert any(message in line for line in found), found


def test_run_and_week_are_the_programs_names(problems: Problems) -> None:
    text = f"module: t\nname: T\nversion: 1\nkind: program\nprogram: {{weeks: 4}}\n{ENTITY}"
    found = problems(text + "      week: {type: integer}\n")
    assert any("'week' is the program's own column" in line for line in found), found
    renamed = text.replace("  checkin:", "  runs:")
    assert any("'runs' is a reserved name" in line for line in problems(renamed))


def test_program_names_need_a_program(problems: Problems) -> None:
    text = f"module: t\nname: T\nversion: 1\nkind: journal\n{ENTITY}"
    found = problems(text + '    derived:\n      w: "program.week"\n')
    assert any("program.<name> is only valid in a module with a program:" in x for x in found)
    text = f"module: t\nname: T\nversion: 1\nkind: program\nprogram: {{weeks: 4}}\n{ENTITY}"
    found = problems(text + '    derived:\n      w: "program.weeks"\n')
    assert any("program has no 'weeks' (did you mean 'week'?)" in x for x in found), found


def test_weekbars_by_program_week_problems(problems: Problems) -> None:
    text = f"module: t\nname: T\nversion: 1\nkind: journal\n{ENTITY}"
    view = "views:\n  main:\n    - {widget: weekbars, metric: checkin.date, agg: count, "
    found = problems(text + view + "group: program_week}\n")
    assert any("program_week needs a program: block" in line for line in found), found
    found = problems(text + view + "group: program_week, split_by: checkin.date}\n")
    assert any("by program week the bars are the runs" in line for line in found), found


# ---- The workbook ----


def test_the_runs_tab(program: Module, tmp_path: Path) -> None:
    layout = workbook_layout(program)
    runs = layout.tabs[-1]
    assert runs.name == RUNS_TAB
    assert [c.key for c in runs.columns] == [
        "run",
        "start_week",
        "auto:start",
        "updated_at",
        "deleted",
    ]
    path = tmp_path / "program.xlsx"
    sync_module(program, XlsxBackend(path))
    sheet = openpyxl.load_workbook(path)[RUNS_TAB]
    rules = {str(v.sqref).split(":")[0]: v for v in sheet.data_validations.dataValidation}
    assert rules["B3"].type == "custom"
    assert rules["B3"].formula1.startswith('AND(LEN(B3)=8,MID(B3,5,2)="-W"')
    assert str(sheet["C3"].value).startswith('=IF(B3="","",IFERROR(DATE(VALUE(LEFT(B3,4)),1,4)')


def test_the_week_rule_on_google_in_a_comma_locale(program: Module) -> None:
    runs = workbook_layout(program).tabs[-1]
    spec = next(c for c in runs.columns if isinstance(c.validation, WeekRule))
    rule = google_validation(spec, 1, comma=True)
    assert rule is not None
    formula = rule["condition"]["values"][0]["userEnteredValue"]
    assert formula.startswith('=AND(LEN(B3)=8;MID(B3;5;2)="-W";')
    assert GOOGLE.fn("MAXIFS") == "MAXIFS"


def _workbook(program: Module, tmp_path: Path, runs: list[dict[str, Any]]) -> XlsxBackend:
    repo = XlsxBackend(tmp_path / "program.xlsx")
    sync_module(program, repo)
    edits = [Append(RUNS_TAB, cells) for cells in runs]
    edits += [
        Append("Checkins", {"date": dt.datetime(2026, 9, d), "minutes": 20}) for d in (1, 8, 22)
    ]
    repo.apply(edits)
    return repo


def test_runs_are_read_with_their_issues(program: Module, tmp_path: Path) -> None:
    repo = _workbook(
        program,
        tmp_path,
        [
            {"run": 1, "start_week": "2026-W37"},
            {"run": 2, "start_week": "2027-W53"},  # 2027 has 52 weeks
            {"run": 9, "start_week": "2026-W37"},  # same week as run 1
            {"start_week": "2026-W40"},  # no number
            {"run": 4, "start_week": "2026-W41", "deleted": "x"},
            {"run": 3, "start_week": "2026-W39"},
        ],
    )
    data = load_data(program, repo)
    assert [(r.number, r.start_week) for r in data.runs.runs] == [(1, "2026-W37"), (3, "2026-W39")]
    issues = {(i.tab, i.row, i.field): i.message for i in data.issues}
    assert issues[(RUNS_TAB, 4, "start_week")] == "2027 has weeks 1 to 52, not 53"
    assert "run 1 already starts that week" in issues[(RUNS_TAB, 5, "start_week")]
    assert issues[(RUNS_TAB, 6, "run")] == "a run needs its number (1, 2, …)"
    assert (
        issues[("Checkins", 3, "date")] == "dated before the first run (2026-W37): no run or week"
    )
    assert len([i for i in data.issues if i.tab == "Checkins"]) == 1


def test_no_run_yet_is_one_issue(program: Module, tmp_path: Path) -> None:
    data = load_data(program, _workbook(program, tmp_path, []))
    assert [(i.tab, i.message) for i in data.issues] == [
        (RUNS_TAB, "no run has started: type the first one's start week here (2026-W42)")
    ]


def test_runs_out_of_order_are_reported(program: Module, tmp_path: Path) -> None:
    repo = _workbook(
        program,
        tmp_path,
        [{"run": 2, "start_week": "2026-W37"}, {"run": 1, "start_week": "2026-W39"}],
    )
    messages = [i.message for i in load_data(program, repo).issues]
    assert "the runs are not numbered in the order they start" in messages


def test_a_new_run_is_written(program: Module, tmp_path: Path) -> None:
    repo = _workbook(program, tmp_path, [{"run": 1, "start_week": "2026-W37"}])
    writer = RecordWriter(program, repo, clock=lambda: dt.datetime(2026, 11, 17, 9, 0))
    run = writer.start_run(" 2026-W47 ")
    assert (run.number, run.start_week, run.start) == (2, "2026-W47", dt.date(2026, 11, 16))
    rows = repo.read_table(RUNS_TAB).rows
    assert rows[-1].cells["run"] == 2 and rows[-1].cells["start_week"] == "2026-W47"
    for week, message in [
        ("2026-W47", "a new run starts after run 2 (2026-W47)"),
        ("2027-W99", "2027 has weeks 1 to 52, not 99"),
    ]:
        with pytest.raises(WriteError, match=message.replace("(", r"\(").replace(")", r"\)")):
            writer.start_run(week)


# ---- Charts and the metric layer ----


def _rows(program: Module) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {
        "checkin": [
            {"date": dt.date(2026, 9, d), "minutes": m}
            for d, m in [(5, 99), (7, 10), (8, 20), (15, 30), (21, None)]
        ]
        + [{"date": dt.date(2026, 10, 20), "minutes": 40}],
        "exercise": [],
    }
    derived = compute_module(program, tables, {}, RUNS)
    return {
        name: [{**row, **values} for row, values in zip(rows, derived[name], strict=True)]
        for name, rows in tables.items()
    }


def test_weekbars_put_runs_side_by_side(program: Module) -> None:
    spec = {"widget": "weekbars", "metric": "checkin.minutes", "agg": "sum"}
    widget = WIDGET.validate_python(spec | {"group": "program_week"})
    [found] = compute_view(program, [widget], _rows(program), {}, dt.date(2026, 10, 31))
    assert found["grouped"] is True
    assert found["weeks"] == ["W1", "W2", "W3", "W4"]
    assert found["stacks"] == [
        {"label": "Run 1", "values": [30, 30, 0, None]},  # week 3: a record without minutes
        {"label": "Run 2", "values": [40, None, None, None]},
    ]
    counted = WIDGET.validate_python(spec | {"group": "program_week", "agg": "count"})
    [found] = compute_view(program, [counted], _rows(program), {}, dt.date(2026, 10, 31))
    assert found["stacks"][0]["values"] == [2, 1, 0, None]


def test_the_metric_layer_by_program_week(program: Module) -> None:
    sources = {"p": (program, _rows(program))}
    query = Query(["p.checkin.minutes"], group="program_week", agg="sum")
    result = run_query(query, sources, dt.date(2026, 10, 31))
    assert [p.label for p in result.points] == ["R1·W1", "R1·W2", "R1·W3", "R2·W1"]
    assert [p.start for p in result.points] == [
        W37,
        dt.date(2026, 9, 14),
        dt.date(2026, 9, 21),
        dt.date(2026, 10, 19),
    ]
    assert result.series[0].values == [30, 30, None, 40]
    with pytest.raises(QueryError, match="a lag needs points by day"):
        run_query(
            Query(["p.checkin.minutes", "p.checkin.load"], group="program_week", lag=1),
            sources,
            dt.date(2026, 10, 31),
        )


# ---- The API ----


@pytest.fixture
def client(program: Module, tmp_path: Path) -> Iterator[TestClient]:
    repo = _workbook(program, tmp_path, [{"run": 1, "start_week": "2026-W37"}])
    catalog = Catalog(AppConfig())
    cached = CachedRepository("program", repo, Snapshots(tmp_path / "snapshots"))
    catalog.entries["program"] = Entry("program", program, [], cached)
    yield TestClient(create_app(catalog=catalog))


def test_the_runs_of_a_program(client: TestClient) -> None:
    body = client.get("/api/modules/program/runs?date=2026-09-30").json()
    assert body["weeks"] == 4
    assert body["runs"] == [
        {"number": 1, "start_week": "2026-W37", "start": "2026-09-07", "end": "2026-10-04"}
    ]
    assert body["current"] == {"run": 1, "week": 4, "phase": "Peak · build", "light_week": True}
    assert body["next_week"] == "2026-W40"
    assert body["issues"] == []  # the Runs tab's own; records before run 1 are their tabs'
    assert client.get("/api/modules/program/runs?date=2026-09-01").json()["current"] is None


def test_a_run_is_started_from_the_app(client: TestClient) -> None:
    response = client.post("/api/modules/program/runs", json={"start_week": "2026-W45"})
    assert response.status_code == 201, response.text
    assert [r["number"] for r in response.json()["runs"]] == [1, 2]
    again = client.post("/api/modules/program/runs", json={"start_week": "2026-W44"})
    assert again.status_code == 422
    assert again.json()["detail"]["field"] == "start_week"
    assert "after run 2 (2026-W45)" in again.json()["detail"]["message"]
    # the records see it at once
    records = client.get("/api/modules/program/checkin").json()["records"]
    assert [r["derived"]["run"] for r in records] == [None, 1, 1]


def test_runs_of_a_module_that_is_no_program(client: TestClient) -> None:
    assert client.get("/api/modules/nothing/runs").status_code == 404
