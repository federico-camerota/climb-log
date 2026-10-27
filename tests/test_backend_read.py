# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract: reading a workbook, on every backend (04 §1, D-048).

Two header rows, columns by key, key/value tabs. Backend-specific reading (file formats, raw
cell types of a library) is tested next to its backend, e.g. `test_xlsx.py`.
"""

import datetime as dt
import re

import pytest
from backends import Backend
from workbooks import tab

from climblog.storage import Repository, SheetRow, StorageError, TableNotFound


@pytest.fixture
def book(backend: Backend) -> Repository:
    return backend.make(
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
        }
    )


def test_tables_have_columns_by_key_and_row_numbers(book: Repository) -> None:
    assert book.list_tables() == ["Session", "_settings", "_meta", "Empty"]
    table = book.read_table("Session")
    assert table.columns == ("venue", "date", "auto:status", "notes")
    assert table.rows == (
        SheetRow(3, {"venue": "Gym", "date": dt.datetime(2026, 10, 20), "auto:status": "GOOD",
                     "notes": "Più riposo"}),
        SheetRow(5, {"date": dt.datetime(2026, 10, 22), "notes": "  "}),  # text kept as written
    )  # fmt: skip


def test_a_tab_without_rows(book: Repository) -> None:
    table = book.read_table("Empty")
    assert (table.columns, table.rows) == ((), ())


def test_key_value_tabs(book: Repository) -> None:
    assert book.read_kv("_settings") == {"low_max": 4}
    assert book.read_kv("_meta") == {"module": "test_journal"}  # headers in any case; first wins


def test_a_key_value_tab_needs_its_headers(book: Repository) -> None:
    with pytest.raises(StorageError, match="needs the headers 'key' and 'value' in row 1"):
        book.read_kv("Session")
    with pytest.raises(StorageError, match="needs the headers"):
        book.read_kv("Empty")


def test_missing_tab_and_workbook(backend: Backend, book: Repository) -> None:
    name = re.escape(backend.label(book))
    with pytest.raises(TableNotFound, match=f"no tab 'Sessions' in {name}"):
        book.read_table("Sessions")
    missing = backend.new()
    assert not missing.exists()
    with pytest.raises(StorageError, match="workbook not found"):
        missing.list_tables()


def test_a_key_twice_in_row_2(backend: Backend) -> None:
    book = backend.make({"T": tab(["date", "mood", "mood"])})
    with pytest.raises(StorageError, match=r"column key 'mood' is in row 2 twice \(B2 and C2\)"):
        book.read_table("T")


def test_the_workbook_is_read_again_when_it_changes(backend: Backend) -> None:
    book = backend.make({"T": tab(["a"], [1])})
    assert book.read_table("T").rows == (SheetRow(3, {"a": 1}),)
    first = book.last_modified()
    backend.edit(book, "T", "A4", 2)
    assert [row.cells for row in book.read_table("T").rows] == [{"a": 1}, {"a": 2}]
    assert book.last_modified() > first
