# SPDX-License-Identifier: GPL-3.0-or-later
"""The backend-neutral view of a workbook (02-architecture.md, 04-storage.md §1, D-048).

A tab has two header rows: labels (row 1, for people) and field keys (row 2, for the app).
Backends match columns on the keys, so column order does not matter, and give each data row
(row 3 on) as `{key: raw cell}` with its row number. Parsing cells and building records is the
loader's job (`load.py`), the same for every backend.

Writes are row edits applied together in one save (D-049): an `Append` goes into the first free
row, an `Update` changes some cells of a row and is refused if the row changed since it was read.
Turning records into edits is `write.py`'s job.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from climblog.storage.cells import RawCell

if TYPE_CHECKING:
    from climblog.storage.layout import WorkbookLayout

FIRST_DATA_ROW = 3
AUTO = "auto:"  # app-managed formula columns: never written, ignored in conflict checks


@dataclass(frozen=True)
class SheetRow:
    number: int  # the sheet's row number (1-based)
    cells: Mapping[str, RawCell]  # column key → cell; blank cells may be absent


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]  # the keys of row 2, in sheet order
    rows: tuple[SheetRow, ...]  # data rows with at least one non-blank cell


@dataclass(frozen=True)
class Append:
    """A new row in the first free row of the tab: one whose columns, `auto:` aside, are blank."""

    tab: str
    cells: Mapping[str, RawCell]  # column key → cell


@dataclass(frozen=True)
class Update:
    """New values for some cells of a row (None clears a cell)."""

    tab: str
    row: int  # the sheet's row number
    cells: Mapping[str, RawCell]
    expected: Mapping[str, RawCell]  # the row as read (`SheetRow.cells`): a change is a conflict


Edit = Append | Update


class StorageError(Exception):
    """The workbook cannot be read (missing file, broken header row, …)."""


class TableNotFound(StorageError):
    """The workbook has no tab of that name."""


class WorkbookLocked(StorageError):
    """The workbook is open in another program; reading still works."""


class WriteConflict(StorageError):
    """A row changed in the workbook since it was read (a hand edit, D-027)."""


class Repository(Protocol):
    """One module's workbook."""

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

    def apply(self, edits: Sequence[Edit]) -> list[int]:
        """Write the edits in one save, all or nothing; the sheet row of each edit.

        Raises `WorkbookLocked`, `WriteConflict`, `TableNotFound`, or `StorageError` (e.g. a
        column missing from row 2).
        """
        ...

    def write_kv(self, name: str, values: Mapping[str, RawCell]) -> None:
        """Set values in a key/value tab; a key not there yet gets a new row."""
        ...

    def exists(self) -> bool:
        """Whether the workbook exists (schema sync creates it)."""
        ...

    def sync_schema(self, layout: "WorkbookLayout", meta: Mapping[str, RawCell]) -> list[str]:
        """Make the workbook match the layout, additively, in one save; one line per change.

        Creates the workbook if it doesn't exist. Raises `WorkbookLocked` or `StorageError`.
        """
        ...
