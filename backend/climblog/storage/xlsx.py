# SPDX-License-Identifier: GPL-3.0-or-later
"""The local `.xlsx` backend: reading (04-storage.md §2, D-048). Writing comes with #15.

The workbook is read in one pass, read-only, as the sheet shows it (`data_only`: a formula
gives its last computed value), and kept until the file changes.
"""

import datetime as dt
import zipfile
from decimal import Decimal
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from climblog.storage.base import (
    FIRST_DATA_ROW,
    SheetRow,
    StorageError,
    Table,
    TableNotFound,
)
from climblog.storage.cells import RawCell

Sheet = list[tuple[RawCell, ...]]


class XlsxBackend:
    """A `Repository` on a local workbook."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: tuple[int, dict[str, Sheet]] | None = None

    def list_tables(self) -> list[str]:
        return list(self._sheets())

    def read_table(self, name: str) -> Table:
        rows = self._sheet(name)
        keys = rows[FIRST_DATA_ROW - 2] if len(rows) >= FIRST_DATA_ROW - 1 else ()
        columns: dict[str, int] = {}
        for i, key in enumerate(keys):
            if _blank(key):
                continue
            text = str(key).strip()
            if text in columns:
                first, second = (get_column_letter(c + 1) for c in (columns[text], i))
                raise StorageError(
                    f"tab '{name}': column key '{text}' is in row 2 twice ({first}2 and {second}2)"
                )
            columns[text] = i

        data = []
        for number, row in enumerate(rows[FIRST_DATA_ROW - 1 :], start=FIRST_DATA_ROW):
            cells = {
                k: row[i] for k, i in columns.items() if i < len(row) and row[i] not in (None, "")
            }
            if any(not _blank(value) for value in cells.values()):  # kept as written (04 §3b)
                data.append(SheetRow(number, cells))
        return Table(name, tuple(columns), tuple(data))

    def read_kv(self, name: str) -> dict[str, RawCell]:
        rows = self._sheet(name)
        headers = (
            [str(h).strip().casefold() if not _blank(h) else "" for h in rows[0]] if rows else []
        )
        if "key" not in headers or "value" not in headers:
            raise StorageError(f"tab '{name}' needs the headers 'key' and 'value' in row 1")
        k, v = headers.index("key"), headers.index("value")
        pairs: dict[str, RawCell] = {}
        for row in rows[1:]:
            key = row[k] if k < len(row) else None
            if not _blank(key):
                pairs.setdefault(str(key).strip(), row[v] if v < len(row) else None)
        return pairs

    def last_modified(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self._stat_mtime_ns() / 1e9)

    # ---- Reading ----

    def _sheet(self, name: str) -> Sheet:
        sheets = self._sheets()
        if name not in sheets:
            raise TableNotFound(f"no tab '{name}' in {self.path.name}")
        return sheets[name]

    def _sheets(self) -> dict[str, Sheet]:
        mtime = self._stat_mtime_ns()
        if self._cache is not None and self._cache[0] == mtime:
            return self._cache[1]
        try:
            workbook = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as error:
            raise StorageError(f"cannot read {self.path.name}: {error}") from None
        try:
            sheets = {
                sheet.title: [
                    tuple(_raw(v) for v in row) for row in sheet.iter_rows(values_only=True)
                ]
                for sheet in workbook.worksheets
            }
        finally:
            workbook.close()
        self._cache = (mtime, sheets)
        return sheets

    def _stat_mtime_ns(self) -> int:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            raise StorageError(f"workbook not found: {self.path}") from None


def _raw(value: object) -> RawCell:
    """openpyxl's cell value as one of ours: a Decimal is a float, rich text its plain text."""
    if value is None or isinstance(value, str | int | float | dt.date | dt.time | dt.timedelta):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)  # rich text, or a formula object (not given with data_only)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
