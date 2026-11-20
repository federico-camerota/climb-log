# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001, RUF003  (prescriptions are written with ×, as in "3×10")
"""`ref` fields and reference lookups (D-113): `reference.<table>[key].<column>` and
`….<per_week>[week]` checked and computed, unknown keys as data issues and refused on write,
keys matched in any case and without spaces, the hidden helper columns and the `ref` dropdowns.
The sheet formulas are checked on LibreOffice in `test_formula_parity.py`. All fictional."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import Module, load_module
from climblog.modules.compute import compute_module
from climblog.modules.formulas import compile_formulas, default_columns
from climblog.modules.program import RUNS_TAB
from climblog.modules.reference import CHOICE_HELPER, KEY_HELPER, match_key
from climblog.storage import (
    CachedRepository,
    Snapshots,
    XlsxBackend,
    load_data,
    sync_module,
    workbook_layout,
)
from climblog.storage.base import Append
from climblog.storage.gsheets_sync import _validation as google_validation
from climblog.storage.layout import RefRule
from climblog.storage.write import RecordWriter, WriteError

DEMO = Path(__file__).parent.parent / "scripts" / "demo-program.yaml"
W37 = dt.date(2026, 9, 7)  # Monday of 2026-W37: week 1 of run 1


@pytest.fixture
def program() -> Module:
    return load_module(DEMO)


EXERCISES = [
    {"id": "A1", "name": "Wall slides", "w1": "2×10", "w2": "3×10", "w3": "Skip"},
    {"id": "A2", "name": "Band pulls", "w1": "2×8", "retired": "Yes"},
    {"id": "A9", "name": "Gone", "deleted": "x"},
]


def workbook(program: Module, tmp_path: Path) -> XlsxBackend:
    repo = XlsxBackend(tmp_path / "program.xlsx")
    sync_module(program, repo)
    edits = [Append(RUNS_TAB, {"run": 1, "start_week": "2026-W37"})]
    edits += [Append("Exercises", row) for row in EXERCISES]
    edits += [Append("Sessions", {"date": dt.datetime(2026, 9, d)}) for d in (8, 15, 22, 29)]
    repo.apply(edits)
    return repo


# ---- Expressions ----


HEAD = """\
module: t
name: T
version: 1
kind: program
program: {weeks: 4}
reference:
  items:
    tab: Items
    key: id
    fields:
      id: {type: text}
      size: {type: number}
    per_week: {name: dose}
  numbered:
    tab: Numbered
    key: n
    fields:
      n: {type: integer}
entities:
  log:
    label: Log
    tab: Log
    key: [date]
    fields:
      date: {type: date, required: true}
      item: {type: ref, reference: items}
      count: {type: integer}
    derived:
"""


@pytest.mark.parametrize(
    ("expr", "message"),
    [
        ("reference.things[item].size", "no reference table 'things' (known: items, numbered)"),
        ("reference.items[item].weight", "reference.items has no column 'weight'"),
        ("reference.items[item].dose", "dose is per week: [week]"),
        ("reference.items[item].size[2]", "has no per-week column 'size' (per week: 'dose')"),
        ("reference.items[item].dose['two']", "a week needs number, not text"),
        ("reference.items[count].size", "the key of reference.items needs text, not number"),
        ("reference.numbered[item].n", "the key of reference.numbered needs number, not text"),
        ("reference.items.size", "reference.<table>[key].<column>"),
        ("reference.items[item]", "reference.<table>[key].<column>"),
        ("count[0]", "indexing (`x[...]`) is only valid as reference.<table>[key]"),
    ],
)
def test_lookup_problems(problems: Problems, expr: str, message: str) -> None:
    found = problems(f'{HEAD}      x: "{expr}"\n')
    assert any(message in line for line in found), found


def test_display_must_be_a_field(problems: Problems) -> None:
    text = HEAD.replace("    key: id\n", "    key: id\n    display: title\n", 1)
    found = problems(f'{text}      x: "count"\n')
    assert any("the display 'title' is not one of the fields" in line for line in found), found


def test_lookups_are_computed(load: LoadYaml) -> None:
    module = load(
        HEAD
        + '      size: "reference.items[item].size"\n'
        + '      dose: "reference.items[item].dose[count]"\n'
        + '      gone: "reference.items[item].retired"\n'
    )
    reference: dict[str, list[dict[str, Value]]] = {
        "items": [
            {"id": "A1", "size": 3, "w1": "2×10", "w2": None, "retired": False},
            {"id": "B2", "size": 5, "w1": "1", "retired": True},
        ]
    }
    rows: list[dict[str, Value]] = [
        {"date": dt.date(2026, 9, 1), "item": "a1 ", "count": 1},  # any case, spaces around
        {"date": dt.date(2026, 9, 2), "item": "A1", "count": 2},  # a blank week cell
        {"date": dt.date(2026, 9, 3), "item": "B2", "count": 1},  # retired: still read
        {"date": dt.date(2026, 9, 4), "item": "ZZ", "count": 1},  # no such row
        {"date": dt.date(2026, 9, 5), "item": None, "count": 1},
        {"date": dt.date(2026, 9, 6), "item": "A1", "count": 9},  # past the last week
        {"date": dt.date(2026, 9, 7), "item": "A1", "count": None},
    ]
    found = compute_module(module, {"log": rows}, {}, reference=reference)["log"]
    assert [(r["size"], r["dose"], r["gone"]) for r in found] == [
        (3, "2×10", False),
        (3, None, False),
        (5, "1", True),
        (None, None, None),
        (None, None, None),
        (3, None, False),
        (3, None, False),
    ]


def test_keys_match_in_any_case_without_spaces() -> None:
    assert match_key(" a3 ") == match_key("A3") == "a3"
    assert match_key("  ") is None
    assert match_key(7) == 7


# ---- The workbook ----


def test_helper_columns_and_dropdowns(program: Module, tmp_path: Path) -> None:
    columns = default_columns(program)
    formulas = compile_formulas(program, columns)
    key = formulas[("Exercises", KEY_HELPER)].at(3)
    assert key == '=IF(OR(A3="",O3<>""),"",TRIM(A3))'  # O: deleted
    offered = formulas[("Exercises", CHOICE_HELPER)].at(3)
    assert offered.startswith('=IF(OR(L3="",OR(K3="yes"')  # L: auto:key; K: retired
    tabs = {tab.name: tab for tab in workbook_layout(program).tabs}
    log = {c.key: c for c in tabs["Exercise log"].columns}
    assert log["exercise"].validation == RefRule("Exercises")

    repo = XlsxBackend(tmp_path / "program.xlsx")
    sync_module(program, repo)
    sheet = openpyxl.load_workbook(repo.path)["Exercise log"]
    rules = {str(v.sqref).split(":")[0]: v for v in sheet.data_validations.dataValidation}
    assert rules["B3"].type == "list"
    assert rules["B3"].formula1 == "Exercises!$M$3:$M$2000"  # M: auto:choice
    assert rules["B3"].errorStyle == "warning"  # a retired key typed by hand stays


def test_the_dropdown_on_google(program: Module) -> None:
    log = next(t for t in workbook_layout(program).tabs if t.name == "Exercise log")
    spec = next(c for c in log.columns if c.key == "exercise")
    rule = google_validation(spec, 1, True, lambda tab, key: "M" if tab == "Exercises" else None)
    assert rule == {
        "condition": {
            "type": "ONE_OF_RANGE",
            "values": [{"userEnteredValue": "=Exercises!$M$3:$M"}],
        },
        "strict": False,
        "showCustomUi": True,
    }
    assert google_validation(spec, 1, True) is None  # the tab isn't there yet


# ---- Reading and writing ----


def test_unknown_refs_are_issues(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    repo.apply(
        [
            Append("Exercise log", {"date": dt.datetime(2026, 9, 8), "exercise": " a1"}),
            Append("Exercise log", {"date": dt.datetime(2026, 9, 15), "exercise": "A2"}),
            Append("Exercise log", {"date": dt.datetime(2026, 9, 22), "exercise": "A9"}),
            Append("Exercise log", {"date": dt.datetime(2026, 9, 29), "exercise": "ZZ"}),
        ]
    )
    data = load_data(program, repo)
    issues = [(i.row, i.field, i.message) for i in data.issues if i.tab == "Exercise log"]
    assert issues == [
        (5, "exercise", "'A9' is not a row of Exercises"),  # deleted
        (6, "exercise", "'ZZ' is not a row of Exercises"),
    ]
    records = data.entities["exercise_log"].records
    assert [r["exercise"] for r in records] == ["a1", "A2", None, None]  # trimmed, as typed
    tables = {name: e.records for name, e in data.entities.items()}
    derived = compute_module(program, tables, data.settings, data.runs, data.reference_rows())
    found = [(d["name"], d["prescribed"], d["skipped_by_plan"]) for d in derived["exercise_log"]]
    assert found == [
        ("Wall slides", "2×10", False),  # 8 Sep: week 1 of run 1
        ("Band pulls", None, False),  # retired, still read; no week-2 prescription
        (None, None, False),
        (None, None, False),
    ]


def test_ref_values_on_write(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    write = RecordWriter(program, repo)
    write.add("exercise_log", {"date": "2026-09-08", "exercise": "a1 "})
    rows = repo.read_table("Exercise log").rows
    assert rows[-1].cells["exercise"] == "A1"  # as the table spells it
    write.add("exercise_log", {"date": "2026-09-15", "exercise": "A2"})  # retired: allowed
    with pytest.raises(WriteError, match="exercise: 'ZZ' is not a row of Exercises"):
        write.add("exercise_log", {"date": "2026-09-22", "exercise": "ZZ"})
    with pytest.raises(WriteError, match="'A9' is not a row of Exercises"):  # deleted
        write.add("exercise_log", {"date": "2026-09-22", "exercise": "A9"})


def test_ref_columns_in_reference_tables(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    write = RecordWriter(program, repo)
    write.add_reference_row("tracks", {"id": "T1", "name": "Balance"})
    write.add_reference_row("drills", {"id": "D1", "track": "t1"})
    assert repo.read_table("Drills").rows[0].cells["track"] == "T1"
    with pytest.raises(WriteError, match="'T9' is not a row of Tracks"):
        write.add_reference_row("drills", {"id": "D2", "track": "T9"})
    repo.apply([Append("Drills", {"id": "D3", "track": "T9"})])  # typed by hand
    issues = [(i.tab, i.field, i.message) for i in load_data(program, repo).issues]
    assert ("Drills", "track", "'T9' is not a row of Tracks") in issues


def test_reference_keys_match_in_any_case(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    repo.apply([Append("Exercises", {"id": "a1", "name": "Again"})])
    data = load_data(program, repo)
    assert [r["id"] for r in data.reference["exercises"].rows] == ["A1", "A2"]
    assert any("same id as row 3" in i.message for i in data.issues)
    with pytest.raises(WriteError, match="already there"):
        RecordWriter(program, repo).add_reference_row("exercises", {"id": " A1", "name": "x"})


# ---- The API ----


@pytest.fixture
def client(program: Module, tmp_path: Path) -> Iterator[TestClient]:
    repo = workbook(program, tmp_path)
    catalog = Catalog(AppConfig())
    cached = CachedRepository("program", repo, Snapshots(tmp_path / "snapshots"))
    catalog.entries["program"] = Entry("program", program, [], cached)
    yield TestClient(create_app(catalog=catalog))


def test_lookups_through_the_api(client: TestClient) -> None:
    url = "/api/modules/program/exercise_log"
    added = client.post(url, json={"values": {"date": "2026-09-15", "exercise": "a1"}})
    assert added.status_code == 201, added.text
    record: dict[str, Any] = added.json()["record"]
    assert record["values"]["exercise"] == "A1"
    assert record["derived"] == {
        "run": 1,
        "week": 2,
        "name": "Wall slides",
        "prescribed": "3×10",
        "skipped_by_plan": False,
    }
    bad = client.post(url, json={"values": {"date": "2026-09-22", "exercise": "ZZ"}})
    assert bad.status_code == 422
    assert bad.json()["detail"]["field"] == "exercise"
    table = client.get("/api/modules/program/reference/exercises").json()["table"]
    assert table["display"] == "name"
