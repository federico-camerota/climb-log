# SPDX-License-Identifier: GPL-3.0-or-later
"""The training plan (D-110): records dated by a week typed as 2026-W47, the module, this week's
plan on Today, a dashboard table that looks ahead, and the API. The sheet formulas of week-dated
records are checked on LibreOffice in `test_formula_parity.py`. Fictional data only."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import openpyxl
import pytest
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient

from climblog.analytics import compute_view
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.modules.forms import due
from climblog.modules.formulas import formula_columns
from climblog.modules.schema import DateField
from climblog.storage import CachedRepository, Snapshots, XlsxBackend, load_data, sync_module
from climblog.storage.cells import CellError, parse_cell
from climblog.storage.layout import WeekRule, workbook_layout
from climblog.storage.write import RecordWriter, WriteError

ROOT = Path(__file__).parent.parent
PLAN = load_module(ROOT / "modules" / "training-plan.yaml")
WEDNESDAY = dt.date(2026, 11, 18)  # in 2026-W47 (Monday 16 November)
W47 = dt.date(2026, 11, 16)
WEEK = DateField(type="week")


# ---- Week cells ----


@pytest.mark.parametrize(
    ("raw", "monday"),
    [
        ("2026-W47", W47),
        (" 2026-W47 ", W47),
        (dt.datetime(2026, 11, 19), W47),  # a date typed instead: its week
        (dt.date(2026, 11, 22), W47),  # a Sunday is still that week
    ],
)
def test_a_week_cell_is_its_monday(raw: object, monday: dt.date) -> None:
    assert parse_cell(PLAN, WEEK, raw) == monday  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "message"),
    [("2026-W5x", "is not a week like"), ("2027-W53", "2027 has weeks 1 to 52, not 53")],
)
def test_a_bad_week_cell(raw: str, message: str) -> None:
    with pytest.raises(CellError, match=message):
        parse_cell(PLAN, WEEK, raw)


def test_a_week_can_date_a_record(problems: Problems, load: LoadYaml) -> None:
    head = (
        "module: t\nname: T\nversion: 1\nkind: journal\nentities:\n  e:\n    label: E\n    tab: E\n"
    )
    module = load(head + "    date_field: w\n    key: [w]\n    fields:\n      w: {type: week}\n")
    assert module.entities["e"].date_field == "w"
    text = head + "    date_field: n\n    key: [n]\n    fields:\n      n: {type: text}\n"
    assert any("must be a field of type date, datetime or week" in x for x in problems(text))


# ---- The module ----


def test_the_plan_module() -> None:
    planned = PLAN.entities["planned"]
    assert (planned.date_field, planned.key) == ("week_of", ["week_of", "item"])
    _, app_only = formula_columns(PLAN)
    assert app_only == []
    tab = workbook_layout(PLAN).tabs[0]
    week = next(c for c in tab.columns if c.key == "week_of")
    assert (week.number_format, week.validation) == ("@", WeekRule())


def test_the_plan_can_be_a_program(tmp_path: Path) -> None:
    """With a `program:` block a plan gets each session's run and program week (D-109)."""
    text = (ROOT / "modules" / "training-plan.yaml").read_text(encoding="utf-8")
    text = text.replace("kind: journal", "kind: program\nprogram: {weeks: 12}")
    file = tmp_path / "plan.yaml"
    file.write_text(text, encoding="utf-8")
    module = load_module(file)
    assert list(module.entities["planned"].derived) == ["run", "week"]
    assert formula_columns(module)[1] == []


# ---- Today ----


def planned(
    week: dt.date, item: int, day: str | None, kind: str, what: str | None = None
) -> dict[str, Value]:
    return {"week_of": week, "item": item, "day": day, "type": kind, "description": what}


def test_this_weeks_plan_today_first() -> None:
    rows = [
        planned(W47, 1, "Mon", "Climbing", "Limit bouldering"),
        planned(W47, 2, None, "Hangboard"),
        planned(W47, 3, "Wed", "Shoulder A"),
        planned(W47, 4, "Sat", "Fear outdoor 1", "Lead, short falls"),
        planned(W47 - dt.timedelta(weeks=1), 1, "Wed", "Rest"),  # last week
        planned(W47 + dt.timedelta(weeks=1), 1, "Wed", "Climbing"),  # next week
    ]
    day = due(PLAN, {"planned": rows}, WEDNESDAY)
    assert day.items == []  # a plan is never due
    assert (day.plan_form, day.plan_week, day.plan_field) == ("plan", "2026-W47", "week_of")
    assert [(p.line, p.today) for p in day.plan] == [
        ("Wed · Shoulder A", True),
        ("Mon · Climbing · Limit bouldering", False),
        ("Sat · Fear outdoor 1 · Lead, short falls", False),
        ("Any day · Hangboard", False),
    ]
    assert day.plan[0].key == {"week_of": "2026-W47", "item": 3}


def test_an_empty_week() -> None:
    day = due(PLAN, {"planned": []}, WEDNESDAY)
    assert (day.plan, day.plan_week) == ([], "2026-W47")


# ---- The dashboard ----


def test_the_table_looks_ahead_oldest_first() -> None:
    rows = [
        planned(W47 - dt.timedelta(weeks=1), 1, "Tue", "Rest"),
        planned(W47, 1, "Mon", "Climbing"),
        planned(W47 + dt.timedelta(weeks=2), 1, "Fri", "Strength"),
        planned(W47 + dt.timedelta(weeks=4), 1, None, "Hangboard"),
        planned(W47 + dt.timedelta(weeks=5), 1, None, "Rest"),  # beyond the four weeks
    ]
    widget = (PLAN.views or {})["overview"][0]  # this week and the next four
    [found] = compute_view(PLAN, [widget], {"planned": rows}, {}, WEDNESDAY)
    assert [(r["week_of"], r["type"]) for r in found["rows"]] == [
        ("2026-W47", "Climbing"),
        ("2026-W49", "Strength"),
        ("2026-W51", "Hangboard"),
    ]


# ---- Writing and the API ----


@pytest.fixture
def repo(tmp_path: Path) -> XlsxBackend:
    made = XlsxBackend(tmp_path / "plan.xlsx")
    sync_module(PLAN, made)
    return made


def test_a_planned_session_is_written_as_its_week(repo: XlsxBackend, tmp_path: Path) -> None:
    writer = RecordWriter(PLAN, repo)
    writer.add("planned", {"week_of": "2026-W47", "type": "Climbing", "day": "Tue"})
    writer.add("planned", {"week_of": "2026-W47", "type": "Rest"})
    sheet = openpyxl.load_workbook(tmp_path / "plan.xlsx")["Plan"]
    assert [sheet.cell(row, 1).value for row in (3, 4)] == ["2026-W47", "2026-W47"]
    records = load_data(PLAN, repo).entities["planned"].records
    assert [(r["week_of"], r["item"]) for r in records] == [(W47, 1), (W47, 2)]
    with pytest.raises(WriteError, match="is not a week like"):
        writer.add("planned", {"week_of": "next week", "type": "Rest"})


@pytest.fixture
def client(repo: XlsxBackend, tmp_path: Path) -> Iterator[TestClient]:
    catalog = Catalog(AppConfig())
    cached = CachedRepository("training_plan", repo, Snapshots(tmp_path / "snapshots"))
    catalog.entries["training_plan"] = Entry("training_plan", PLAN, [], cached)
    yield TestClient(create_app(catalog=catalog))


def test_the_api_speaks_weeks(client: TestClient) -> None:
    url = "/api/modules/training_plan/planned"
    for values in (
        {"week_of": "2026-W47", "type": "Climbing", "day": "Wed"},
        {"week_of": "2026-W47", "type": "Hangboard"},
    ):
        response = client.post(url, json={"values": values})
        assert response.status_code == 201, response.text
    record = response.json()["record"]["values"]
    assert (record["week_of"], record["item"]) == ("2026-W47", 2)
    again = client.get(f"{url}/record?week_of=2026-W47&item=1").json()["record"]["values"]
    assert (again["week_of"], again["type"]) == ("2026-W47", "Climbing")
    today = client.get("/api/today?date=2026-11-18").json()["modules"][0]
    assert today["items"] == []
    assert [(p["line"], p["today"]) for p in today["plan"]] == [
        ("Wed · Climbing", True),
        ("Any day · Hangboard", False),
    ]
    assert (today["plan_form"], today["plan_week"], today["plan_field"]) == (
        "plan",
        "2026-W47",
        "week_of",
    )
