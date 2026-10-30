# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google Sheets and Drive APIs, over plain REST (04-storage.md §3, D-063).

`SheetsClient` is all the Google backend needs from Google; `RestSheetsClient` implements it
with google-auth's `AuthorizedSession` (requests), which adds the login and refreshes the access
token. The session is made on first use, so loading the app config never needs the network or a
login. The tests use an in-memory client that speaks the same JSON (`tests/fake_sheets.py`).

Google's quota (about 60 write requests a minute) answers 429 when exceeded, and its servers
sometimes answer 5xx: such calls are tried again after 1, 2, 4, 8 and 16 seconds (D-064). Every
write is to fixed cells, so doing one twice gives the same sheet.
"""

import datetime as dt
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import requests

from climblog.storage.base import StorageError

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE = "https://www.googleapis.com/drive/v3/files"
# Each tab's values, number formats and formulas, in one response (D-063).
GRID_FIELDS = (
    "properties(title,locale),"
    "sheets(properties(sheetId,title,index,gridProperties(rowCount,columnCount)),"
    "data(rowData(values(userEnteredValue,effectiveValue,effectiveFormat/numberFormat))))"
)
# What schema sync needs besides the cells: rules, protections and named ranges (D-065).
LAYOUT_FIELDS = (
    "properties(title,locale),namedRanges(namedRangeId,name),"
    "sheets(properties(sheetId,title,index,gridProperties(rowCount,columnCount)),"
    "conditionalFormats,protectedRanges(protectedRangeId,description),"
    "data(rowData(values(userEnteredValue,effectiveValue,effectiveFormat/numberFormat))))"
)
FOLDER = "application/vnd.google-apps.folder"
SPREADSHEET = "application/vnd.google-apps.spreadsheet"
TIMEOUT = 30  # seconds
RETRY_AFTER = (1, 2, 4, 8, 16)  # seconds to wait before each new try (429 and 5xx)
_RETRY = {429, 500, 502, 503, 504}

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

    def get_layout(self, spreadsheet_id: str) -> Json:
        """`get_grid` with each tab's conditional formats and protected ranges, and the named
        ranges (`LAYOUT_FIELDS`), for schema sync. Raises `GoogleNotFound`."""
        ...

    def modified_time(self, spreadsheet_id: str) -> dt.datetime:
        """When Drive last saw the file change (local time). Raises `GoogleNotFound`."""
        ...

    def folder(self, name: str) -> str:
        """The ID of the app's Drive folder of that name in My Drive, made if missing."""
        ...

    def create_file(self, title: str, folder_id: str) -> str:
        """A new, empty spreadsheet in that folder; its ID."""
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

    def __init__(
        self, connect: Callable[[], Session], *, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._connect = connect
        self._sleep = sleep
        self._session: Session | None = None

    def title(self, spreadsheet_id: str) -> str:
        doc = self._call("GET", f"{SHEETS}/{spreadsheet_id}", params={"fields": "properties.title"})
        return str(doc["properties"]["title"])

    def get_grid(self, spreadsheet_id: str) -> Json:
        params = {"includeGridData": "true", "fields": GRID_FIELDS}
        return self._call("GET", f"{SHEETS}/{spreadsheet_id}", params=params)

    def get_layout(self, spreadsheet_id: str) -> Json:
        params = {"includeGridData": "true", "fields": LAYOUT_FIELDS}
        return self._call("GET", f"{SHEETS}/{spreadsheet_id}", params=params)

    def folder(self, name: str) -> str:
        # `drive.file` shows only the folders the app made, so a folder of the same name made
        # by hand is not found and a new one is made beside it.
        query = f"mimeType='{FOLDER}' and name='{_quoted(name)}' and trashed=false"
        params = {"q": query, "fields": "files(id)", "orderBy": "createdTime"}
        found = self._call("GET", DRIVE, params=params).get("files", [])
        if found:
            return str(found[0]["id"])
        return str(self._call("POST", DRIVE, json={"name": name, "mimeType": FOLDER})["id"])

    def create_file(self, title: str, folder_id: str) -> str:
        body = {"name": title, "mimeType": SPREADSHEET, "parents": [folder_id]}
        return str(self._call("POST", DRIVE, json=body)["id"])

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
        for wait in (*RETRY_AFTER, None):
            try:
                response = self._session.request(method, url, timeout=TIMEOUT, **kwargs)
            except requests.RequestException:
                raise StorageError("cannot reach Google") from None
            if response.status_code not in _RETRY or wait is None:
                break
            self._sleep(wait)
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
        if status == 429:
            raise StorageError("Google's quota is used up for now: try again in a minute")
        raise StorageError(f"Google answered {status}: {message}")


def _quoted(text: str) -> str:
    """Text inside '…' in a Drive query."""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _message(response: requests.Response) -> str:
    """The `error.message` of a Google error response, else the HTTP reason."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.reason or "no details"
    return str(message)
