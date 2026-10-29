# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google backend's reading, on an in-memory Google (04-storage.md §3, D-063).

What every backend does is in the contract tests (`test_backend_read.py`); here, what is
particular to Google: cell types from number formats, caching on Drive's `modifiedTime`, sheets
the app didn't create, and writes refused until #52/#53.
"""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml
from fake_sheets import FakeSheetsClient, cell_data, spreadsheet_body
from workbooks import SYNC_MODULE, tab

from climblog.storage import (
    CachedRepository,
    GSheetsBackend,
    Snapshots,
    StorageError,
    workbook_layout,
)
from climblog.storage.google_client import GoogleNotFound, Json
from climblog.storage.gsheets import grid_rows

D20 = dt.datetime(2026, 10, 20)


@pytest.fixture
def client() -> FakeSheetsClient:
    return FakeSheetsClient()


def book(client: FakeSheetsClient, keys: list[str], *rows: list[object]) -> GSheetsBackend:
    spreadsheet_id = client.create(spreadsheet_body("Journal", {"T": tab(keys, *rows)}))
    return GSheetsBackend(spreadsheet_id, client)


def test_cells_come_back_as_openpyxl_gives_them(client: FakeSheetsClient) -> None:
    repo = book(
        client,
        ["day", "at", "start", "rest", "kg", "reps", "ok", "note"],
        [dt.date(2026, 10, 20), dt.datetime(2026, 10, 20, 18, 30), dt.time(18, 30),
         dt.timedelta(hours=1, minutes=30), 12.5, 3.0, True, "Più riposo"],
    )  # fmt: skip
    (row,) = repo.read_table("T").rows
    assert row.cells == {
        "day": D20,  # a date cell is a datetime, as from openpyxl
        "at": dt.datetime(2026, 10, 20, 18, 30),
        "start": dt.time(18, 30),
        "rest": dt.timedelta(hours=1, minutes=30),
        "kg": 12.5,
        "reps": 3,
        "ok": True,
        "note": "Più riposo",
    }
    assert type(row.cells["reps"]) is int


def test_values_google_computed() -> None:
    def value(effective: dict[str, object], form: dict[str, str] | None = None) -> object:
        cell: dict[str, object] = {"effectiveValue": effective}
        if form:
            cell["effectiveFormat"] = {"numberFormat": form}
        sheet = {"data": [{"rowData": [{"values": [cell]}]}]}
        return grid_rows(sheet)[0][0]

    assert value({"errorValue": {"type": "DIVIDE_BY_ZERO", "message": "…"}}) == "#DIV/0!"
    assert value({"errorValue": {"type": "N_A"}}) == "#N/A"
    assert value({"errorValue": {"type": "SOMETHING_NEW"}}) == "#ERROR!"
    assert value({"stringValue": ""}) == ""  # a formula's "" result: blank to the tables
    assert value({}) is None
    assert value({"formattedValue": "?"}) is None  # no value of a kind we know
    assert value({"numberValue": 0.25}, {"type": "TIME", "pattern": "hh:mm"}) == dt.time(6)
    assert value({"numberValue": 1.25}, {"type": "TIME", "pattern": "[H]:MM"}) == dt.timedelta(
        hours=30
    )
    noisy = 46315.770833333336  # 2026-10-20 18:30 with float noise
    assert value({"numberValue": noisy}, {"type": "DATE_TIME"}) == dt.datetime(2026, 10, 20, 18, 30)
    assert value({"numberValue": 75}, {"type": "PERCENT"}) == 75
    assert grid_rows({}) == []
    assert grid_rows({"data": [{"rowData": [{}, {"values": [{}]}]}]}) == [(), (None,)]


def test_formulas_as_text(client: FakeSheetsClient) -> None:
    repo = book(client, ["date", "auto:double"], [D20, '=IF(A3="","",B3*2)'])
    assert repo.read_table("T").rows[0].cells == {"date": D20}  # no value computed yet
    assert repo.read_formulas("T").rows[0].cells == {
        "date": D20,
        "auto:double": '=IF(A3="","",B3*2)',
    }


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 10, 29, 12, 0)

    def __call__(self) -> dt.datetime:
        return self.now


def lagging_edit(client: FakeSheetsClient, repo: GSheetsBackend, value: int) -> None:
    """Change A3 as a hand edit would, while Drive's modifiedTime has not moved yet (it takes
    about 3 minutes on Google)."""
    drive = client.modified[repo.spreadsheet_id]
    update = {
        "rows": [{"values": [cell_data(value)]}],
        "start": {"sheetId": 1000, "rowIndex": 2, "columnIndex": 0},
        "fields": "userEnteredValue",
    }
    client.batch_update(repo.spreadsheet_id, [{"updateCells": update}])
    client.modified[repo.spreadsheet_id] = drive


def test_the_sheet_is_read_once_until_drive_sees_a_change(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"], [1])
    client.calls.clear()
    repo.read_table("T")
    repo.list_tables()
    assert client.calls.count("get_grid") == 1
    client.modified[repo.spreadsheet_id] += dt.timedelta(seconds=1)
    repo.read_table("T")
    assert client.calls.count("get_grid") == 2


def test_a_copy_older_than_max_age_is_read_again(client: FakeSheetsClient) -> None:
    clock = Clock()
    repo = book(client, ["a"], [1])
    repo = GSheetsBackend(repo.spreadsheet_id, client, clock=clock)  # max_age 60 s
    first = repo.last_modified()
    assert first == clock.now  # a first read counts as a change: an old snapshot is not trusted
    lagging_edit(client, repo, 2)
    clock.now += dt.timedelta(seconds=59)
    assert repo.read_table("T").rows[0].cells == {"a": 1}  # Drive saw nothing: the copy is kept
    assert repo.last_modified() == first
    clock.now += dt.timedelta(seconds=1)
    assert repo.read_table("T").rows[0].cells == {"a": 2}
    assert repo.last_modified() == clock.now  # the content changed: later than Drive's time
    seen = repo.last_modified()
    clock.now += dt.timedelta(minutes=5)
    client.calls.clear()
    assert repo.last_modified() == seen  # read again, same content: nothing changed
    assert client.calls.count("get_grid") == 1


def test_the_snapshot_follows_the_content(client: FakeSheetsClient, tmp_path: Path) -> None:
    clock = Clock()
    repo = book(client, ["a"], [1])
    repo = GSheetsBackend(repo.spreadsheet_id, client, clock=clock)
    cached = CachedRepository("journal", repo, Snapshots(tmp_path))
    assert cached.read_table("T").rows[0].cells == {"a": 1}
    lagging_edit(client, repo, 2)
    clock.now += dt.timedelta(seconds=60)
    assert cached.read_table("T").rows[0].cells == {"a": 2}
    again = CachedRepository(
        "journal", GSheetsBackend(repo.spreadsheet_id, client), Snapshots(tmp_path)
    )
    assert again.read_table("T").rows[0].cells == {"a": 2}  # a new process reads Google, not disk


def test_label_names_the_sheet_by_title_once_read(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"])
    assert repo.label == f"Google Sheet {repo.spreadsheet_id}"
    repo.list_tables()
    assert repo.label == "Google Sheet 'Journal'"


def test_a_sheet_the_app_did_not_create(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"])
    client.unwatched.add(repo.spreadsheet_id)
    assert repo.exists()
    with pytest.raises(StorageError, match=r"was not created by climb-log, .* \(#54\)"):
        repo.list_tables()


def test_a_sheet_that_disappears_between_calls(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"])

    def gone(spreadsheet_id: str) -> Json:
        raise GoogleNotFound("not found on Google")

    client.get_grid = gone  # type: ignore[method-assign]
    with pytest.raises(StorageError, match="workbook not found: Google Sheet"):
        repo.read_table("T")


def test_writes_wait_for_later_issues(client: FakeSheetsClient, load: LoadYaml) -> None:
    repo = book(client, ["a"])
    with pytest.raises(StorageError, match="comes with #52"):
        repo.apply([])
    with pytest.raises(StorageError, match="comes with #52"):
        repo.write_kv("_meta", {})
    with pytest.raises(StorageError, match="comes with #53"):
        repo.sync_schema(workbook_layout(load(SYNC_MODULE)), {})
