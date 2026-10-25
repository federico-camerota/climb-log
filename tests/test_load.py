# SPDX-License-Identifier: GPL-3.0-or-later
"""Loading records from a workbook: keys, defaults, joins, data issues (04 §1, §4, D-048)."""

import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from conftest import LoadYaml
from workbooks import tab, write_workbook

from climblog.modules import Module
from climblog.modules.compute import compute_module
from climblog.storage import (
    DataIssue,
    Edit,
    RawCell,
    SheetRow,
    Table,
    TableNotFound,
    XlsxBackend,
    load_data,
)

# A fictional module: a session split over two tabs, its sets, and falls with generated ids.
MODULE = """\
module: test_load
name: Test load
version: 1
kind: journal
settings:
  low_max: {type: number, default: 4}
  start: {type: date, default: 2026-10-01}
  motto: {type: text, default: Keep going}
scales:
  s10: {min: 1, max: 10, direction: higher_better}
entities:
  session:
    label: Session
    key: [date, session_no]
    anchor_tab: Session
    sections:
      info: {label: Info, tab: Session}
      wb: {label: Wellbeing, tab: Wellbeing}
    fields:
      date: {type: date, required: true, section: "*"}
      session_no: {type: integer, min: 1, default: 1, section: "*"}
      kind: {type: choice, choices: [Climb, Board], section: info}
      mood: {type: scale, scale: s10, required: true, section: wb}
      route: {type: text, required: true, visible_if: "kind == 'Climb'", section: wb}
    derived:
      low_mood: "mood <= settings.low_max"
  set:
    label: Set
    tab: Sets
    key: [date, session_no, set_no]
    parent: {entity: session, key: [date, session_no]}
    fields:
      date: {type: date}
      session_no: {type: integer, default: 1}
      set_no: {type: integer, default: next}
      kg: {type: number}
      completed: {type: bool, default: true}
  fall:
    label: Fall
    tab: Falls
    id_prefix: fall
    fields:
      id: {type: text}
      date: {type: date}
      height_m: {type: number}
"""

D20, D21, D22 = dt.datetime(2026, 10, 20), dt.datetime(2026, 10, 21), dt.datetime(2026, 10, 22)
SESSION = ["date", "session_no", "kind", "auto:status", "updated_at", "deleted"]
WELLBEING = ["date", "session_no", "mood", "route"]
SETS = ["date", "session_no", "set_no", "kg", "completed"]
FALLS = ["id", "date", "height_m", "auto:week"]


class Memory:
    """A `Repository` over tabs written as in `workbooks.tab` (labels, keys, rows)."""

    def __init__(self, tabs: Mapping[str, Sequence[Sequence[Any]]]) -> None:
        self.tabs = tabs

    def list_tables(self) -> list[str]:
        return list(self.tabs)

    def read_table(self, name: str) -> Table:
        if name not in self.tabs:
            raise TableNotFound(name)
        _, keys, *rows = self.tabs[name]
        data = []
        for number, row in enumerate(rows, start=3):
            cells = {k: v for k, v in zip(keys, row, strict=False) if v not in (None, "")}
            if cells:
                data.append(SheetRow(number, cells))
        return Table(name, tuple(keys), tuple(data))

    def read_kv(self, name: str) -> dict[str, RawCell]:
        if name not in self.tabs:
            raise TableNotFound(name)
        return {row[0]: row[1] for row in self.tabs[name][1:]}

    def last_modified(self) -> dt.datetime:
        return dt.datetime(2026, 10, 24)

    def apply(self, edits: Sequence[Edit]) -> list[int]:
        raise NotImplementedError("read-only")

    def write_kv(self, name: str, values: Mapping[str, RawCell]) -> None:
        raise NotImplementedError("read-only")


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


def tabs(**changes: Sequence[Sequence[Any]]) -> dict[str, Sequence[Sequence[Any]]]:
    """A clean workbook for MODULE, with some tabs replaced."""
    base: dict[str, Sequence[Sequence[Any]]] = {
        "Session": tab(SESSION, [D20, None, "Climb"], [D21, 2, "Board"]),
        "Wellbeing": tab(WELLBEING, [D21, 2, 7], [D20, 1, 8, "Via Lattea"]),
        "Sets": tab(SETS, [D20, None, 1, 10], [D20, 1, 2, 12.5, "no"]),
        "Falls": tab(FALLS, [None, D22, 3], [None, None, None, "W1"]),
        "_settings": [["key", "value"], ["low_max", 5]],
    }
    return base | changes


def issues_of(module: Module, workbook: Mapping[str, Sequence[Sequence[Any]]]) -> list[str]:
    return [_line(i) for i in load_data(module, Memory(workbook)).issues]


def _line(issue: DataIssue) -> str:
    return f"{issue.tab}:{issue.row}:{issue.field}: {issue.message}"


def test_a_clean_workbook(module: Module) -> None:
    data = load_data(module, Memory(tabs()))
    assert data.issues == []
    session = data.entities["session"]
    assert session.records == [  # joined on the key; a blank session_no is its default 1
        {"date": dt.date(2026, 10, 20), "session_no": 1, "kind": "Climb", "mood": 8,
         "route": "Via Lattea"},
        {"date": dt.date(2026, 10, 21), "session_no": 2, "kind": "Board", "mood": 7,
         "route": None},
    ]  # fmt: skip
    assert session.places == [{"Session": 3, "Wellbeing": 4}, {"Session": 4, "Wellbeing": 3}]
    sets = data.entities["set"].records
    assert [(s["session_no"], s["kg"], s["completed"]) for s in sets] == [
        (1, 10, True),  # blank completed: its default
        (1, 12.5, False),
    ]
    falls = data.entities["fall"]
    assert falls.records == [{"id": None, "date": dt.date(2026, 10, 22), "height_m": 3}]
    assert falls.places == [{"Falls": 3}]  # the row with only a formula value is not a record
    assert data.settings == {"low_max": 5, "start": dt.date(2026, 10, 1), "motto": "Keep going"}


def test_rows_without_a_key(module: Module) -> None:
    session = tab(
        SESSION,
        [D20, None, "Climb"],
        [None, None, None, "GOOD"],  # the pre-filled formula buffer: ignored
        [None, 2, "Board"],  # data but no date
        ["yesterday", None, "Board"],  # a bad date: one issue, not two
    )
    assert issues_of(module, tabs(Session=session)) == [
        "Session:5:date: no date: the row is left out",
        "Session:6:date: 'yesterday' is not a date (e.g. 2026-10-24 or 24/10/2026)",
        "Wellbeing:3:None: no Session row for date 2026-10-21, session_no 2",
    ]


def test_duplicate_keys_keep_the_upper_row(module: Module) -> None:
    session = tab(SESSION, [D20, None, "Climb"], [D20, 1, "Board"], [D21, 2, "Board"])
    data = load_data(module, Memory(tabs(Session=session)))
    assert [_line(i) for i in data.issues] == [
        "Session:4:None: same date, session_no as row 3: the row is left out"
    ]
    assert data.entities["session"].records[0]["kind"] == "Climb"


def test_a_blank_set_number_is_the_rows_place_in_its_session(module: Module) -> None:
    keys = [*SETS, "deleted"]
    sets = tab(
        keys,
        [D20, None, 1, 10],
        [D20, None, None, 11],  # 2nd row of the 20th → 2
        [D21, 2, None, 5],  # another session: 1
        [D20, None, None, 12, None, "x"],  # deleted: not counted
        [None, None, None, 13],  # no date: left out, not counted
        [D20, 1, None, 14],  # session_no blank = 1: same session, 3rd row → 3
        [D20, None, 2, 15],  # typed 2 again: a duplicate, as in the sheet
        [D20, None, "two", 16],  # a bad number stays bad
    )
    data = load_data(module, Memory(tabs(Sets=sets)))
    numbered = [
        (s["date"], s["session_no"], s["set_no"], s["kg"]) for s in data.entities["set"].records
    ]
    day20, day21 = D20.date(), D21.date()
    assert numbered == [
        (day20, 1, 1, 10), (day20, 1, 2, 11), (day21, 2, 1, 5), (day20, 1, 3, 14)
    ]  # fmt: skip
    assert [_line(i) for i in data.issues] == [
        "Sets:7:date: no date: the row is left out",
        "Sets:9:None: same date, session_no, set_no as row 4: the row is left out",
        "Sets:10:set_no: 'two' is not a number",
    ]


def test_deleted_rows_are_skipped(module: Module) -> None:
    session = tab(SESSION, [D20, None, "Climb"], [D21, 2, "Board", None, None, "2026-10-23"])
    data = load_data(module, Memory(tabs(Session=session)))
    assert len(data.entities["session"].records) == 1
    assert [_line(i) for i in data.issues] == [
        "Wellbeing:3:None: no Session row for date 2026-10-21, session_no 2"
    ]


def test_required_fields_are_checked_after_the_join(module: Module) -> None:
    """`route` is required on Wellbeing only when `kind`, on the Session tab, is Climb."""
    wellbeing = tab(WELLBEING, [D20, 1, None], [D21, 2, None])
    assert issues_of(module, tabs(Wellbeing=wellbeing)) == [
        "Wellbeing:3:mood: required, but empty",
        "Wellbeing:3:route: required, but empty",
        "Wellbeing:4:mood: required, but empty",
    ]
    # A session without a Wellbeing row: that section isn't filled in yet, nothing to report.
    assert issues_of(module, tabs(Wellbeing=tab(WELLBEING))) == []


def test_bad_cells_are_reported_and_blank(module: Module) -> None:
    sets = tab(SETS, [D20, None, 1, "10kg"], [D20, None, 2, 12, "maybe"])
    data = load_data(module, Memory(tabs(Sets=sets)))
    assert [_line(i) for i in data.issues] == [
        "Sets:3:kg: '10kg' is not a number",
        "Sets:4:completed: 'maybe' is not Yes or No",  # bad: not its default
    ]
    assert [(s["kg"], s["completed"]) for s in data.entities["set"].records] == [
        (None, True),
        (12, None),
    ]


def test_child_rows_without_a_parent_still_load(module: Module) -> None:
    sets = tab(SETS, [D20, None, 1, 10], [D22, None, 1, 5])
    data = load_data(module, Memory(tabs(Sets=sets)))
    assert [_line(i) for i in data.issues] == [
        "Sets:4:None: no Session row for date 2026-10-22, session_no 1"
    ]
    assert len(data.entities["set"].records) == 2


def test_missing_tabs_and_columns(module: Module) -> None:
    workbook = tabs(Wellbeing=tab(["date", "session_no", "route"], [D20, 1, "Via Lattea"]))
    del workbook["Falls"], workbook["_settings"]
    data = load_data(module, Memory(workbook))
    assert [_line(i) for i in data.issues] == [
        "Wellbeing:None:mood: the column is missing",  # and no "required" issues for it
        "Falls:None:None: the tab is missing",
    ]
    assert data.entities["fall"].records == []
    assert data.settings["low_max"] == 4  # no _settings tab: the defaults


@pytest.mark.parametrize(
    ("rows", "expected", "issues"),
    [
        ([["low_max", None]], 4, []),
        ([["low_max", "4,5"]], 4.5, []),
        ([["low_max", "lots"]], 4, ["_settings:None:low_max: 'lots' is not a number; using the "
                                    "default"]),
        ([["other", 1]], 4, []),
    ],
)  # fmt: skip
def test_settings(
    module: Module, rows: list[list[Any]], expected: float, issues: list[str]
) -> None:
    data = load_data(module, Memory(tabs(_settings=[["key", "value"], *rows])))
    assert data.settings["low_max"] == expected
    assert [_line(i) for i in data.issues] == issues


def test_an_xlsx_workbook_end_to_end(module: Module, tmp_path: Path) -> None:
    path = write_workbook(tmp_path / "test-load.xlsx", tabs())
    data = load_data(module, XlsxBackend(path))
    assert data.issues == []
    tables = {name: entity.records for name, entity in data.entities.items()}
    derived = compute_module(module, tables, data.settings)
    assert [d["low_mood"] for d in derived["session"]] == [False, False]  # 8 and 7 > 5
    assert data.entities["session"].records[0]["route"] == "Via Lattea"
