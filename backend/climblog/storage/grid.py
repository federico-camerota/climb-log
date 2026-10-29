# SPDX-License-Identifier: GPL-3.0-or-later
"""A tab as rows of raw cells, read the same way by every backend (04-storage.md §1, D-048).

Row 2 holds the column keys, data starts in row 3; key/value tabs name their `key` and `value`
columns in row 1. A backend turns its sheet into `Rows` (row 1 first) and these functions do the
rest, so the rules and their messages are the same for xlsx and Google Sheets.
"""

from collections.abc import Sequence

from openpyxl.utils import get_column_letter

from climblog.storage.base import FIRST_DATA_ROW, SheetRow, StorageError, Table
from climblog.storage.cells import RawCell

Rows = list[tuple[RawCell, ...]]


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
