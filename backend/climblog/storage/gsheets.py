# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google Sheets backend (04-storage.md §3, D-063, D-064).

The whole spreadsheet is read in one call, with each cell's value, number format and formula.
The copy is read again when Drive says the file changed, or when it is older than `max_age`:
Drive's `modifiedTime` moves about 3 minutes after an edit (measured on 2026-10-29), so it alone
would hide a phone edit for that long. `last_modified` is Drive's time, or the moment the app
saw the content change if that is later, so the snapshot (D-020) follows the content.

Cells become the same raw values openpyxl gives for an `.xlsx`: a number formatted as a date is
a `datetime`, as a time a `time`, as a duration (`[h]:mm`) a `timedelta`, so the loader reads
both backends alike. The API takes formulas in en_US syntax, and gives each back in the syntax
it was entered in: the app's (`updateCells`) as written, one typed by hand (or sent with
`spreadsheets.create`) in a decimal-comma locale as `=IF(A3="";"";B3*1,5)` (measured on
2026-10-30). Those are turned back into en_US syntax, so the drift check compares like with like.

A write reads the sheet again first (the cached copy may be a minute old), checks the edits on
it as the xlsx backend does (free rows, conflicts, columns), and sends them all in one
`batchUpdate`, which Google applies all or none: the cells, more grid rows when needed and the
formula buffer's top-up (copied down, so Google moves the relative references). Strings are text
cells (`stringValue`, the API's RAW), so `'`, `=` notes stay as typed (04 §3b). A hand edit made
between that read and the write is not seen: edits by hand are occasional (D-027) and backups
cover the rest.

Schema sync (`gsheets_sync.py`) sends its changes in one `batchUpdate` too. A backend made
without an ID creates its spreadsheet on the first sync, in the app's Drive folder, with the
locale and time zone of `NewSheets` (D-065).
"""

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from climblog.storage.base import (
    AUTO,
    FIRST_DATA_ROW,
    Append,
    Edit,
    StorageError,
    Table,
    TableNotFound,
)
from climblog.storage.cells import RawCell
from climblog.storage.google_client import GoogleNotFound, Json, SheetsClient
from climblog.storage.grid import (
    Rows,
    blank,
    check_columns,
    check_unchanged,
    formula_rows_end,
    grid_table,
    key_columns,
    kv_columns,
    kv_pairs,
)
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
_DAY = dt.timedelta(days=1)
# Number formats for the cells the app writes, as the xlsx backend's (04 §2); a cell keeps a
# format chosen in the sheet if it is of the value's kind.
DATE_FORMAT = {"type": "DATE", "pattern": "dd/mm/yyyy"}
_DATE_TIME = {"type": "DATE_TIME", "pattern": "dd/mm/yyyy hh:mm:ss"}
_TIME = {"type": "TIME", "pattern": "hh:mm"}
_DURATION = {"type": "TIME", "pattern": "[h]:mm"}
_TEXT = {"type": "TEXT"}
_KINDS = {"DATE": "date", "DATE_TIME": "date", "TIME": "date", "NUMBER": "number",
          "PERCENT": "number", "CURRENCY": "number", "SCIENTIFIC": "number"}  # fmt: skip


@dataclass(frozen=True)
class NewSheets:
    """Where and how the app creates a module's spreadsheet (`[google]` in the app config)."""

    folder: str = "climb-log"  # in My Drive
    locale: str = "it_IT"  # how the sheet reads what is typed by hand: 7,5 and 24/10/2026
    time_zone: str = "Europe/Rome"


NEW_SHEETS = NewSheets()


@dataclass(frozen=True)
class _Copy:
    drive_modified: dt.datetime  # Drive's modifiedTime when the grid was read
    read_at: dt.datetime
    changed_at: dt.datetime  # when the app last saw the content differ
    grid: Json


class GSheetsBackend:
    """A `Repository` on a Google Sheet; without an ID, one that schema sync creates."""

    def __init__(
        self,
        spreadsheet_id: str | None,
        client: SheetsClient,
        *,
        max_age: dt.timedelta = MAX_AGE,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
        new_sheets: NewSheets = NEW_SHEETS,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.client = client
        self.max_age = max_age
        self.new_sheets = new_sheets
        self._clock = clock
        self._copy: _Copy | None = None

    @property
    def label(self) -> str:
        """How messages name the sheet: by its title once read, else by its ID."""
        if self._copy is not None:
            return f"Google Sheet '{self._copy.grid['properties']['title']}'"
        if self.spreadsheet_id is None:
            return "a new Google Sheet"
        return f"Google Sheet {self.spreadsheet_id}"

    def list_tables(self) -> list[str]:
        return [str(sheet["properties"]["title"]) for sheet in self._sheets()]

    def read_table(self, name: str) -> Table:
        return grid_table(name, grid_rows(self._sheet(name)))

    def read_formulas(self, name: str) -> Table:
        sheet, locale = self._sheet(name), self._locale()
        return grid_table(name, grid_rows(sheet, formulas=True, locale=locale))

    def read_kv(self, name: str) -> dict[str, RawCell]:
        return kv_pairs(name, grid_rows(self._sheet(name)))

    def last_modified(self) -> dt.datetime:
        """Drive's time, or when the app saw the content change if later; reads the sheet again
        when Drive says it changed or the copy is older than `max_age`."""
        drive, now, copy = self._drive_modified(), self._clock(), self._copy
        if copy is None or copy.drive_modified != drive or now - copy.read_at >= self.max_age:
            try:
                grid = self.client.get_grid(self._id())
            except GoogleNotFound:
                raise StorageError(f"workbook not found: {self.label}") from None
            changed = now if copy is None or grid != copy.grid else copy.changed_at
            self._copy = copy = _Copy(drive, now, changed, grid)
        return max(drive, copy.changed_at)

    def _id(self) -> str:
        if self.spreadsheet_id is None:
            raise StorageError(f"workbook not found: {self.label} is made by schema sync")
        return self.spreadsheet_id

    def _drive_modified(self) -> dt.datetime:
        try:
            return self.client.modified_time(self._id())
        except GoogleNotFound:
            if not self.exists():
                raise StorageError(f"workbook not found: {self.label}") from None
        raise StorageError(  # Drive shows the app only the files it created (D-062)
            f"{self.label} was not created by climb-log, so the app can't see when it changes: "
            "let the app create the module's sheet (#54)"
        )

    def exists(self) -> bool:
        if self.spreadsheet_id is None:
            return False
        try:
            self.client.title(self.spreadsheet_id)
        except GoogleNotFound:
            return False
        return True

    def apply(self, edits: Sequence[Edit]) -> list[int]:
        tabs = self._fresh_tabs()
        numbers = []
        for edit in edits:
            tab = self._tab(tabs, edit.tab)
            check_columns(edit.tab, tab.columns, edit.cells)
            if isinstance(edit, Append):
                number = tab.take_free()
            else:
                number = edit.row
                check_unchanged(edit, tab.row(number) if number >= FIRST_DATA_ROW else {})
            for key, value in edit.cells.items():
                tab.write(number, tab.columns[key], value)
            numbers.append(number)
        self._send([r for tab in tabs.values() for r in tab.requests()])
        return numbers

    def write_kv(self, name: str, values: Mapping[str, RawCell]) -> None:
        tab = self._tab(self._fresh_tabs(), name)
        k, v = kv_columns(name, tab.rows[0] if tab.rows else ())
        numbers: dict[str, int] = {}
        for number, row in enumerate(tab.rows[1:], start=2):
            key = row[k] if k < len(row) else None
            if not blank(key):
                numbers.setdefault(str(key).strip(), number)  # the first of a key wins
        end = len(tab.rows)
        for key, value in values.items():
            if key not in numbers:
                end += 1
                numbers[key] = end
            tab.write(numbers[key], k, key)
            tab.write(numbers[key], v, value)
        self._send(tab.requests())

    def sync_schema(self, layout: WorkbookLayout, meta: Mapping[str, RawCell]) -> list[str]:
        from climblog.storage.gsheets_sync import new_sheet_requests, sync_requests  # imports us

        created = self.spreadsheet_id is None
        if created:
            folder = self.client.folder(self.new_sheets.folder)
            self.spreadsheet_id = self.client.create_file(layout.title or layout.module, folder)
        try:
            try:
                book = self.client.get_layout(self._id())
            except GoogleNotFound:
                raise StorageError(f"workbook not found: {self.label}") from None
            locale = self.new_sheets.locale if created else None
            requests, done = sync_requests(book, layout, meta, locale=locale)
            if created:
                first, last = new_sheet_requests(
                    book, self.new_sheets.locale, self.new_sheets.time_zone
                )
                requests = first + requests + last
            self._send(requests)
        except BaseException:
            if created:  # no half-made sheet is left behind
                self.client.trash(self._id())
                self.spreadsheet_id = None
            raise
        return ["created the workbook", *done] if created else done

    # ---- Writing ----

    def _fresh_tabs(self) -> dict[str, "_Tab"]:
        """The tabs as Google has them now, for a write (not the cached copy)."""
        try:
            grid = self.client.get_grid(self._id())
        except GoogleNotFound:
            raise StorageError(f"workbook not found: {self.label}") from None
        return {str(sheet["properties"]["title"]): _Tab(sheet) for sheet in grid.get("sheets", [])}

    def _tab(self, tabs: Mapping[str, "_Tab"], name: str) -> "_Tab":
        if name not in tabs:
            raise TableNotFound(f"no tab '{name}' in {self.label}")
        return tabs[name]

    def _send(self, requests: list[Json]) -> None:
        """One `batchUpdate`: Google applies all of it or none. The copy is read again after."""
        if requests:
            try:
                self.client.batch_update(self._id(), requests)
            finally:
                self._copy = None

    # ---- Reading ----

    def _sheets(self) -> list[Json]:
        self.last_modified()  # reads the sheet again when due
        assert self._copy is not None
        sheets: list[Json] = self._copy.grid.get("sheets", [])
        return sorted(sheets, key=lambda sheet: sheet["properties"].get("index", 0))

    def _locale(self) -> str:
        assert self._copy is not None  # `_sheet` read it
        return str(self._copy.grid["properties"].get("locale", "en_US"))

    def _sheet(self, name: str) -> Json:
        for sheet in self._sheets():
            if sheet["properties"]["title"] == name:
                return sheet
        raise TableNotFound(f"no tab '{name}' in {self.label}")


def grid_rows(sheet: Mapping[str, Any], *, formulas: bool = False, locale: str = "en_US") -> Rows:
    """A tab of a `get_grid` response as rows of raw cells (row 1 first); with `formulas`, a
    formula cell gives its formula in en_US syntax (`=IF(...)`) instead of its value; `locale`
    is the spreadsheet's (`properties.locale`)."""
    comma = comma_decimal(locale)
    rows: Rows = []
    for data in sheet.get("data", []):  # one block: the whole tab was asked for
        for row in data.get("rowData", []):
            rows.append(tuple(_cell(value, formulas, comma) for value in row.get("values", [])))
    return rows


# Languages whose spreadsheets write 1,5 and separate arguments with `;` (Google follows the
# locale's decimal separator).
_COMMA_LANGUAGES = {
    "bg", "ca", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hr", "hu", "id", "it", "lt",
    "lv", "nb", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sr", "sv", "tr", "uk", "vi",
}  # fmt: skip


def comma_decimal(locale: str) -> bool:
    """Whether a spreadsheet locale (`it_IT`) writes formulas with decimal commas."""
    return locale.split("_")[0].casefold() in _COMMA_LANGUAGES


def en_formula(formula: str) -> str:
    """A formula in a decimal-comma locale's syntax in en_US syntax: outside "strings" and
    'tab names', `;` becomes `,` and `,` becomes `.`. A formula without `;` there is taken as
    en_US already (the app's own; a hand-typed one with a decimal comma and no `;` is the one
    case it gets wrong, and then shows as a changed formula)."""
    if ";" not in _outside_quotes(formula):
        return formula
    out, quote = [], ""
    for char in formula:
        if quote:
            quote = "" if char == quote else quote  # "" and '' reopen at once: still inside
        elif char in "\"'":
            quote = char
        elif char == ";":
            char = ","
        elif char == ",":
            char = "."
        out.append(char)
    return "".join(out)


def _outside_quotes(formula: str) -> str:
    out, quote = [], ""
    for char in formula:
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        else:
            out.append(char)
    return "".join(out)


def local_formula(formula: str) -> str:
    """An en_US formula in a decimal-comma locale's syntax, the inverse of `en_formula`: for
    the formulas of validation rules, which Google reads in the sheet's locale."""
    out, quote = [], ""
    for char in formula:
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == ",":
            char = ";"
        elif char == ".":
            char = ","
        out.append(char)
    return "".join(out)


def _cell(value: Mapping[str, Any], formulas: bool, comma: bool = False) -> RawCell:
    if formulas and "formulaValue" in value.get("userEnteredValue", {}):
        formula = str(value["userEnteredValue"]["formulaValue"])
        return en_formula(formula) if comma else formula
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


class _Tab:
    """A tab being written: its cells as read just before, and the cells to write."""

    def __init__(self, sheet: Json) -> None:
        props = sheet["properties"]
        self.sheet_id: int = props.get("sheetId", 0)
        self.row_count: int = props.get("gridProperties", {}).get("rowCount", 1000)
        self.rows = grid_rows(sheet)
        self.formulas = grid_rows(sheet, formulas=True)
        self.formats = [
            [
                value.get("effectiveFormat", {}).get("numberFormat")
                for value in row.get("values", [])
            ]
            for data in sheet.get("data", [])
            for row in data.get("rowData", [])
        ]
        self.columns = key_columns(props["title"], self.rows[1] if len(self.rows) > 1 else ())
        self.data = [i for key, i in self.columns.items() if not key.startswith(AUTO)]
        self.autos = [i for key, i in self.columns.items() if key.startswith(AUTO)]
        self.cells: dict[tuple[int, int], RawCell] = {}  # (row, column), 1-based row
        self.next_free = FIRST_DATA_ROW
        self.appended = False

    def row(self, number: int) -> dict[str, RawCell]:
        values = self.rows[number - 1] if number <= len(self.rows) else ()
        return {key: values[i] if i < len(values) else None for key, i in self.columns.items()}

    def take_free(self) -> int:
        """The next row an append may fill: one whose columns, `auto:` aside, are blank."""
        while self.next_free <= len(self.rows) and not self._free(self.next_free):
            self.next_free += 1
        self.next_free += 1
        self.appended = True
        return self.next_free - 1

    def _free(self, number: int) -> bool:
        values = self.rows[number - 1]
        return all(i >= len(values) or values[i] in (None, "") for i in self.data)

    def write(self, number: int, column: int, value: RawCell) -> None:
        self.cells[(number, column)] = value

    def requests(self) -> list[Json]:
        """More rows if needed, the cells, then the formula buffer's top-up."""
        top_up = self._top_up() if self.appended else []
        last = max([n for n, _ in self.cells] + [end for *_, end in top_up], default=0)
        requests: list[Json] = []
        if last > self.row_count:
            more = {"sheetId": self.sheet_id, "dimension": "ROWS", "length": last - self.row_count}
            requests.append({"appendDimension": more})
        for (number, column), value in sorted(self.cells.items()):
            cell, fields = _cell_data(value, self._format(number, column))
            start = {"sheetId": self.sheet_id, "rowIndex": number - 1, "columnIndex": column}
            update = {"rows": [{"values": [cell]}], "start": start, "fields": fields}
            requests.append({"updateCells": update})
        for column, source, end in top_up:
            requests.append({"copyPaste": {
                "source": self._range(source, source, column),
                "destination": self._range(source + 1, end, column),
                "pasteType": "PASTE_NORMAL",
            }})  # fmt: skip
        return requests

    def _top_up(self) -> list[tuple[int, int, int]]:
        """(column, last formula row, buffer end) for each formula column to extend (D-054)."""
        written = [n for (n, i) in self.cells if i in self.data]
        last_data = max([FIRST_DATA_ROW - 1, *written], default=0)
        sources = {}
        for number, values in enumerate(self.rows, start=1):
            if any(i < len(values) and not blank(values[i]) for i in self.data):
                last_data = max(last_data, number)
        for number, values in enumerate(self.formulas, start=1):
            for i in self.autos:
                if number >= FIRST_DATA_ROW and _is_formula(values, i):
                    sources[i] = number
        if not sources:
            return []
        end = formula_rows_end(last_data, max(sources.values()))
        return [(i, row, end) for i, row in sorted(sources.items()) if row < end]

    def _format(self, number: int, column: int) -> Json | None:
        row = self.formats[number - 1] if number <= len(self.formats) else []
        form = row[column] if column < len(row) else None
        return dict(form) if form else None

    def _range(self, first: int, last: int, column: int) -> Json:
        return {"sheetId": self.sheet_id, "startRowIndex": first - 1, "endRowIndex": last,
                "startColumnIndex": column, "endColumnIndex": column + 1}  # fmt: skip


def _is_formula(values: tuple[RawCell, ...], i: int) -> bool:
    return i < len(values) and isinstance(values[i], str) and str(values[i]).startswith("=")


def _cell_data(value: RawCell, current: Json | None) -> tuple[Json, str]:
    """The API's `CellData` for a value, and the fields to set: a string is a text cell (never a
    formula), a date or time a serial with a date format, unless the cell's own format is
    already of that kind; None clears the value."""
    if value is None:
        return {}, "userEnteredValue"
    if isinstance(value, str):
        entered: Json = {"stringValue": value}
        form: Json | None = _TEXT
        kind = "text"
    elif isinstance(value, bool):
        entered, form, kind = {"boolValue": value}, None, "bool"
    elif isinstance(value, int | float):
        entered, form, kind = {"numberValue": value}, None, "number"
    else:
        serial_number, form = serial(value)
        entered, kind = {"numberValue": serial_number}, "date"
    if current is not None and _KINDS.get(current.get("type", "")) == kind:
        return {"userEnteredValue": entered}, "userEnteredValue"  # the sheet's format is kept
    cell: Json = {"userEnteredValue": entered}
    if form is not None:
        cell["userEnteredFormat"] = {"numberFormat": form}
    return cell, "userEnteredValue,userEnteredFormat.numberFormat"


def serial(value: dt.date | dt.time | dt.timedelta) -> tuple[float, Json]:
    """A date, time or duration as a spreadsheet serial and its number format."""
    if isinstance(value, dt.datetime):
        return (value - _EPOCH) / _DAY, _DATE_TIME
    if isinstance(value, dt.date):
        return (value - _EPOCH.date()) / _DAY, DATE_FORMAT
    if isinstance(value, dt.time):
        return (dt.datetime.combine(_EPOCH.date(), value) - _EPOCH) / _DAY, _TIME
    return value / _DAY, _DURATION
