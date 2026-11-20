# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001, RUF003  (prescriptions are written with ×, as in "3×10")
"""Reference tables (03-module-framework.md §2.5, D-112): the `reference:` block and its checks,
each table's tab in the workbook (on every backend), its rows with their data issues, adding and
changing rows (retiring one included) and the API. All on the fictional demo program."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from backends import Backend
from conftest import Problems
from fastapi.testclient import TestClient

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.main import create_app
from climblog.modules import Module, load_module
from climblog.modules.reference import RETIRED, reference_columns
from climblog.storage import (
    CachedRepository,
    Repository,
    Snapshots,
    XlsxBackend,
    check_schema,
    load_data,
    sync_module,
    workbook_layout,
)
from climblog.storage.base import Append, WriteConflict
from climblog.storage.layout import ListRule, RangeRule, RefRule
from climblog.storage.write import KeyTaken, RecordNotFound, RecordWriter, WriteError

CONTRACT = "sync"  # the round trip runs on every backend
DEMO = Path(__file__).parent.parent / "scripts" / "demo-program.yaml"
WEEKS = [f"w{n}" for n in range(1, 7)]
NOW = dt.datetime(2026, 11, 20, 9, 30)


@pytest.fixture
def program() -> Module:
    return load_module(DEMO)


def workbook(program: Module, tmp_path: Path) -> XlsxBackend:
    repo = XlsxBackend(tmp_path / "program.xlsx")
    sync_module(program, repo)
    return repo


def writer(program: Module, repo: Repository) -> RecordWriter:
    return RecordWriter(program, repo, clock=lambda: NOW)


# ---- The module file ----


def test_the_tables_of_a_module(program: Module) -> None:
    tables = program.reference or {}
    assert list(tables) == ["exercises", "tracks", "measures", "drills"]
    assert list(reference_columns(program, "exercises")) == [
        "id",
        "name",
        "session",
        "load_rule",
        *WEEKS,  # the program's six weeks
        RETIRED,
    ]
    assert list(reference_columns(program, "tracks")) == ["id", "name", RETIRED]


HEAD = "module: t\nname: T\nversion: 1\nkind: program\nprogram: {weeks: 3}\n"
ENTITY = """\
entities:
  checkin:
    label: Check-in
    tab: Checkins
    key: [date]
    fields:
      date: {type: date, required: true}
"""


def table(fields: str, extra: str = "", tab: str = "Items", key: str = "id") -> str:
    return (
        f"reference:\n  items:\n    tab: {tab}\n    key: {key}\n{extra}"
        f"    fields:\n      id: {{type: text}}\n{fields}"
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (table("      day: {type: date}\n"), "fields are text, choice, number, bool or ref"),
        (table("      n: {type: scale, scale: s}\n"), "fields are text, choice, number, bool or"),
        (table("", key="code"), "the key 'code' is not one of the fields"),
        (table("      on: {type: bool}\n", key="on"), "the key must be a text or integer field"),
        (table("      retired: {type: bool}\n"), "'retired' is a column the app adds"),
        (table("      deleted: {type: text}\n"), "'deleted' is a column the app adds"),
        (
            table("      w2: {type: text}\n", "    per_week: {name: dose}\n"),
            "'w2' is a per-week column's name",
        ),
        (table("      t: {type: ref, reference: other}\n"), "unknown reference table 'other'"),
        (table("      t: {type: ref, reference: items}\n"), "a table can't refer to itself"),
        (table("      t: {type: text, section: a}\n"), "a reference field has no `section`"),
        (table("      t: {type: text, since: 2026-01-01}\n"), "a reference field has no `since`"),
        (table("      t: {type: text, phase: pre}\n"), "has no phase and is never optional"),
        (table("", tab="Checkins"), "tab 'Checkins' is already used by 'checkin'"),
        (table("", tab="Runs"), "'Runs' is a tab the app manages itself"),
        (table("", "    colour: red\n"), "reference.items.colour: unknown key"),
    ],
)
def test_reference_problems(problems: Problems, text: str, message: str) -> None:
    found = problems(HEAD + text + ENTITY)
    assert any(message in line for line in found), found


def test_per_week_needs_a_program(problems: Problems) -> None:
    head = HEAD.replace("kind: program\nprogram: {weeks: 3}\n", "kind: journal\n")
    found = problems(head + table("", "    per_week: {name: dose}\n") + ENTITY)
    assert any("per_week columns need a program: block" in line for line in found), found


def test_reference_is_a_reserved_entity_name(problems: Problems) -> None:
    found = problems(HEAD + ENTITY.replace("  checkin:", "  reference:"))
    assert any("'reference' is a reserved name" in line for line in found), found


def test_a_journal_can_have_tables(tmp_path: Path) -> None:
    file = tmp_path / "t.yaml"
    head = HEAD.replace("kind: program\nprogram: {weeks: 3}\n", "kind: journal\n")
    file.write_text(head + table("      grams: {type: number, min: 0}\n") + ENTITY)
    module = load_module(file)
    assert list(reference_columns(module, "items")) == ["id", "grams", RETIRED]


# ---- The workbook ----


def test_the_tab_of_a_table(program: Module) -> None:
    tabs = {tab.name: tab for tab in workbook_layout(program).tabs}
    assert [t for t in tabs if t in ("Exercises", "Tracks", "Drills")] == [
        "Exercises",
        "Tracks",
        "Drills",
    ]
    columns = {c.key: c for c in tabs["Exercises"].columns}
    assert list(columns) == [
        "id",
        "name",
        "session",
        "load_rule",
        *WEEKS,
        RETIRED,
        "auto:key",  # hidden: lookups and dropdowns (D-113)
        "auto:choice",
        "updated_at",
        "deleted",
    ]
    assert columns["id"].group == "key"
    assert {columns[k].group for k in ("name", "session", "w1", RETIRED)} == {"reference"}
    assert columns["w1"].label == "W1\nPrescription"
    assert columns["w1"].number_format == "@"  # typed as text: "3×10"
    assert columns["session"].validation == ListRule(("Warm-up", "A", "B"))
    assert columns[RETIRED].validation == ListRule(("Yes", "No"))
    drills = {c.key: c for c in tabs["Drills"].columns}
    assert drills["order"].validation == RangeRule("whole", 1, None)
    assert drills["track"].validation == RefRule("Tracks")  # the tracks still offered
    formulas = [c.key for c in tabs["Exercises"].columns if c.formula]
    assert formulas == ["auto:key", "auto:choice"]
    assert all(columns[k].hidden for k in formulas)


def test_a_table_round_trip(program: Module, backend: Backend) -> None:
    """Sync creates the tab; rows typed by hand and from the app read back the same."""
    repo = backend.new()
    sync_module(program, repo)
    assert check_schema(program, repo) == []
    labels, keys = backend.cells(repo, "Tracks")[:2]
    assert list(keys[:7]) == [
        "id",
        "name",
        RETIRED,
        "auto:key",
        "auto:choice",
        "updated_at",
        "deleted",
    ]
    assert labels[0] == "Id"
    repo.apply([Append("Tracks", {"id": "T1", "name": "Balance"})])  # typed in the sheet
    writer(program, repo).add_reference_row("tracks", {"id": "T2", "name": "Reach"})
    backend.edit(repo, "Tracks", "C3", "Yes")  # retired by hand
    data = load_data(program, repo)
    rows = data.reference["tracks"].rows
    assert [(r["id"], r["name"], r[RETIRED]) for r in rows] == [
        ("T1", "Balance", True),
        ("T2", "Reach", False),
    ]
    assert data.reference["tracks"].places == [3, 4]


def test_rows_with_their_issues(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    repo.apply(
        [
            Append("Exercises", {"id": "A1", "name": "Wall slides", "session": "A", "w1": "3×10"}),
            Append("Exercises", {"id": "A1", "name": "Again"}),  # the same key
            Append("Exercises", {"name": "No key"}),
            Append("Exercises", {"id": "A2", "session": "C", RETIRED: "maybe"}),
            Append("Exercises", {"id": "A3", "name": "Gone", "deleted": "x"}),
            Append("Tracks", {"id": "T1", "name": "Balance"}),
            Append("Drills", {"id": "D1", "track": " T1 ", "order": 2}),
        ]
    )
    data = load_data(program, repo)
    rows = data.reference["exercises"].rows
    assert [r["id"] for r in rows] == ["A1", "A2"]
    assert rows[0]["w1"] == "3×10" and rows[0]["w2"] is None and rows[0][RETIRED] is False
    assert rows[1][RETIRED] is False  # unreadable: an issue, not retired
    issues = {(i.tab, i.row, i.field): (i.kind, i.message) for i in data.issues}
    assert issues[("Exercises", 4, None)] == ("left_out", "same id as row 3: the row is left out")
    assert issues[("Exercises", 5, "id")] == ("left_out", "no id: the row is left out")
    assert issues[("Exercises", 6, "session")] == ("value", "'C' is not one of: Warm-up, A, B")
    assert issues[("Exercises", 6, RETIRED)][0] == "value"
    assert issues[("Exercises", 6, "name")] == ("required", "required, but empty")
    assert not [i for i in data.issues if i.tab == "Drills"]
    assert data.reference["drills"].rows[0]["track"] == "T1"  # trimmed
    assert data.reference["drills"].find("D1") == 0


def test_a_missing_tab_and_column(program: Module, tmp_path: Path) -> None:
    repo = XlsxBackend(tmp_path / "old.xlsx")
    sync_module(program, repo)
    book = __import__("openpyxl").load_workbook(repo.path)
    del book["Drills"]
    book["Tracks"].delete_cols(2)  # name
    book.save(repo.path)
    data = load_data(program, XlsxBackend(repo.path))
    found = {(i.tab, i.field, i.kind) for i in data.issues}
    assert ("Drills", None, "tab") in found
    assert ("Tracks", "name", "column") in found
    assert data.reference["drills"].rows == []


# ---- Writing ----


def test_adding_and_changing_rows(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    write = writer(program, repo)
    key = write.add_reference_row("exercises", {"id": " B1 ", "name": "Squats", "w2": "3×8"})
    assert key == "B1"
    write.update_reference_row("exercises", "B1", {"w2": None, "w3": "Skip", RETIRED: True})
    rows = repo.read_table("Exercises").rows
    assert rows[0].cells["w3"] == "Skip" and "w2" not in rows[0].cells
    assert rows[0].cells[RETIRED] == "Yes"
    assert rows[0].cells["updated_at"] == NOW
    row = load_data(program, repo).reference["exercises"].rows[0]
    assert (row["id"], row["w3"], row[RETIRED]) == ("B1", "Skip", True)


def test_write_problems(program: Module, tmp_path: Path) -> None:
    repo = workbook(program, tmp_path)
    write = writer(program, repo)
    write.add_reference_row("tracks", {"id": "T1", "name": "Balance"})
    repo.apply([Append("Tracks", {"id": "T2"}), Append("Tracks", {"id": "T2", "name": "x"})])
    with pytest.raises(KeyTaken, match="Tracks: T1 is already there"):
        write.add_reference_row("tracks", {"id": "T1", "name": "Again"})
    with pytest.raises(KeyTaken):  # a left-out row has it: a new one would be left out too
        write.add_reference_row("tracks", {"id": "T2", "name": "Again"})
    with pytest.raises(WriteError, match="no id: a row needs one"):
        write.add_reference_row("tracks", {"name": "No key"})
    with pytest.raises(WriteError, match="tracks has no column colour") as error:
        write.add_reference_row("tracks", {"id": "T3", "colour": "red", "name": 5})
    assert [f for f, _ in error.value.problems] == ["colour"]
    with pytest.raises(WriteError, match="id can't be changed"):
        write.update_reference_row("tracks", "T1", {"id": "T9"})
    with pytest.raises(RecordNotFound, match="no row 'T9' in Tracks"):
        write.update_reference_row("tracks", "T9", {"name": "x"})
    with pytest.raises(WriteError, match="no reference table 'nothing'"):
        write.add_reference_row("nothing", {"id": "x"})
    with pytest.raises(WriteConflict, match="name has changed since it was read"):
        write.update_reference_row("tracks", "T1", {"name": "New"}, {"name": "Old"})
    with pytest.raises(WriteError, match="'C' is not one of: Warm-up, A, B"):
        write.add_reference_row("exercises", {"id": "A1", "name": "x", "session": "C"})


# ---- The API ----


@pytest.fixture
def client(program: Module, tmp_path: Path) -> Iterator[TestClient]:
    repo = workbook(program, tmp_path)
    repo.apply([Append("Tracks", {"id": "T1", "name": "Balance"}), Append("Tracks", {"id": ""})])
    repo.apply([Append("Tracks", {"name": "No key"})])
    catalog = Catalog(AppConfig())
    cached = CachedRepository("program", repo, Snapshots(tmp_path / "snapshots"))
    catalog.entries["program"] = Entry("program", program, [], cached)
    yield TestClient(create_app(catalog=catalog))


def test_the_tables_of_a_module_in_the_api(client: TestClient) -> None:
    body = client.get("/api/modules/program/reference").json()
    exercises, tracks, _, _ = body["tables"]
    assert exercises == {
        "name": "exercises",
        "label": "Exercises",
        "tab": "Exercises",
        "key": "id",
        "display": "name",
        "columns": ["id", "name", "session", "load_rule", *WEEKS, RETIRED],
        "week_columns": WEEKS,
        "per_week_label": "Prescription",
    }
    assert tracks["week_columns"] == [] and tracks["per_week_label"] is None


def test_rows_in_the_api(client: TestClient) -> None:
    body = client.get("/api/modules/program/reference/tracks").json()
    assert body["rows"] == [{"values": {"id": "T1", "name": "Balance", RETIRED: False}, "row": 3}]
    assert [(i["row"], i["kind"]) for i in body["issues"]] == [(4, "left_out")]
    assert body["offline"] is False


def test_writing_rows_from_the_app(client: TestClient) -> None:
    url = "/api/modules/program/reference/tracks"
    added = client.post(url, json={"values": {"id": "T2", "name": "Reach"}})
    assert added.status_code == 201, added.text
    assert [r["values"]["id"] for r in added.json()["rows"]] == ["T1", "T2"]
    again = client.post(url, json={"values": {"id": "T2", "name": "Reach"}})
    assert again.status_code == 409
    retired = client.patch(f"{url}/row?key=T1", json={"values": {RETIRED: True}})
    assert retired.status_code == 200, retired.text
    assert retired.json()["rows"][0]["values"][RETIRED] is True
    renamed = client.patch(f"{url}/row?key=T1", json={"values": {"id": "T5"}})
    assert renamed.status_code == 422
    assert renamed.json()["detail"]["field"] == "id"
    stale = client.patch(
        f"{url}/row?key=T2", json={"values": {"name": "B"}, "expected": {"name": "A"}}
    )
    assert stale.status_code == 409
    gone = client.patch(f"{url}/row?key=T9", json={"values": {"name": "B"}})
    assert gone.status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "/api/modules/nothing/reference",
        "/api/modules/program/reference/nothing",
    ],
)
def test_unknown_modules_and_tables(client: TestClient, url: str) -> None:
    assert client.get(url).status_code == 404


def test_entities_still_answer(client: TestClient) -> None:
    body: dict[str, Any] = client.get("/api/modules/program/session").json()
    assert body["records"] == []
