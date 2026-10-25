# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a local workbook: two header rows, columns by key, key/value tabs (04 §1, §2, D-048)."""

import datetime as dt
import os
from pathlib import Path

import openpyxl
import pytest
from workbooks import tab, write_workbook

from climblog.storage import SheetRow, StorageError, TableNotFound, XlsxBackend


@pytest.fixture
def book(tmp_path: Path) -> XlsxBackend:
    path = write_workbook(
        tmp_path / "journal.xlsx",
        {
            "Session": tab(
                ["venue", None, "date", "auto:status", "notes"],  # any order; a blank key
                ["Gym", "x", dt.datetime(2026, 10, 20), "GOOD", "Più riposo"],
                [None, None, None, "", None],  # empty: left out
                [None, None, dt.datetime(2026, 10, 22), None, "  "],
            ),
            "_settings": [["key", "value", "label"], ["low_max", 4, "LOW when ≤"], [None, 9]],
            "_meta": [["Key", "Value"], ["module", "test_journal"], ["module", "duplicate"]],
            "Empty": [],
        },
    )
    return XlsxBackend(path)


def test_tables_have_columns_by_key_and_row_numbers(book: XlsxBackend) -> None:
    assert book.list_tables() == ["Session", "_settings", "_meta", "Empty"]
    table = book.read_table("Session")
    assert table.columns == ("venue", "date", "auto:status", "notes")
    assert table.rows == (
        SheetRow(3, {"venue": "Gym", "date": dt.datetime(2026, 10, 20), "auto:status": "GOOD",
                     "notes": "Più riposo"}),
        SheetRow(5, {"date": dt.datetime(2026, 10, 22), "notes": "  "}),  # text kept as written
    )  # fmt: skip


def test_a_tab_without_rows(book: XlsxBackend) -> None:
    table = book.read_table("Empty")
    assert (table.columns, table.rows) == ((), ())


def test_key_value_tabs(book: XlsxBackend) -> None:
    assert book.read_kv("_settings") == {"low_max": 4}
    assert book.read_kv("_meta") == {"module": "test_journal"}  # headers in any case; first wins


def test_a_key_value_tab_needs_its_headers(book: XlsxBackend) -> None:
    with pytest.raises(StorageError, match="needs the headers 'key' and 'value' in row 1"):
        book.read_kv("Session")
    with pytest.raises(StorageError, match="needs the headers"):
        book.read_kv("Empty")


def test_missing_tab_and_file(book: XlsxBackend, tmp_path: Path) -> None:
    with pytest.raises(TableNotFound, match=r"no tab 'Sessions' in journal\.xlsx"):
        book.read_table("Sessions")
    with pytest.raises(StorageError, match="workbook not found"):
        XlsxBackend(tmp_path / "nope.xlsx").list_tables()


def test_a_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.xlsx"
    path.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(StorageError, match=r"cannot read broken\.xlsx"):
        XlsxBackend(path).list_tables()


def test_a_key_twice_in_row_2(tmp_path: Path) -> None:
    path = write_workbook(tmp_path / "w.xlsx", {"T": tab(["date", "mood", "mood"])})
    with pytest.raises(StorageError, match=r"column key 'mood' is in row 2 twice \(B2 and C2\)"):
        XlsxBackend(path).read_table("T")


def test_formulas_read_as_the_sheet_shows_them(tmp_path: Path) -> None:
    """data_only: a formula cell gives its last computed value (none in a file openpyxl wrote)."""
    path = write_workbook(tmp_path / "w.xlsx", {"T": tab(["a", "auto:b"], [2, "=A3*2"])})
    assert XlsxBackend(path).read_table("T").rows == (SheetRow(3, {"a": 2}),)


def test_the_workbook_is_read_again_when_it_changes(tmp_path: Path) -> None:
    path = write_workbook(tmp_path / "w.xlsx", {"T": tab(["a"], [1])})
    book = XlsxBackend(path)
    assert book.read_table("T").rows == (SheetRow(3, {"a": 1}),)
    first = book.last_modified()

    workbook = openpyxl.load_workbook(path)
    workbook["T"].append([2])
    workbook.save(path)
    later = path.stat().st_mtime + 5
    os.utime(path, (later, later))  # a clearly newer mtime, whatever the clock resolution
    assert [row.cells for row in book.read_table("T").rows] == [{"a": 1}, {"a": 2}]
    assert book.last_modified() > first


def test_rare_openpyxl_values_become_raw_cells() -> None:
    from decimal import Decimal

    from openpyxl.cell.rich_text import CellRichText

    from climblog.storage.xlsx import _raw

    assert _raw(Decimal("7.5")) == 7.5
    assert _raw(CellRichText(["Più ", "riposo"])) == "Più riposo"
    assert _raw(dt.time(9, 30)) == dt.time(9, 30)
