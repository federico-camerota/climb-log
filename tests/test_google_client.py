# SPDX-License-Identifier: GPL-3.0-or-later
"""The REST client for Sheets and Drive, with a fake session: what is asked of Google, and
how its answers and errors come back (04-storage.md §3, D-063). No network."""

import datetime as dt
import json
from typing import Any

import pytest
import requests

from climblog.storage import StorageError
from climblog.storage.google_client import (
    DRIVE,
    FOLDER,
    GRID_FIELDS,
    LAYOUT_FIELDS,
    RETRY_AFTER,
    SHEETS,
    SPREADSHEET,
    XLSX,
    GoogleNotFound,
    RestSheetsClient,
)

ID = "fictional-sheet-id-0123456789"


def response(status: int = 200, body: Any = None, reason: str = "") -> requests.Response:
    answer = requests.Response()
    answer.status_code, answer.reason = status, reason
    answer._content = b"" if body is None else json.dumps(body).encode()
    return answer


class FakeSession:
    """Answers with `answers` in turn (an exception is raised), and records each request and
    each wait."""

    def __init__(self, *answers: requests.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.waits: list[float] = []  # the client's sleeps between tries

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.requests.append((method, url, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def client(*answers: requests.Response | Exception) -> tuple[RestSheetsClient, FakeSession]:
    session = FakeSession(*answers)
    return RestSheetsClient(lambda: session, sleep=session.waits.append), session


def test_each_call_and_what_it_asks() -> None:
    sheets, session = client(
        response(body={"properties": {"title": "Journal"}}),
        response(body={"sheets": []}),
        response(body={"modifiedTime": "2026-10-29T15:04:05.123Z"}),
        response(body={"spreadsheetId": ID}),
        response(body={"spreadsheetId": ID, "replies": [{}]}),
        response(),  # an empty body
    )
    assert sheets.title(ID) == "Journal"
    assert sheets.get_grid(ID) == {"sheets": []}
    modified = sheets.modified_time(ID)
    utc = dt.datetime(2026, 10, 29, 15, 4, 5, 123000, tzinfo=dt.UTC)
    assert modified == utc.astimezone().replace(tzinfo=None)  # local time, naive
    assert sheets.create({"properties": {"title": "New"}}) == ID
    assert sheets.batch_update(ID, [{"updateCells": {}}])["replies"] == [{}]
    sheets.trash(ID)
    asked = [
        (method, url, kw.get("params"), kw.get("json")) for method, url, kw in session.requests
    ]
    assert asked == [
        ("GET", f"{SHEETS}/{ID}", {"fields": "properties.title"}, None),
        ("GET", f"{SHEETS}/{ID}", {"includeGridData": "true", "fields": GRID_FIELDS}, None),
        ("GET", f"{DRIVE}/{ID}", {"fields": "modifiedTime"}, None),
        ("POST", SHEETS, None, {"properties": {"title": "New"}}),
        ("POST", f"{SHEETS}/{ID}:batchUpdate", None, {"requests": [{"updateCells": {}}]}),
        ("PATCH", f"{DRIVE}/{ID}", None, {"trashed": True}),
    ]  # fmt: skip
    assert all(kwargs["timeout"] == 30 for _, _, kwargs in session.requests)


def test_layout_folders_and_new_files() -> None:
    sheets, session = client(
        response(body={"sheets": []}),
        response(body={"files": [{"id": "folder-1"}, {"id": "folder-2"}]}),
        response(body={"files": []}),
        response(body={"id": "folder-3"}),
        response(body={"id": ID}),
    )
    assert sheets.get_layout(ID) == {"sheets": []}
    assert sheets.folder("climb-log") == "folder-1"  # the oldest of the app's folders
    assert sheets.folder("it's") == "folder-3"  # none yet: made
    assert sheets.create_file("Journal", "folder-3") == ID
    asked = [(m, url, kw.get("params"), kw.get("json")) for m, url, kw in session.requests]
    query = f"mimeType='{FOLDER}' and name='{{}}' and trashed=false"
    find = {"fields": "files(id)", "orderBy": "createdTime"}
    assert asked == [
        ("GET", f"{SHEETS}/{ID}", {"includeGridData": "true", "fields": LAYOUT_FIELDS}, None),
        ("GET", DRIVE, {"q": query.format("climb-log"), **find}, None),
        ("GET", DRIVE, {"q": query.format("it\\'s"), **find}, None),
        ("POST", DRIVE, None, {"name": "it's", "mimeType": FOLDER}),
        (
            "POST",
            DRIVE,
            None,
            {"name": "Journal", "mimeType": SPREADSHEET, "parents": ["folder-3"]},
        ),
    ]


def test_export_as_xlsx() -> None:
    answer = response()
    answer._content = b"PK\x03\x04 fictional xlsx bytes"
    sheets, session = client(answer)
    assert sheets.export_xlsx(ID) == b"PK\x03\x04 fictional xlsx bytes"
    ((method, url, kwargs),) = session.requests
    assert (method, url, kwargs["params"]) == ("GET", f"{DRIVE}/{ID}/export", {"mimeType": XLSX})


def test_the_session_is_made_on_first_use_only() -> None:
    made: list[FakeSession] = []

    def connect() -> FakeSession:
        made.append(FakeSession(response(body={"sheets": []}), response(body={"sheets": []})))
        return made[-1]

    sheets = RestSheetsClient(connect)
    assert made == []  # building the client needs no login and no network
    sheets.get_grid(ID)
    sheets.get_grid(ID)
    assert len(made) == 1


def test_a_login_problem_comes_from_connect() -> None:
    def connect() -> FakeSession:
        raise StorageError("not logged in to Google: run `climblog google login`")

    with pytest.raises(StorageError, match="not logged in"):
        RestSheetsClient(connect).get_grid(ID)


ERROR = {"error": {"code": 0, "message": "Requested entity was not found.", "status": "X"}}


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        (response(404, ERROR), GoogleNotFound, r"not found on Google \(Requested entity"),
        (response(401, ERROR), StorageError, "refused the login: run `climblog google login`"),
        (response(403, {"error": {"message": "The caller does not have permission"}}),
         StorageError, "Google refused access: The caller does not have permission"),
        (response(500, None, "Internal Server Error"), StorageError,
         "Google answered 500: Internal Server Error"),
        (response(503, None), StorageError, "Google answered 503: no details"),
        (response(429, ERROR), StorageError, "quota is used up for now: try again in a minute"),
        (response(400, ERROR), StorageError, "Google answered 400: Requested entity"),
        (requests.ConnectionError("offline"), StorageError, "cannot reach Google"),
    ],
)  # fmt: skip
def test_errors(answer: requests.Response | Exception, error: type, message: str) -> None:
    sheets, _ = client(*[answer] * (len(RETRY_AFTER) + 1))  # 429 and 5xx are tried again
    with pytest.raises(error, match=message):
        sheets.get_grid(ID)


def test_busy_answers_are_tried_again() -> None:
    sheets, session = client(response(503), response(429), response(body={"sheets": []}))
    assert sheets.get_grid(ID) == {"sheets": []}
    assert len(session.requests) == 3
    assert session.waits == [1, 2]


def test_tries_stop_after_the_last_wait() -> None:
    sheets, session = client(*[response(500)] * 10)
    with pytest.raises(StorageError, match="Google answered 500"):
        sheets.batch_update(ID, [])
    assert session.waits == [1, 2, 4, 8, 16]
    assert len(session.requests) == 6


def test_other_errors_are_not_tried_again() -> None:
    sheets, session = client(response(400, ERROR), requests.ConnectionError("offline"))
    with pytest.raises(StorageError, match="400"):
        sheets.get_grid(ID)
    with pytest.raises(StorageError, match="cannot reach Google"):
        sheets.get_grid(ID)
    assert len(session.requests) == 2
    assert session.waits == []


def test_a_body_that_is_not_an_object_is_empty() -> None:
    sheets, _ = client(response(body=["unexpected"]))
    assert sheets.get_grid(ID) == {}
