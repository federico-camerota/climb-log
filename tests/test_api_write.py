# SPDX-License-Identifier: GPL-3.0-or-later
"""The write API on every backend: add, read one, update and soft delete journal records over
HTTP, and the errors a client acts on (D-075). Fictional data only."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from backends import Backend
from fastapi.testclient import TestClient
from openpyxl.utils import get_column_letter

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.main import create_app
from climblog.modules import load_module
from climblog.storage import CachedRepository, Repository, Snapshots, XlsxBackend, sync_module

CONTRACT = "write"
JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
SESSIONS = "/api/modules/journal/session"
RECORD = f"{SESSIONS}/record"
PRE = {"date": "2026-10-30", "session_type": "Climbing", "venue": "[ESEMPIO] Palestra Nord"}


@pytest.fixture
def repo(backend: Backend) -> Repository:
    """An empty journal workbook, made by schema sync."""
    made = backend.new()
    sync_module(JOURNAL, made)
    return made


@pytest.fixture
def client(repo: Repository, tmp_path: Path) -> Iterator[TestClient]:
    catalog = Catalog(AppConfig())
    snapshots = Snapshots(tmp_path / "snapshots")
    cached = CachedRepository("journal", repo, snapshots)
    catalog.entries["journal"] = Entry("journal", JOURNAL, [], cached)
    yield TestClient(create_app(catalog=catalog))


def add(client: TestClient, **values: Any) -> dict[str, Any]:
    response = client.post(SESSIONS, json={"values": PRE | values})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_session_is_added_and_read_back(client: TestClient) -> None:
    body = add(client, wb_mood_pre=7, notes="[ESEMPIO] Più riposo, è andata così")
    record = body["record"]
    assert record["values"]["date"] == "2026-10-30"
    assert record["values"]["session_no"] == 1  # the key's default
    assert record["values"]["notes"] == "[ESEMPIO] Più riposo, è andata così"  # raw UTF-8
    assert set(record["rows"]) == {"Session", "Wellbeing"}  # a row only where there are values
    assert record["derived"]["log_check"].startswith("Missing: ")
    assert body["as_of"] is not None

    listed = client.get(SESSIONS).json()["records"]
    assert [r["values"]["venue"] for r in listed] == ["[ESEMPIO] Palestra Nord"]
    one = client.get(RECORD, params={"date": "2026-10-30"}).json()
    assert one["record"] == record


def test_a_second_session_on_the_same_day(client: TestClient) -> None:
    add(client)
    second = add(client, session_no=2, session_type="Hangboard")["record"]
    assert second["values"]["session_no"] == 2
    one = client.get(RECORD, params={"date": "2026-10-30", "session_no": "2"}).json()
    assert one["record"]["values"]["session_type"] == "Hangboard"
    assert len(client.get(SESSIONS).json()["records"]) == 2


def test_a_taken_key_is_a_conflict(client: TestClient) -> None:
    add(client)
    response = client.post(SESSIONS, json={"values": PRE})
    assert response.status_code == 409
    assert response.json()["detail"]["message"].startswith(
        "Session already has a row for date 2026-10-30"
    )


@pytest.mark.parametrize(
    ("values", "field", "message"),
    [
        ({"wb_mood_pre": 11}, "wb_mood_pre", "wb_mood_pre: 11 is above the maximum 10"),
        ({"mood": 5}, "mood", "Session has no field mood"),
        ({"date": None}, "date", "no date: a session needs one"),
        ({"session_type": "Yoga"}, "session_type", "session_type: "),
    ],
)
def test_bad_values_name_the_field(
    client: TestClient, values: dict[str, Any], field: str, message: str
) -> None:
    response = client.post(SESSIONS, json={"values": PRE | values})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["field"] == field
    assert detail["message"].startswith(message)
    assert client.get(SESSIONS).json()["records"] == []  # nothing written


def test_every_bad_value_is_named(client: TestClient) -> None:
    values = PRE | {"wb_mood_pre": 11, "session_type": "Yoga"}
    detail = client.post(SESSIONS, json={"values": values}).json()["detail"]
    assert [p["field"] for p in detail["problems"]] == ["session_type", "wb_mood_pre"]
    assert detail["field"] == "session_type"  # the first, as before
    assert detail["problems"][1]["message"] == "wb_mood_pre: 11 is above the maximum 10"


def test_post_completes_the_session(client: TestClient) -> None:
    add(client, wb_mood_pre=7)
    response = client.patch(
        RECORD,
        params={"date": "2026-10-30", "session_no": "1"},
        json={"values": {"wb_mood_post": 8, "duration_min": "1:30", "feel_enjoyment": 9}},
    )
    assert response.status_code == 200, response.text
    record = response.json()["record"]
    assert record["values"]["wb_mood_pre"] == 7  # kept
    assert record["values"]["duration_min"] == 90
    assert {"Session", "Wellbeing", "Session Feel"} <= set(record["rows"])


def test_a_field_changed_since_it_was_read_is_a_conflict(
    client: TestClient, backend: Backend, repo: Repository
) -> None:
    add(client)
    read = client.get(RECORD, params={"date": "2026-10-30"}).json()["record"]["values"]
    backend.edit(repo, "Session", _cell(backend, repo, "Session", "venue", 3), "Altrove")

    stale = {"values": {"notes": "[ESEMPIO] ok"}, "expected": read}
    response = client.patch(RECORD, params={"date": "2026-10-30"}, json=stale)
    assert response.status_code == 409
    assert response.json()["detail"]["message"].startswith("venue has changed since it was read")

    fresh = client.get(RECORD, params={"date": "2026-10-30"}).json()["record"]["values"]
    response = client.patch(RECORD, params={"date": "2026-10-30"}, json=stale | {"expected": fresh})
    assert response.status_code == 200
    assert response.json()["record"]["values"]["venue"] == "Altrove"  # the hand edit is kept


def test_update_errors(client: TestClient) -> None:
    add(client)
    missing = client.patch(RECORD, params={"date": "2026-10-31"}, json={"values": {}})
    assert missing.status_code == 404
    assert missing.json()["detail"]["message"] == "no session for date 2026-10-31, session_no 1"
    no_key = client.patch(RECORD, json={"values": {"notes": "x"}})
    assert (no_key.status_code, no_key.json()["detail"]["field"]) == (422, "date")
    rekey = client.patch(
        RECORD, params={"date": "2026-10-30"}, json={"values": {"date": "2026-10-29"}}
    )
    assert (rekey.status_code, rekey.json()["detail"]["field"]) == (422, "date")
    assert client.get(RECORD, params={"date": "2026-10-31"}).status_code == 404


def test_a_session_is_soft_deleted(client: TestClient) -> None:
    add(client, wb_mood_pre=7)
    response = client.delete(RECORD, params={"date": "2026-10-30"})
    assert response.status_code == 204
    assert client.get(SESSIONS).json()["records"] == []
    assert client.get(RECORD, params={"date": "2026-10-30"}).status_code == 404
    add(client)  # the key is free again


def test_a_rest_day(client: TestClient) -> None:
    body = {"values": {"date": "31/10/2026", "rest_type": "Full rest", "mood": 8}}  # day first
    response = client.post("/api/modules/journal/rest_day", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["record"]["values"]["date"] == "2026-10-31"
    assert response.json()["record"]["derived"]["weekday"] == "Sat"


def test_unknown_module_and_entity(client: TestClient) -> None:
    assert client.post("/api/modules/nope/session", json={"values": {}}).status_code == 404
    assert client.post("/api/modules/journal/falls", json={"values": {}}).status_code == 404


def _cell(backend: Backend, repo: Repository, tab: str, column: str, row: int) -> str:
    keys = backend.cells(repo, tab)[1]  # row 2: the column keys
    return f"{get_column_letter(keys.index(column) + 1)}{row}"


# ---- Local workbooks only ----


@pytest.fixture
def local(tmp_path: Path) -> tuple[Path, TestClient]:
    path = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(path))
    catalog = Catalog(AppConfig())
    cached = CachedRepository("journal", XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
    catalog.entries["journal"] = Entry("journal", JOURNAL, [], cached)
    return path, TestClient(create_app(catalog=catalog))


def test_a_workbook_open_in_excel_is_locked(local: tuple[Path, TestClient]) -> None:
    path, client = local
    (path.parent / f"~${path.name}").write_text("")
    response = client.post(SESSIONS, json={"values": PRE})
    assert response.status_code == 423
    assert "open" in response.json()["detail"]["message"]


def test_offline_is_read_only(local: tuple[Path, TestClient]) -> None:
    path, client = local
    add(client)  # a snapshot is taken on the read back
    path.rename(path.with_suffix(".away"))
    response = client.post(SESSIONS, json={"values": PRE | {"date": "2026-10-31"}})
    assert response.status_code == 503
    assert "can't be saved now" in response.json()["detail"]["message"]
    listed = client.get(SESSIONS).json()
    assert listed["offline"] is True
    assert len(listed["records"]) == 1
    assert isinstance(dt.datetime.fromisoformat(listed["as_of"]), dt.datetime)
