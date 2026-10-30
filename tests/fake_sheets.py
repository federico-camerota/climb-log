# SPDX-License-Identifier: GPL-3.0-or-later
"""An in-memory Google: a `SheetsClient` that keeps spreadsheets as the API's JSON (D-063).

`create` takes the body `spreadsheets.create` takes, so the test harness builds the same request
for this fake and for the real API (`spreadsheet_body`). Values typed in (`userEnteredValue`)
become the cell's value as Google would show it, except formulas, which get no computed value
(as in a workbook written by openpyxl). Every change moves `modifiedTime` on by a second.

`batch_update` knows the requests the backend sends, and like Google applies all of them or
none, and refuses cells outside the grid (`gridProperties`, 1000 rows and 26 columns for a new
tab). In a decimal-comma locale (`properties.locale`), formulas come back in its syntax, as from
Google: `=IF(A3="";"";B3*1,5)`.
"""

import copy
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from climblog.storage import StorageError
from climblog.storage.google_client import GoogleNotFound, Json
from climblog.storage.gsheets import comma_decimal

_EPOCH = dt.datetime(1899, 12, 30)
START = dt.datetime(2026, 10, 1, 9, 0)


def cell_data(value: Any) -> Json:
    """A Python value as the API's `CellData` to type into a cell (`=…` text is a formula)."""
    if value is None:
        return {}
    if isinstance(value, str):
        kind = "formulaValue" if value.startswith("=") else "stringValue"
        return {"userEnteredValue": {kind: value}}
    if isinstance(value, bool):
        return {"userEnteredValue": {"boolValue": value}}
    if isinstance(value, int | float):
        return {"userEnteredValue": {"numberValue": value}}
    if (dated := _dated(value)) is None:
        raise TypeError(f"no cell for {value!r}")
    kind, pattern, serial = dated
    return {
        "userEnteredValue": {"numberValue": serial},
        "userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}},
    }


def _dated(value: Any) -> tuple[str, str, float] | None:
    """A date, time or duration as its number format type, a pattern and its serial."""
    day = dt.timedelta(days=1)
    if isinstance(value, dt.datetime):
        return "DATE_TIME", "yyyy-mm-dd hh:mm:ss", (value - _EPOCH) / day
    if isinstance(value, dt.date):
        return "DATE", "yyyy-mm-dd", (value - _EPOCH.date()) / day
    if isinstance(value, dt.time):
        return "TIME", "hh:mm:ss", (dt.datetime.combine(dt.date.min, value) - dt.datetime.min) / day
    if isinstance(value, dt.timedelta):
        return "TIME", "[h]:mm:ss", value / day
    return None


def spreadsheet_body(title: str, tabs: Mapping[str, Sequence[Sequence[Any]]]) -> Json:
    """A `spreadsheets.create` body with these tabs, in order, and their cells."""
    return {
        "properties": {"title": title},
        "sheets": [
            {
                "properties": {"title": name, "index": index},
                "data": [
                    {
                        "startRow": 0,
                        "startColumn": 0,
                        "rowData": [{"values": [cell_data(v) for v in row]} for row in rows],
                    }
                ],
            }
            for index, (name, rows) in enumerate(tabs.items())
        ],
    }


class FakeSheetsClient:
    """A `SheetsClient` in memory. `unwatched` IDs exist for Sheets but not for Drive, like
    sheets the app didn't create under the `drive.file` scope (D-062)."""

    def __init__(self) -> None:
        self.books: dict[str, Json] = {}
        self.modified: dict[str, dt.datetime] = {}
        self.unwatched: set[str] = set()
        self.calls: list[str] = []

    def title(self, spreadsheet_id: str) -> str:
        self.calls.append("title")
        return str(self._book(spreadsheet_id)["properties"]["title"])

    def get_grid(self, spreadsheet_id: str) -> Json:
        self.calls.append("get_grid")
        book = copy.deepcopy(self._book(spreadsheet_id))
        if comma_decimal(book["properties"].get("locale", "en_US")):
            for sheet in book.get("sheets", []):
                for data in sheet.get("data", []):
                    for row in data.get("rowData", []):
                        for value in row.get("values", []):
                            entered = value.get("userEnteredValue", {})
                            if "formulaValue" in entered:
                                entered["formulaValue"] = _localized(entered["formulaValue"])
        return book

    def modified_time(self, spreadsheet_id: str) -> dt.datetime:
        self.calls.append("modified_time")
        self._book(spreadsheet_id)
        if spreadsheet_id in self.unwatched:
            raise GoogleNotFound("not found on Google (File not found)")
        return self.modified[spreadsheet_id]

    def create(self, body: Mapping[str, Any]) -> str:
        self.calls.append("create")
        spreadsheet_id = f"fake-{len(self.books) + 1:04d}-{'x' * 30}"
        book = copy.deepcopy(dict(body))
        for number, sheet in enumerate(book.get("sheets", []), start=1):
            props = sheet["properties"]
            props.setdefault("sheetId", number * 1000)
            rows = [row for data in sheet.get("data", []) for row in data.get("rowData", [])]
            for row in rows:
                row["values"] = [_typed(value) for value in row.get("values", [])]
            grid = props.setdefault("gridProperties", {})
            grid.setdefault("rowCount", max(1000, len(rows)))
            width = max((len(row["values"]) for row in rows), default=0)
            grid.setdefault("columnCount", max(26, width))
        self.books[spreadsheet_id] = book
        self.modified[spreadsheet_id] = START
        return spreadsheet_id

    def batch_update(self, spreadsheet_id: str, requests: Sequence[Mapping[str, Any]]) -> Json:
        self.calls.append("batch_update")
        book = copy.deepcopy(self._book(spreadsheet_id))  # all or nothing
        for request in requests:
            (kind, body), *_ = request.items()
            getattr(self, f"_{kind}")(book, body)
        self.books[spreadsheet_id] = book
        self.modified[spreadsheet_id] += dt.timedelta(seconds=1)
        return {"spreadsheetId": spreadsheet_id}

    def _updateCells(self, book: Json, update: Mapping[str, Any]) -> None:
        start = update["start"]
        sheet = _sheet(book, start["sheetId"])
        fields = str(update["fields"]).split(",")
        for r, row in enumerate(update["rows"], start=start["rowIndex"]):
            for c, value in enumerate(row["values"], start=start["columnIndex"]):
                cell = _cell(sheet, r, c)
                new = _typed(value)
                if "userEnteredValue" in fields:
                    for key in ("userEnteredValue", "effectiveValue"):
                        cell.pop(key, None)
                        if key in new:
                            cell[key] = new[key]
                if any(f.startswith("userEnteredFormat") for f in fields):
                    cell.pop("effectiveFormat", None)
                    if "effectiveFormat" in new:
                        cell["effectiveFormat"] = new["effectiveFormat"]

    def _appendDimension(self, book: Json, body: Mapping[str, Any]) -> None:
        grid = _sheet(book, body["sheetId"])["properties"]["gridProperties"]
        grid["rowCount" if body["dimension"] == "ROWS" else "columnCount"] += body["length"]

    def _copyPaste(self, book: Json, body: Mapping[str, Any]) -> None:
        """Repeats the source over the destination, moving relative references (one column)."""
        source, target = body["source"], body["destination"]
        sheet = _sheet(book, source["sheetId"])
        c = source["startColumnIndex"]
        assert source["endColumnIndex"] == c + 1 and target["startColumnIndex"] == c
        height = source["endRowIndex"] - source["startRowIndex"]
        for r in range(target["startRowIndex"], target["endRowIndex"]):
            r0 = source["startRowIndex"] + (r - target["startRowIndex"]) % height
            original = copy.deepcopy(_cell(sheet, r0, c))
            entered = original.get("userEnteredValue", {})
            if "formulaValue" in entered:
                letter = get_column_letter(c + 1)
                moved = Translator(entered["formulaValue"], origin=f"{letter}{r0 + 1}")
                entered["formulaValue"] = moved.translate_formula(f"{letter}{r + 1}")
            cell = _cell(sheet, r, c)
            cell.clear()
            cell.update(original)

    def trash(self, spreadsheet_id: str) -> None:
        self.calls.append("trash")
        self.books.pop(spreadsheet_id, None)

    def _book(self, spreadsheet_id: str) -> Json:
        if spreadsheet_id not in self.books:
            raise GoogleNotFound("not found on Google (Requested entity was not found.)")
        return self.books[spreadsheet_id]


def _sheet(book: Json, sheet_id: int) -> Json:
    return next(s for s in book["sheets"] if s["properties"]["sheetId"] == sheet_id)


def _cell(sheet: Json, r: int, c: int) -> Json:
    """The cell at 0-based (r, c), made if missing; outside the grid is Google's error."""
    grid = sheet["properties"]["gridProperties"]
    if r >= grid["rowCount"] or c >= grid["columnCount"]:
        raise StorageError(f"Google answered 400: Range ({r}, {c}) exceeds grid limits")
    if not sheet.get("data"):
        sheet["data"] = [{"rowData": []}]
    rows = sheet["data"][0].setdefault("rowData", [])
    while len(rows) <= r:
        rows.append({})
    values = rows[r].setdefault("values", [])
    while len(values) <= c:
        values.append({})
    cell: Json = values[c]
    return cell


def _localized(formula: str) -> str:
    """An en_US formula in a decimal-comma locale's syntax (no quotes handled: test formulas)."""
    return formula.replace(",", ";").replace(".", ",")


def _typed(value: Json) -> Json:
    """A typed-in cell with the value and format Google would show (formulas: no value)."""
    entered = value.get("userEnteredValue", {})
    cell = {"userEnteredValue": dict(entered)} if entered else {}
    if entered and "formulaValue" not in entered:
        cell["effectiveValue"] = dict(entered)
    if form := value.get("userEnteredFormat", {}).get("numberFormat"):
        cell["effectiveFormat"] = {"numberFormat": dict(form)}
    return cell
