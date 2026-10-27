# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract: writing a workbook, on every backend (04 §1, §3b, D-049, D-054).

Appends into free rows of the formula buffer, raw text, updates with a conflict check, all or
nothing, key/value tabs. Backend-specific writing (number formats, lock files, saving a file,
backups) is tested next to its backend, e.g. `test_xlsx_write.py`.
"""

import datetime as dt

import pytest
from backends import Backend
from workbooks import tab

from climblog.storage import (
    Append,
    Repository,
    SheetRow,
    StorageError,
    TableNotFound,
    Update,
    WriteConflict,
)

D20, D21 = dt.datetime(2026, 10, 20), dt.datetime(2026, 10, 21)
KEYS = ["date", "kg", "note", "auto:double", "updated_at"]
TABS = ("Sets", "_settings", "Labels")


def formula(row: int) -> str:
    return f'=IF($A{row}="","",B{row}*2)'


@pytest.fixture
def book(backend: Backend) -> Repository:
    """Two records, a blank-key row with hand data, then two buffer rows with formulas."""
    return backend.make(
        {
            "Sets": tab(
                KEYS,
                [D20, 10, None, formula(3)],
                [D21, 12.5, "Più riposo", formula(4)],
                [None, 15, None, formula(5)],  # no date: a data issue, never overwritten
                [None, None, None, formula(6)],
                [None, None, None, formula(7)],
            ),
            "_settings": [["key", "value"], ["low_max", 4]],
            "Labels": [["Date"]],  # no key row yet
        }
    )


def test_appends_fill_the_formula_buffer_then_go_below(backend: Backend, book: Repository) -> None:
    rows = book.apply([Append("Sets", {"date": D20, "kg": 11}) for _ in range(3)])
    assert rows == [6, 7, 8]
    cells = backend.cells(book, "Sets")
    assert cells[4][:2] == (None, 15)  # the hand row is kept
    assert cells[5] == (D20, 11, None, formula(6), None)  # the formula is kept
    assert cells[7][:4] == (D20, 11, None, formula(8))  # the buffer was topped up (D-054)
    assert book.read_table("Sets").rows[-1] == SheetRow(8, {"date": D20, "kg": 11})


def test_appends_keep_fifty_free_formula_rows(backend: Backend, book: Repository) -> None:
    book.apply([Append("Sets", {"date": D21, "kg": 9})])
    cells = backend.cells(book, "Sets")
    assert len(cells) == 202  # a buffer of at least 200 rows, from row 3
    assert cells[-1][3] == formula(202)
    assert cells[-1][:3] == (None, None, None)
    rows = book.apply([Append("Sets", {"date": D21, "kg": 9}) for _ in range(160)])
    assert rows[-1] == 166
    assert len(backend.cells(book, "Sets")) == 366  # under 50 free rows: 200 past the last data row


def test_an_update_takes_no_buffer_row(backend: Backend, book: Repository) -> None:
    book.apply([Update("Sets", 3, {"kg": 11}, {"date": D20, "kg": 10})])
    assert len(backend.cells(book, "Sets")) == 7


NOTES = ["=1+1", "'po' stanco", "+3 kg", "-2", "perché 💪", "riga 1\nriga 2", "  "]


def test_strings_are_written_as_text(backend: Backend, book: Repository) -> None:
    book.apply([Append("Sets", {"date": D20, "note": note}) for note in NOTES])
    assert [row[2] for row in backend.cells(book, "Sets")[5 : 5 + len(NOTES)]] == NOTES
    assert [row.cells.get("note") for row in book.read_table("Sets").rows[3:]] == NOTES


def test_updates_change_cells_and_keep_the_rest(backend: Backend, book: Repository) -> None:
    row = book.read_table("Sets").rows[1]
    assert book.apply([Update("Sets", 4, {"kg": 13, "note": None}, row.cells)]) == [4]
    assert backend.cells(book, "Sets")[3] == (D21, 13, None, formula(4), None)


def test_a_row_changed_since_it_was_read_is_a_conflict(backend: Backend, book: Repository) -> None:
    row = book.read_table("Sets").rows[1]
    stale = {**row.cells, "kg": 12}
    with pytest.raises(WriteConflict, match="row 4 changed since it was read"):
        book.apply([Update("Sets", 4, {"kg": 13}, stale)])
    with pytest.raises(WriteConflict):  # a cell filled by hand counts too
        book.apply([Update("Sets", 4, {"kg": 13}, {"date": D21, "kg": 12.5})])
    assert backend.cells(book, "Sets")[3][1] == 12.5
    # formula columns are not compared: their values come from the last recalculation
    book.apply([Update("Sets", 4, {"kg": 13}, {**row.cells, "auto:double": 99})])
    assert backend.cells(book, "Sets")[3][1] == 13


def test_edits_are_all_or_nothing(backend: Backend, book: Repository) -> None:
    before = [backend.cells(book, name) for name in TABS]
    with pytest.raises(StorageError, match="tab 'Sets' has no column weight in row 2"):
        book.apply([Append("Sets", {"date": D20}), Append("Sets", {"weight": 70})])
    with pytest.raises(StorageError, match="auto:double is app-managed"):
        book.apply([Append("Sets", {"auto:double": 1})])
    with pytest.raises(StorageError, match="row 2 is a header row"):
        book.apply([Update("Sets", 2, {"kg": 1}, {})])
    with pytest.raises(StorageError, match="tab 'Labels' has no column date in row 2"):
        book.apply([Append("Labels", {"date": D20})])
    with pytest.raises(TableNotFound):
        book.apply([Append("Hangs", {"date": D20})])
    assert [backend.cells(book, name) for name in TABS] == before


def test_reads_see_the_new_rows(book: Repository) -> None:
    assert len(book.read_table("Sets").rows) == 3
    book.apply([Append("Sets", {"date": D20})])
    assert len(book.read_table("Sets").rows) == 4


def test_a_missing_workbook_is_a_storage_error(backend: Backend) -> None:
    with pytest.raises(StorageError):
        backend.new().apply([])


def test_write_kv_sets_values_and_adds_keys(backend: Backend, book: Repository) -> None:
    book.write_kv("_settings", {"low_max": 5, "note": "=keep as text"})
    assert book.read_kv("_settings") == {"low_max": 5, "note": "=keep as text"}
    assert backend.cells(book, "_settings") == [
        ("key", "value"),
        ("low_max", 5),
        ("note", "=keep as text"),
    ]


def test_write_kv_updates_the_first_of_a_repeated_key(backend: Backend) -> None:
    book = backend.make(
        {"_meta": [["Value", None, "Key"], [1, None, "v"], [None, None, None], [2, None, "v"]]}
    )
    book.write_kv("_meta", {"v": 3})
    assert backend.cells(book, "_meta")[1:] == [(3, None, "v"), (None, None, None), (2, None, "v")]
    bad = backend.make({"_meta": [["k", "v"]]})
    with pytest.raises(StorageError, match="needs the headers 'key' and 'value'"):
        bad.write_kv("_meta", {"v": 1})
