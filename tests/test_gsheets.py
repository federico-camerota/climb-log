# SPDX-License-Identifier: GPL-3.0-or-later
"""The Google backend, on an in-memory Google (04-storage.md §3, D-063, D-064).

What every backend does is in the contract tests (`test_backend_*.py`); here, what is particular
to Google: cell types from number formats, caching on Drive's `modifiedTime`, sheets the app
didn't create, and what a write sends (schema sync: `test_gsheets_sync.py`).
"""

import datetime as dt
from pathlib import Path

import pytest
from fake_sheets import FakeSheetsClient, cell_data, spreadsheet_body
from workbooks import tab

from climblog.storage import (
    Append,
    CachedRepository,
    GSheetsBackend,
    Snapshots,
    StorageError,
    Update,
    WriteConflict,
)
from climblog.storage.cells import RawCell
from climblog.storage.google_client import GoogleNotFound, Json
from climblog.storage.gsheets import en_formula, grid_rows, local_formula

D20 = dt.datetime(2026, 10, 20)


def sid(repo: GSheetsBackend) -> str:
    assert repo.spreadsheet_id is not None
    return repo.spreadsheet_id


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


def test_formulas_come_back_in_en_us_syntax(client: FakeSheetsClient) -> None:
    body = spreadsheet_body("Journal", {"T": tab(["a", "auto:b"], [1, '=IF(A3="","",A3*1.5)'])})
    body["properties"]["locale"] = "it_IT"
    repo = GSheetsBackend(client.create(body), client)
    sheet = client.get_grid(sid(repo))["sheets"][0]
    assert grid_rows(sheet, formulas=True)[2][1] == '=IF(A3="";"";A3*1,5)'  # as Google gives it
    assert repo.read_formulas("T").rows[0].cells["auto:b"] == '=IF(A3="","",A3*1.5)'


def test_en_formula() -> None:
    assert en_formula('=IF(A3="";"";B3*1,5)') == '=IF(A3="","",B3*1.5)'
    assert en_formula('=IF(A3="","",B3*1.5)') == '=IF(A3="","",B3*1.5)'  # the app's: as is
    assert en_formula('=IF(A3=";","",1.5)') == '=IF(A3=";","",1.5)'  # `;` in a string only
    assert en_formula('=IF(A3="a;b,c";"x""y;";1)') == '=IF(A3="a;b,c","x""y;",1)'
    assert en_formula("=SUM('Tab; 1,5'!A:A;2)") == "=SUM('Tab; 1,5'!A:A,2)"
    for formula in ('=IF(A3="a;b,c","x""y;",1.5)', "=SUM('Tab, 1.5'!A:A,2)"):
        assert en_formula(local_formula(formula)) == formula


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 10, 29, 12, 0)

    def __call__(self) -> dt.datetime:
        return self.now


def lagging_edit(client: FakeSheetsClient, repo: GSheetsBackend, value: int) -> None:
    """Change A3 as a hand edit would, while Drive's modifiedTime has not moved yet (it takes
    about 3 minutes on Google)."""
    drive = client.modified[sid(repo)]
    update = {
        "rows": [{"values": [cell_data(value)]}],
        "start": {"sheetId": 1000, "rowIndex": 2, "columnIndex": 0},
        "fields": "userEnteredValue",
    }
    client.batch_update(sid(repo), [{"updateCells": update}])
    client.modified[sid(repo)] = drive


def test_the_sheet_is_read_once_until_drive_sees_a_change(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"], [1])
    client.calls.clear()
    repo.read_table("T")
    repo.list_tables()
    assert client.calls.count("get_grid") == 1
    client.modified[sid(repo)] += dt.timedelta(seconds=1)
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
    assert repo.label == f"Google Sheet {sid(repo)}"
    repo.list_tables()
    assert repo.label == "Google Sheet 'Journal'"


def test_a_sheet_the_app_did_not_create(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"])
    client.unwatched.add(sid(repo))
    assert repo.exists()
    with pytest.raises(StorageError, match=r"was not created by climb-log, .* \(#54\)"):
        repo.list_tables()


def test_a_configured_sheet_that_does_not_exist(client: FakeSheetsClient) -> None:
    repo = GSheetsBackend("fictional-missing-sheet-0123456789", client)
    assert not repo.exists()
    with pytest.raises(StorageError, match="workbook not found: Google Sheet fictional-missing"):
        repo.read_table("T")
    with pytest.raises(StorageError, match="workbook not found"):
        repo.apply([])


def test_a_sheet_that_disappears_between_calls(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"])

    def gone(spreadsheet_id: str) -> Json:
        raise GoogleNotFound("not found on Google")

    client.get_grid = gone  # type: ignore[method-assign]
    with pytest.raises(StorageError, match="workbook not found: Google Sheet"):
        repo.read_table("T")


# ---- Writing ----


def formats(client: FakeSheetsClient, repo: GSheetsBackend, row: int) -> list[object]:
    """The number format of each cell of a row of tab T, as Google holds it."""
    sheet = client.books[sid(repo)]["sheets"][0]
    values = sheet["data"][0]["rowData"][row - 1]["values"]
    return [v.get("effectiveFormat", {}).get("numberFormat") for v in values]


def test_values_are_written_with_their_formats(client: FakeSheetsClient) -> None:
    repo = book(client, ["day", "at", "start", "rest", "kg", "ok", "note"])
    at = dt.datetime(2026, 10, 20, 18, 30)
    values: list[RawCell] = [at.date(), at, at.time(), dt.timedelta(minutes=90), 12.5, True, "=1+1"]
    keys = ["day", "at", "start", "rest", "kg", "ok", "note"]
    repo.apply([Append("T", dict(zip(keys, values, strict=True)))])
    assert formats(client, repo, 3) == [
        {"type": "DATE", "pattern": "dd/mm/yyyy"},
        {"type": "DATE_TIME", "pattern": "dd/mm/yyyy hh:mm:ss"},
        {"type": "TIME", "pattern": "hh:mm"},
        {"type": "TIME", "pattern": "[h]:mm"},
        None,
        None,
        {"type": "TEXT"},
    ]
    assert repo.read_table("T").rows[0].cells == {
        "day": D20,  # as from openpyxl: a date cell reads as a datetime
        "at": dt.datetime(2026, 10, 20, 18, 30),
        "start": dt.time(18, 30),
        "rest": dt.timedelta(minutes=90),
        "kg": 12.5,
        "ok": True,
        "note": "=1+1",  # text, never a formula
    }


def test_a_format_of_the_values_kind_is_kept(client: FakeSheetsClient) -> None:
    repo = book(client, ["day", "kg", "note"], [D20, 1, "x"])
    sheet = client.books[sid(repo)]["sheets"][0]
    cells = sheet["data"][0]["rowData"][2]["values"]
    for i, form in ((0, {"type": "DATE", "pattern": "d mmm yyyy"}), (1, {"type": "PERCENT"})):
        cells[i]["userEnteredFormat"] = cells[i]["effectiveFormat"] = {"numberFormat": form}
    row = repo.read_table("T").rows[0]
    repo.apply([Update("T", 3, {"day": D20, "kg": "7,5", "note": 3}, row.cells)])
    assert formats(client, repo, 3) == [
        {"type": "DATE", "pattern": "d mmm yyyy"},  # chosen in the sheet: kept
        {"type": "TEXT"},  # a string is always text
        None,  # a number in a text cell: back to automatic
    ]


def test_a_write_is_one_batch_on_a_fresh_read(client: FakeSheetsClient) -> None:
    clock = Clock()
    repo = book(client, ["a"], [1])
    repo = GSheetsBackend(repo.spreadsheet_id, client, clock=clock)
    row = repo.read_table("T").rows[0]
    lagging_edit(client, repo, 2)  # the cached copy, under a minute old, doesn't show it yet
    client.calls.clear()
    with pytest.raises(WriteConflict, match="row 3 changed since it was read"):
        repo.apply([Update("T", 3, {"a": 5}, row.cells)])
    assert client.calls == ["get_grid"]  # read again for the write; nothing sent
    client.calls.clear()
    repo.apply([Append("T", {"a": 7}), Append("T", {"a": 8})])
    assert client.calls == ["get_grid", "batch_update"]


def test_adjacent_cells_go_in_one_request(client: FakeSheetsClient) -> None:
    repo = book(client, ["a", "b", "c", "d"])
    sent: list[list[Json]] = []
    send = client.batch_update

    def spy(spreadsheet_id: str, requests: list[Json]) -> Json:
        sent.append(requests)
        return send(spreadsheet_id, requests)

    client.batch_update = spy  # type: ignore[method-assign,assignment]
    repo.apply([Append("T", {"a": 1, "b": 2, "d": 4}), Append("T", {"a": 5})])
    (requests,) = sent
    updates = [r["updateCells"] for r in requests if "updateCells" in r]
    starts = [(u["start"]["rowIndex"], u["start"]["columnIndex"]) for u in updates]
    assert starts == [(2, 0), (2, 3), (3, 0)]  # a3:b3, d3, a4
    assert [len(u["rows"][0]["values"]) for u in updates] == [2, 1, 1]
    assert [r.cells for r in repo.read_table("T").rows] == [{"a": 1, "b": 2, "d": 4}, {"a": 5}]


def test_reads_see_a_write_at_once(client: FakeSheetsClient) -> None:
    clock = Clock()
    repo = book(client, ["a"], [1])
    repo = GSheetsBackend(repo.spreadsheet_id, client, clock=clock)
    before = repo.last_modified()
    clock.now += dt.timedelta(seconds=1)
    client.modified[sid(repo)] -= dt.timedelta(hours=1)  # Drive lags behind
    repo.apply([Append("T", {"a": 2})])
    assert [r.cells["a"] for r in repo.read_table("T").rows] == [1, 2]
    assert repo.last_modified() > before  # so the snapshot is taken again


def test_rows_are_added_to_the_grid_when_needed(client: FakeSheetsClient) -> None:
    repo = book(client, ["a", "auto:b"], [1, "=A3"])
    sheet = client.books[sid(repo)]["sheets"][0]
    sheet["properties"]["gridProperties"]["rowCount"] = 3
    repo.apply([Append("T", {"a": 2})])
    sheet = client.books[sid(repo)]["sheets"][0]
    assert sheet["properties"]["gridProperties"]["rowCount"] == 202  # buffer from row 3 to 202
    assert repo.read_formulas("T").rows[-1].cells == {"auto:b": "=A202"}


def test_a_failed_write_changes_nothing(client: FakeSheetsClient) -> None:
    repo = book(client, ["a"], [1])
    sheet = client.books[sid(repo)]["sheets"][0]
    sheet["properties"]["gridProperties"]["columnCount"] = 0  # Google refuses every cell
    with pytest.raises(StorageError, match="exceeds grid limits"):
        repo.apply([Append("T", {"a": 2})])
    assert [r.cells["a"] for r in repo.read_table("T").rows] == [1]


def test_write_kv_adds_keys_below_the_last_row(client: FakeSheetsClient) -> None:
    spreadsheet_id = client.create(
        spreadsheet_body("Journal", {"_settings": [["key", "value"], ["a", 1], [None, "x"]]})
    )
    repo = GSheetsBackend(spreadsheet_id, client)
    repo.write_kv("_settings", {"b": 2})
    assert repo.read_kv("_settings") == {"a": 1, "b": 2}
    assert grid_rows(client.books[spreadsheet_id]["sheets"][0])[3] == ("b", 2)
