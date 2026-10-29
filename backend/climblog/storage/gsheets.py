# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google Sheets backend: reading (04-storage.md §3, D-063).

The whole spreadsheet is read in one call, with each cell's value, number format and formula.
The copy is read again when Drive says the file changed, or when it is older than `max_age`:
Drive's `modifiedTime` moves about 3 minutes after an edit (measured on 2026-10-29), so it alone
would hide a phone edit for that long. `last_modified` is Drive's time, or the moment the app
saw the content change if that is later, so the snapshot (D-020) follows the content.

Cells become the same raw values openpyxl gives for an `.xlsx`: a number formatted as a date is
a `datetime`, as a time a `time`, as a duration (`[h]:mm`) a `timedelta`, so the loader reads
both backends alike. Writing comes with #52 and schema sync with #53.
"""

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from climblog.storage.base import Edit, StorageError, Table, TableNotFound
from climblog.storage.cells import RawCell
from climblog.storage.google_client import GoogleNotFound, Json, SheetsClient
from climblog.storage.grid import Rows, grid_table, kv_pairs
from climblog.storage.layout import WorkbookLayout

_EPOCH = dt.datetime(1899, 12, 30)  # day 0 of spreadsheet date serials
_ERRORS = {  # Google's error types as the sheet shows them (and openpyxl reads them)
    "NULL_VALUE": "#NULL!",
    "DIVIDE_BY_ZERO": "#DIV/0!",
    "VALUE": "#VALUE!",
    "REF": "#REF!",
    "NAME": "#NAME?",
    "NUM": "#NUM!",
    "N_A": "#N/A",
    "LOADING": "#LOADING",
}


MAX_AGE = dt.timedelta(seconds=60)


@dataclass(frozen=True)
class _Copy:
    drive_modified: dt.datetime  # Drive's modifiedTime when the grid was read
    read_at: dt.datetime
    changed_at: dt.datetime  # when the app last saw the content differ
    grid: Json


class GSheetsBackend:
    """A `Repository` on a Google Sheet (reading)."""

    def __init__(
        self,
        spreadsheet_id: str,
        client: SheetsClient,
        *,
        max_age: dt.timedelta = MAX_AGE,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.client = client
        self.max_age = max_age
        self._clock = clock
        self._copy: _Copy | None = None

    @property
    def label(self) -> str:
        """How messages name the sheet: by its title once read, else by its ID."""
        if self._copy is not None:
            return f"Google Sheet '{self._copy.grid['properties']['title']}'"
        return f"Google Sheet {self.spreadsheet_id}"

    def list_tables(self) -> list[str]:
        return [str(sheet["properties"]["title"]) for sheet in self._sheets()]

    def read_table(self, name: str) -> Table:
        return grid_table(name, grid_rows(self._sheet(name)))

    def read_formulas(self, name: str) -> Table:
        return grid_table(name, grid_rows(self._sheet(name), formulas=True))

    def read_kv(self, name: str) -> dict[str, RawCell]:
        return kv_pairs(name, grid_rows(self._sheet(name)))

    def last_modified(self) -> dt.datetime:
        """Drive's time, or when the app saw the content change if later; reads the sheet again
        when Drive says it changed or the copy is older than `max_age`."""
        drive, now, copy = self._drive_modified(), self._clock(), self._copy
        if copy is None or copy.drive_modified != drive or now - copy.read_at >= self.max_age:
            try:
                grid = self.client.get_grid(self.spreadsheet_id)
            except GoogleNotFound:
                raise StorageError(f"workbook not found: {self.label}") from None
            changed = now if copy is None or grid != copy.grid else copy.changed_at
            self._copy = copy = _Copy(drive, now, changed, grid)
        return max(drive, copy.changed_at)

    def _drive_modified(self) -> dt.datetime:
        try:
            return self.client.modified_time(self.spreadsheet_id)
        except GoogleNotFound:
            if not self.exists():
                raise StorageError(f"workbook not found: {self.label}") from None
        raise StorageError(  # Drive shows the app only the files it created (D-062)
            f"{self.label} was not created by climb-log, so the app can't see when it changes: "
            "let the app create the module's sheet (#54)"
        )

    def exists(self) -> bool:
        try:
            self.client.title(self.spreadsheet_id)
        except GoogleNotFound:
            return False
        return True

    def apply(self, edits: Sequence[Edit]) -> list[int]:
        raise StorageError("writing to Google Sheets comes with #52")

    def write_kv(self, name: str, values: Mapping[str, RawCell]) -> None:
        raise StorageError("writing to Google Sheets comes with #52")

    def sync_schema(self, layout: WorkbookLayout, meta: Mapping[str, RawCell]) -> list[str]:
        raise StorageError("schema sync on Google Sheets comes with #53")

    # ---- Reading ----

    def _sheets(self) -> list[Json]:
        self.last_modified()  # reads the sheet again when due
        assert self._copy is not None
        sheets: list[Json] = self._copy.grid.get("sheets", [])
        return sorted(sheets, key=lambda sheet: sheet["properties"].get("index", 0))

    def _sheet(self, name: str) -> Json:
        for sheet in self._sheets():
            if sheet["properties"]["title"] == name:
                return sheet
        raise TableNotFound(f"no tab '{name}' in {self.label}")


def grid_rows(sheet: Mapping[str, Any], *, formulas: bool = False) -> Rows:
    """A tab of a `get_grid` response as rows of raw cells (row 1 first); with `formulas`, a
    formula cell gives its formula (`=IF(...)`) instead of its value."""
    rows: Rows = []
    for data in sheet.get("data", []):  # one block: the whole tab was asked for
        for row in data.get("rowData", []):
            rows.append(tuple(_cell(value, formulas) for value in row.get("values", [])))
    return rows


def _cell(value: Mapping[str, Any], formulas: bool) -> RawCell:
    if formulas and "formulaValue" in value.get("userEnteredValue", {}):
        return str(value["userEnteredValue"]["formulaValue"])
    effective = value.get("effectiveValue")
    if not effective:
        return None
    if "stringValue" in effective:
        return str(effective["stringValue"])
    if "boolValue" in effective:
        return bool(effective["boolValue"])
    if "errorValue" in effective:
        return _ERRORS.get(effective["errorValue"].get("type"), "#ERROR!")
    number = effective.get("numberValue")
    if not isinstance(number, int | float):
        return None
    form = value.get("effectiveFormat", {}).get("numberFormat", {})
    kind, pattern = form.get("type"), str(form.get("pattern", "")).casefold()
    if kind in ("DATE", "DATE_TIME"):
        return _EPOCH + _days(number)
    if kind == "TIME" and "[h" in pattern:  # elapsed time, e.g. [h]:mm
        return _days(number)
    if kind == "TIME":
        return (dt.datetime.min + _days(number % 1)).time()
    return int(number) if float(number).is_integer() else float(number)


def _days(serial: float) -> dt.timedelta:
    """Days as a timedelta, to the millisecond (serials carry float noise below that)."""
    return dt.timedelta(milliseconds=round(serial * 86_400_000))
