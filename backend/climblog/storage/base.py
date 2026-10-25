# SPDX-License-Identifier: GPL-3.0-or-later
"""The backend-neutral view of a workbook (02-architecture.md, 04-storage.md §1, D-048).

A tab has two header rows: labels (row 1, for people) and field keys (row 2, for the app).
Backends match columns on the keys, so column order does not matter, and give each data row
(row 3 on) as `{key: raw cell}` with its row number. Parsing cells and building records is the
loader's job (`load.py`), the same for every backend.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from climblog.storage.cells import RawCell

FIRST_DATA_ROW = 3


@dataclass(frozen=True)
class SheetRow:
    number: int  # the sheet's row number (1-based)
    cells: Mapping[str, RawCell]  # column key → cell; blank cells may be absent


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]  # the keys of row 2, in sheet order
    rows: tuple[SheetRow, ...]  # data rows with at least one non-blank cell


class StorageError(Exception):
    """The workbook cannot be read (missing file, broken header row, …)."""


class TableNotFound(StorageError):
    """The workbook has no tab of that name."""


class Repository(Protocol):
    """One module's workbook. Writes come with #15, schema sync with #17."""

    def list_tables(self) -> list[str]:
        """The workbook's tab names."""
        ...

    def read_table(self, name: str) -> Table:
        """A data tab: keys from row 2, rows from row 3. Raises `TableNotFound`."""
        ...

    def read_kv(self, name: str) -> dict[str, RawCell]:
        """A key/value tab (`_meta`, `_settings`): `key` and `value` columns named in row 1."""
        ...

    def last_modified(self) -> dt.datetime:
        """When the workbook last changed, to reload it."""
        ...
