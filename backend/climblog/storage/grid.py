# SPDX-License-Identifier: GPL-3.0-or-later
"""A tab as rows of raw cells, read the same way by every backend (04-storage.md §1, D-048).

Row 2 holds the column keys, data starts in row 3; key/value tabs name their `key` and `value`
columns in row 1. A backend turns its sheet into `Rows` (row 1 first) and these functions do the
rest, so the rules and their messages are the same for xlsx and Google Sheets.
"""

from collections.abc import Mapping, Sequence

from openpyxl.utils import get_column_letter

from climblog.storage.base import (
    AUTO,
    FIRST_DATA_ROW,
    SheetRow,
    StorageError,
    Table,
    Update,
    WriteConflict,
)
from climblog.storage.cells import RawCell

Rows = list[tuple[RawCell, ...]]

BUFFER = 200  # rows that already hold the formulas, for hand entry (04 §1)
TOP_UP = 50  # fewer free buffer rows than this: 200 more


def grid_table(name: str, rows: Rows) -> Table:
    """Keys from row 2, rows from row 3 (those with a non-blank cell)."""
    columns = key_columns(name, rows[FIRST_DATA_ROW - 2] if len(rows) >= FIRST_DATA_ROW - 1 else ())
    data = []
    for number, row in enumerate(rows[FIRST_DATA_ROW - 1 :], start=FIRST_DATA_ROW):
        cells = {k: row[i] for k, i in columns.items() if i < len(row) and row[i] not in (None, "")}
        if any(not blank(value) for value in cells.values()):  # kept as written (04 §3b)
            data.append(SheetRow(number, cells))
    numbers = {key: i + 1 for key, i in columns.items()}
    return Table(name, tuple(columns), tuple(data), numbers)


def key_columns(tab: str, keys: Sequence[object]) -> dict[str, int]:
    """Column key (row 2) → 0-based column index. A key twice is an error."""
    columns: dict[str, int] = {}
    for i, key in enumerate(keys):
        if blank(key):
            continue
        text = str(key).strip()
        if text in columns:
            first, second = (get_column_letter(c + 1) for c in (columns[text], i))
            raise StorageError(
                f"tab '{tab}': column key '{text}' is in row 2 twice ({first}2 and {second}2)"
            )
        columns[text] = i
    return columns


def kv_columns(tab: str, headers: Sequence[object]) -> tuple[int, int]:
    """The `key` and `value` columns of a key/value tab, from row 1."""
    names = [str(h).strip().casefold() if not blank(h) else "" for h in headers]
    if "key" not in names or "value" not in names:
        raise StorageError(f"tab '{tab}' needs the headers 'key' and 'value' in row 1")
    return names.index("key"), names.index("value")


def kv_pairs(tab: str, rows: Rows) -> dict[str, RawCell]:
    """A key/value tab as a dict; the first row of a repeated key wins."""
    k, v = kv_columns(tab, rows[0] if rows else ())
    pairs: dict[str, RawCell] = {}
    for row in rows[1:]:
        key = row[k] if k < len(row) else None
        if not blank(key):
            pairs.setdefault(str(key).strip(), row[v] if v < len(row) else None)
    return pairs


def blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def formula_rows_end(last_data: int, last_formula: int) -> int:
    """The last row the formula buffer should reach, given the last row with data and the last
    with a formula: at least `BUFFER` rows from row 3, and `BUFFER` past the last data row when
    fewer than `TOP_UP` are free (D-054)."""
    end = max(last_formula, FIRST_DATA_ROW + BUFFER - 1)
    if end - last_data < TOP_UP:
        end = last_data + BUFFER
    return end


def check_columns(tab: str, columns: Mapping[str, int], cells: Mapping[str, RawCell]) -> None:
    """The cells of an edit are in row 2, and none is an app-managed formula column."""
    missing = [key for key in cells if key not in columns]
    if missing:
        raise StorageError(f"tab '{tab}' has no column {', '.join(missing)} in row 2")
    formulas = [key for key in cells if key.startswith(AUTO)]
    if formulas:
        raise StorageError(f"tab '{tab}': {', '.join(formulas)} is app-managed, not written")


def check_unchanged(edit: Update, now: Mapping[str, RawCell]) -> None:
    """The row still holds what was read (`now`: every column of the row as in the sheet),
    `auto:` columns aside; a blank cell and an absent one are the same (D-027)."""
    if edit.row < FIRST_DATA_ROW:
        raise StorageError(f"tab '{edit.tab}': row {edit.row} is a header row")
    for key, value in now.items():
        if key.startswith(AUTO):
            continue
        if _filled(value) != _filled(edit.expected.get(key)):
            raise WriteConflict(
                f"tab '{edit.tab}', row {edit.row} changed since it was read: reload and retry"
            )


def _filled(value: RawCell) -> RawCell:
    return None if value == "" else value
