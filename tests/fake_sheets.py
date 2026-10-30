# SPDX-License-Identifier: GPL-3.0-or-later
"""An in-memory Google: a `SheetsClient` that keeps spreadsheets as the API's JSON (D-063).

`create` takes the body `spreadsheets.create` takes, so the test harness builds the same request
for this fake and for the real API (`spreadsheet_body`). Values typed in (`userEnteredValue`)
become the cell's value as Google would show it, except formulas, which get no computed value
(as in a workbook written by openpyxl). Every change moves `modifiedTime` on by a second.

`batch_update` knows the requests the backend sends, and like Google applies all of them or
none, and refuses cells outside the grid (`gridProperties`, 1000 rows and 26 columns for a new
tab). As on Google, formulas sent with `create` in a decimal-comma locale come back in its
syntax (`=IF(A3="";"";B3*1,5)`), those sent with `batch_update` as sent.
"""

import copy
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from climblog.storage import StorageError
from climblog.storage.google_client import GoogleNotFound, Json
from climblog.storage.gsheets import comma_decimal, local_formula

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
        self.folders: dict[str, str] = {}  # name → ID
        self.parents: dict[str, str] = {}  # spreadsheet ID → folder ID
        self._ids = 0

    def get_layout(self, spreadsheet_id: str) -> Json:
        book = self.get_grid(spreadsheet_id)
        self.calls[-1] = "get_layout"
        return book

    def folder(self, name: str) -> str:
        self.calls.append("folder")
        return self.folders.setdefault(name, f"folder-{len(self.folders) + 1}")

    def create_file(self, title: str, folder_id: str) -> str:
        """An empty spreadsheet, as Drive makes it: one tab, the account's locale."""
        self.calls.append("create_file")
        sheet = {"properties": {"sheetId": 0, "title": "Sheet1", "index": 0}}
        spreadsheet_id = self.create({"properties": {"title": title}, "sheets": [sheet]})
        self.calls.pop()
        self.parents[spreadsheet_id] = folder_id
        return spreadsheet_id

    def title(self, spreadsheet_id: str) -> str:
        self.calls.append("title")
        return str(self._book(spreadsheet_id)["properties"]["title"])

    def get_grid(self, spreadsheet_id: str) -> Json:
        self.calls.append("get_grid")
        return copy.deepcopy(self._book(spreadsheet_id))

    def modified_time(self, spreadsheet_id: str) -> dt.datetime:
        self.calls.append("modified_time")
        self._book(spreadsheet_id)
        if spreadsheet_id in self.unwatched:
            raise GoogleNotFound("not found on Google (File not found)")
        return self.modified[spreadsheet_id]

    def create(self, body: Mapping[str, Any]) -> str:
        self.calls.append("create")
        self._ids += 1
        spreadsheet_id = f"fake-{self._ids:04d}-{'x' * 30}"
        book = copy.deepcopy(dict(body))
        book["properties"].setdefault("locale", "en_US")
        for number, sheet in enumerate(book.get("sheets", []), start=1):
            props = sheet["properties"]
            props.setdefault("sheetId", number * 1000)
            props.setdefault("index", number - 1)
            rows = [row for data in sheet.get("data", []) for row in data.get("rowData", [])]
            for row in rows:
                row["values"] = [_typed(value) for value in row.get("values", [])]
                if comma_decimal(book["properties"]["locale"]):  # Google keeps them localized
                    for value in row["values"]:
                        entered = value.get("userEnteredValue", {})
                        if "formulaValue" in entered:
                            entered["formulaValue"] = local_formula(entered["formulaValue"])
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
        for r, row in enumerate(update["rows"], start=start["rowIndex"]):
            for c, value in enumerate(row["values"], start=start["columnIndex"]):
                _set(_cell(sheet, r, c), value, str(update["fields"]).split(","))

    def _repeatCell(self, book: Json, body: Mapping[str, Any]) -> None:
        cells = body["range"]
        sheet = _sheet(book, cells["sheetId"])
        grid = sheet["properties"]["gridProperties"]
        for r in range(cells.get("startRowIndex", 0), cells.get("endRowIndex", grid["rowCount"])):
            columns = range(
                cells.get("startColumnIndex", 0), cells.get("endColumnIndex", grid["columnCount"])
            )
            for c in columns:
                _set(_cell(sheet, r, c), body["cell"], str(body["fields"]).split(","))

    def _addSheet(self, book: Json, body: Mapping[str, Any]) -> None:
        props = copy.deepcopy(dict(body["properties"]))
        if any(s["properties"]["title"] == props["title"] for s in book["sheets"]):
            raise StorageError(f"Google answered 400: A sheet named '{props['title']}' exists")
        props["index"] = len(book["sheets"])
        grid = props.setdefault("gridProperties", {})
        grid.setdefault("rowCount", 1000)
        grid.setdefault("columnCount", 26)
        book["sheets"].append({"properties": props})

    def _deleteSheet(self, book: Json, body: Mapping[str, Any]) -> None:
        if len(book["sheets"]) == 1:
            raise StorageError("Google answered 400: can't delete the only sheet")
        book["sheets"].remove(_sheet(book, body["sheetId"]))
        for index, sheet in enumerate(book["sheets"]):
            sheet["properties"]["index"] = index

    def _updateSpreadsheetProperties(self, book: Json, body: Mapping[str, Any]) -> None:
        for name in str(body["fields"]).split(","):
            book["properties"][name] = body["properties"][name]

    def _updateDimensionProperties(self, book: Json, body: Mapping[str, Any]) -> None:
        cells = body["range"]
        dimensions = _sheet(book, cells["sheetId"]).setdefault("dimensions", {})
        for i in range(cells["startIndex"], cells["endIndex"]):
            done = dimensions.setdefault(f"{cells['dimension']}:{i}", {})
            for name in str(body["fields"]).split(","):
                done[name] = body["properties"][name]

    def _setDataValidation(self, book: Json, body: Mapping[str, Any]) -> None:
        cells = body["range"]
        rules = _sheet(book, cells["sheetId"]).setdefault("dataValidations", [])
        rules[:] = [rule for rule in rules if rule["range"] != cells]
        if "rule" in body:
            rules.append({"range": dict(cells), "rule": copy.deepcopy(body["rule"])})

    def _addConditionalFormatRule(self, book: Json, body: Mapping[str, Any]) -> None:
        rule = copy.deepcopy(body["rule"])
        sheet = _sheet(book, rule["ranges"][0]["sheetId"])
        sheet.setdefault("conditionalFormats", []).insert(body.get("index", 0), rule)

    def _deleteConditionalFormatRule(self, book: Json, body: Mapping[str, Any]) -> None:
        _sheet(book, body["sheetId"])["conditionalFormats"].pop(body["index"])

    def _addProtectedRange(self, book: Json, body: Mapping[str, Any]) -> None:
        protected = copy.deepcopy(body["protectedRange"])
        self._ids += 1
        protected["protectedRangeId"] = self._ids
        _sheet(book, protected["range"]["sheetId"]).setdefault("protectedRanges", []).append(
            protected
        )

    def _deleteProtectedRange(self, book: Json, body: Mapping[str, Any]) -> None:
        for sheet in book["sheets"]:
            ranges = sheet.get("protectedRanges", [])
            ranges[:] = [p for p in ranges if p["protectedRangeId"] != body["protectedRangeId"]]

    def _addNamedRange(self, book: Json, body: Mapping[str, Any]) -> None:
        named = copy.deepcopy(body["namedRange"])
        names = book.setdefault("namedRanges", [])
        if any(n["name"] == named["name"] for n in names):
            raise StorageError(f"Google answered 400: the name {named['name']} exists")
        self._ids += 1
        named["namedRangeId"] = str(self._ids)
        names.append(named)

    def _deleteNamedRange(self, book: Json, body: Mapping[str, Any]) -> None:
        names = book.get("namedRanges", [])
        names[:] = [n for n in names if n["namedRangeId"] != body["namedRangeId"]]

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


def _typed(value: Json) -> Json:
    """A typed-in cell with the value and format Google would show (formulas: no value)."""
    cell: Json = {}
    _set(cell, value, ["userEnteredValue", "userEnteredFormat", "note"])
    return cell


def _set(cell: Json, value: Json, fields: Sequence[str]) -> None:
    """Change the `fields` of a cell to those of `value` (a field `value` lacks is cleared)."""
    if "userEnteredValue" in fields:
        entered = value.get("userEnteredValue", {})
        for key in ("userEnteredValue", "effectiveValue"):
            cell.pop(key, None)
        if entered:
            cell["userEnteredValue"] = dict(entered)
            if "formulaValue" not in entered:
                cell["effectiveValue"] = dict(entered)
    form = value.get("userEnteredFormat", {})
    if "userEnteredFormat" in fields:
        cell.pop("userEnteredFormat", None)
        if form:
            cell["userEnteredFormat"] = copy.deepcopy(form)
    elif "userEnteredFormat.numberFormat" in fields:
        current = cell.setdefault("userEnteredFormat", {})
        current.pop("numberFormat", None)
        if "numberFormat" in form:
            current["numberFormat"] = dict(form["numberFormat"])
    number_format = cell.get("userEnteredFormat", {}).get("numberFormat")
    cell.pop("effectiveFormat", None)
    if number_format:
        cell["effectiveFormat"] = {"numberFormat": dict(number_format)}
    if "note" in fields:
        cell.pop("note", None)
        if "note" in value:
            cell["note"] = value["note"]
