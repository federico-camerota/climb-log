# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google Sheets and Drive APIs, over plain REST (04-storage.md §3, D-063).

`SheetsClient` is all the Google backend needs from Google; `RestSheetsClient` implements it
with google-auth's `AuthorizedSession` (requests), which adds the login and refreshes the access
token. The session is made on first use, so loading the app config never needs the network or a
login. The tests use an in-memory client that speaks the same JSON (`tests/fake_sheets.py`).
"""

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import requests

from climblog.storage.base import StorageError

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE = "https://www.googleapis.com/drive/v3/files"
# Each tab's values, number formats and formulas, in one response (D-063).
GRID_FIELDS = (
    "properties.title,sheets(properties(sheetId,title,index),data(rowData(values("
    "userEnteredValue,effectiveValue,effectiveFormat/numberFormat))))"
)
TIMEOUT = 30  # seconds

Json = dict[str, Any]


class GoogleNotFound(StorageError):
    """Google has no such spreadsheet, or none this login may see."""


class SheetsClient(Protocol):
    def title(self, spreadsheet_id: str) -> str:
        """The spreadsheet's title. Raises `GoogleNotFound`."""
        ...

    def get_grid(self, spreadsheet_id: str) -> Json:
        """The spreadsheet with every tab's cells (`GRID_FIELDS`). Raises `GoogleNotFound`."""
        ...

    def modified_time(self, spreadsheet_id: str) -> dt.datetime:
        """When Drive last saw the file change (local time). Raises `GoogleNotFound`."""
        ...

    def create(self, body: Mapping[str, Any]) -> str:
        """A new spreadsheet (`spreadsheets.create` body, tabs and cells included); its ID."""
        ...

    def batch_update(self, spreadsheet_id: str, requests: Sequence[Mapping[str, Any]]) -> Json:
        """`spreadsheets.batchUpdate`: Google applies all the requests or none."""
        ...

    def trash(self, spreadsheet_id: str) -> None:
        """Move the file to the Drive trash."""
        ...


class Session(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response: ...


class RestSheetsClient:
    """`SheetsClient` over HTTPS, with the session from `connect` (made on first use)."""

    def __init__(self, connect: Callable[[], Session]) -> None:
        self._connect = connect
        self._session: Session | None = None

    def title(self, spreadsheet_id: str) -> str:
        doc = self._call("GET", f"{SHEETS}/{spreadsheet_id}", params={"fields": "properties.title"})
        return str(doc["properties"]["title"])

    def get_grid(self, spreadsheet_id: str) -> Json:
        params = {"includeGridData": "true", "fields": GRID_FIELDS}
        return self._call("GET", f"{SHEETS}/{spreadsheet_id}", params=params)

    def modified_time(self, spreadsheet_id: str) -> dt.datetime:
        doc = self._call("GET", f"{DRIVE}/{spreadsheet_id}", params={"fields": "modifiedTime"})
        when = dt.datetime.fromisoformat(doc["modifiedTime"])  # RFC 3339, UTC
        return when.astimezone().replace(tzinfo=None)  # local, like a file's mtime

    def create(self, body: Mapping[str, Any]) -> str:
        return str(self._call("POST", SHEETS, json=dict(body))["spreadsheetId"])

    def batch_update(self, spreadsheet_id: str, requests: Sequence[Mapping[str, Any]]) -> Json:
        body = {"requests": [dict(r) for r in requests]}
        return self._call("POST", f"{SHEETS}/{spreadsheet_id}:batchUpdate", json=body)

    def trash(self, spreadsheet_id: str) -> None:
        self._call("PATCH", f"{DRIVE}/{spreadsheet_id}", json={"trashed": True})

    def _call(self, method: str, url: str, **kwargs: Any) -> Json:
        if self._session is None:
            self._session = self._connect()
        try:
            response = self._session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException:
            raise StorageError("cannot reach Google") from None
        if response.ok:
            doc = response.json() if response.content else {}
            return doc if isinstance(doc, dict) else {}
        status, message = response.status_code, _message(response)
        if status == 404:
            raise GoogleNotFound(f"not found on Google ({message})")
        if status == 401:
            raise StorageError("Google refused the login: run `climblog google login`")
        if status == 403:
            raise StorageError(f"Google refused access: {message}")
        raise StorageError(f"Google answered {status}: {message}")


def _message(response: requests.Response) -> str:
    """The `error.message` of a Google error response, else the HTTP reason."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.reason or "no details"
    return str(message)
