# SPDX-License-Identifier: GPL-3.0-or-later
"""An in-memory Google: a `SheetsClient` that keeps spreadsheets as the API's JSON (D-063).

`create` takes the body `spreadsheets.create` takes, so the test harness builds the same request
for this fake and for the real API (`spreadsheet_body`). Values typed in (`userEnteredValue`)
become the cell's value as Google would show it, except formulas, which get no computed value
(as in a workbook written by openpyxl). Every change moves `modifiedTime` on by a second.
"""

import copy
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from climblog.storage.google_client import GoogleNotFound, Json

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
        return copy.deepcopy(self._book(spreadsheet_id))

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
            sheet["properties"].setdefault("sheetId", number * 1000)
            for data in sheet.get("data", []):
                for row in data.get("rowData", []):
                    row["values"] = [_typed(value) for value in row.get("values", [])]
        self.books[spreadsheet_id] = book
        self.modified[spreadsheet_id] = START
        return spreadsheet_id

    def batch_update(self, spreadsheet_id: str, requests: Sequence[Mapping[str, Any]]) -> Json:
        """Only `updateCells` with `start`, as the test harness sends it."""
        self.calls.append("batch_update")
        book = self._book(spreadsheet_id)
        for request in requests:
            update = request["updateCells"]
            start = update["start"]
            sheet = next(
                s for s in book["sheets"] if s["properties"]["sheetId"] == start["sheetId"]
            )
            if not sheet.get("data"):
                sheet["data"] = [{"rowData": []}]
            grid = sheet["data"][0]["rowData"]
            for offset, row in enumerate(update["rows"]):
                r = start["rowIndex"] + offset
                while len(grid) <= r:
                    grid.append({})
                values = grid[r].setdefault("values", [])
                for c_offset, value in enumerate(row["values"]):
                    c = start["columnIndex"] + c_offset
                    while len(values) <= c:
                        values.append({})
                    values[c] = _typed(value)
        self.modified[spreadsheet_id] += dt.timedelta(seconds=1)
        return {"spreadsheetId": spreadsheet_id}

    def trash(self, spreadsheet_id: str) -> None:
        self.calls.append("trash")
        self.books.pop(spreadsheet_id, None)

    def _book(self, spreadsheet_id: str) -> Json:
        if spreadsheet_id not in self.books:
            raise GoogleNotFound("not found on Google (Requested entity was not found.)")
        return self.books[spreadsheet_id]


def _typed(value: Json) -> Json:
    """A typed-in cell with the value and format Google would show (formulas: no value)."""
    entered = value.get("userEnteredValue", {})
    cell = {"userEnteredValue": dict(entered)} if entered else {}
    if entered and "formulaValue" not in entered:
        cell["effectiveValue"] = dict(entered)
    if form := value.get("userEnteredFormat", {}).get("numberFormat"):
        cell["effectiveFormat"] = {"numberFormat": dict(form)}
    return cell
