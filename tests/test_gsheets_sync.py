# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema sync on Google, on an in-memory Google (04-storage.md §1, §3, D-065).

What every backend does is in `test_backend_sync.py`; here, what Google gets in its own terms:
a new sheet in the app's folder with its locale, header styles, dropdowns and colour rules,
warning-only protection, named settings, and the grid growing for the formula buffer.
"""

from typing import Any

import pytest
from conftest import LoadYaml
from fake_sheets import FakeSheetsClient, spreadsheet_body
from formula_module import MODULE as FORMULA_MODULE
from workbooks import D20, SYNC_MODULE, existing_tabs, tab

from climblog.modules import Module
from climblog.storage import (
    Append,
    GSheetsBackend,
    StorageError,
    sync_module,
    workbook_layout,
)
from climblog.storage.google_client import Json
from climblog.storage.gsheets import NewSheets
from climblog.storage.gsheets_sync import google_format, sync_requests


@pytest.fixture
def client() -> FakeSheetsClient:
    return FakeSheetsClient()


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(SYNC_MODULE)


@pytest.fixture
def created(client: FakeSheetsClient, module: Module) -> GSheetsBackend:
    repo = GSheetsBackend(None, client)
    sync_module(module, repo)
    return repo


def sheet(client: FakeSheetsClient, repo: GSheetsBackend, name: str) -> Json:
    assert repo.spreadsheet_id is not None
    book = client.books[repo.spreadsheet_id]
    return next(s for s in book["sheets"] if s["properties"]["title"] == name)


def cell(client: FakeSheetsClient, repo: GSheetsBackend, name: str, row: int, column: int) -> Json:
    found: Json = sheet(client, repo, name)["data"][0]["rowData"][row - 1]["values"][column]
    return found


def rgb(hex_rgb: str) -> dict[str, Any]:
    red, green, blue = (int(hex_rgb[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return {"rgbColor": {"red": red, "green": green, "blue": blue}}


# ---- A new sheet ----


def test_a_new_sheet_is_made_in_the_apps_folder(
    client: FakeSheetsClient, created: GSheetsBackend
) -> None:
    assert created.spreadsheet_id is not None
    book = client.books[created.spreadsheet_id]
    assert book["properties"] == {
        "title": "Test sync",
        "locale": "it_IT",
        "timeZone": "Europe/Rome",
    }
    assert client.parents[created.spreadsheet_id] == client.folders["climb-log"]
    assert created.list_tables() == ["Pre", "Post", "_settings", "_meta"]  # Google's tab is gone
    assert created.label == "Google Sheet 'Test sync'"


def test_formulas_are_written_in_the_sheets_syntax(
    client: FakeSheetsClient, load: LoadYaml
) -> None:
    repo = GSheetsBackend(None, client)
    sync_module(load(FORMULA_MODULE), repo)
    rows = sheet(client, repo, "Session")["data"][0]["rowData"]
    formulas = [v for row in rows[2:4] for v in row.get("values", [])
                if "formulaValue" in v.get("userEnteredValue", {})]  # fmt: skip
    assert len(formulas) > 40
    assert all("errorValue" not in v.get("effectiveValue", {}) for v in formulas)  # parsed
    assert formulas[0]["userEnteredValue"]["formulaValue"].startswith('=IF(A3="";"";')
    formula = repo.read_formulas("Session").rows[0].cells["auto:load"]
    assert formula == '=IF(A3="","",IF(OR(D3="",E3=""),"",D3*E3))'  # read back in en_US syntax


def test_the_folder_locale_and_time_zone_come_from_the_config(
    client: FakeSheetsClient, module: Module
) -> None:
    repo = GSheetsBackend(None, client, new_sheets=NewSheets("Training", "en_GB", "UTC"))
    sync_module(module, repo)
    assert repo.spreadsheet_id is not None
    assert client.books[repo.spreadsheet_id]["properties"]["locale"] == "en_GB"
    assert client.parents[repo.spreadsheet_id] == client.folders["Training"]
    (scale,) = sheet(client, repo, "Pre")["conditionalFormats"]
    assert scale["gradientRule"]["midpoint"]["value"] == "5.5"  # a decimal point in en_GB


def test_a_new_sheet_that_fails_is_trashed(client: FakeSheetsClient, module: Module) -> None:
    repo = GSheetsBackend(None, client)
    calls = []

    def refuse(spreadsheet_id: str, requests: Any) -> Json:
        calls.append(spreadsheet_id)
        raise StorageError("Google answered 400: Invalid requests")

    client.batch_update = refuse  # type: ignore[method-assign]
    with pytest.raises(StorageError, match="Invalid requests"):
        sync_module(module, repo)
    assert repo.spreadsheet_id is None
    assert client.books == {}  # trashed
    assert len(calls) == 1
    assert not repo.exists()
    with pytest.raises(StorageError, match="a new Google Sheet is made by schema sync"):
        repo.read_table("Pre")


def test_a_configured_sheet_that_is_gone_is_not_made_again(
    client: FakeSheetsClient, module: Module
) -> None:
    repo = GSheetsBackend("fictional-missing-sheet-0123456789", client)
    with pytest.raises(StorageError, match="workbook not found"):
        repo.sync_schema(workbook_layout(module), {})
    assert client.books == {}


# ---- Headers, rules and protection ----


def test_header_rows_are_styled_and_frozen(
    client: FakeSheetsClient, created: GSheetsBackend
) -> None:
    pre = sheet(client, created, "Pre")
    grid = pre["properties"]["gridProperties"]
    assert (grid["frozenRowCount"], grid["frozenColumnCount"]) == (2, 2)
    label, key = cell(client, created, "Pre", 1, 1), cell(client, created, "Pre", 2, 1)
    assert label["userEnteredFormat"]["backgroundColorStyle"] == rgb("C6E0B4")  # pain: pre, green
    assert label["userEnteredFormat"]["textFormat"]["bold"] is True
    assert key["userEnteredFormat"]["textFormat"]["fontFamily"] == "Roboto Mono"
    assert key["userEnteredFormat"]["borders"]["bottom"]["style"] == "SOLID_MEDIUM"
    assert cell(client, created, "Pre", 2, 0)["note"].startswith("Row 2 holds the field keys")
    dimensions = pre["dimensions"]
    assert dimensions["COLUMNS:0"] == {"pixelSize": 77}  # 11 characters
    assert dimensions["COLUMNS:3"] == {"pixelSize": 84, "hiddenByUser": True}  # auto:_key
    assert dimensions["ROWS:0"] == {"pixelSize": 64}
    assert cell(client, created, "Pre", 3, 0)["effectiveFormat"] == {
        "numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}
    }


def test_dropdowns_ranges_and_scale_colours(
    client: FakeSheetsClient, created: GSheetsBackend
) -> None:
    pre = sheet(client, created, "Pre")
    rules = {r["range"]["startColumnIndex"]: r["rule"] for r in pre["dataValidations"]}
    assert rules[0] == {
        "condition": {"type": "DATE_ON_OR_AFTER", "values": [{"userEnteredValue": "1990-01-01"}]},
        "strict": True,
    }
    pain = [str(n) for n in range(1, 11)]
    assert rules[1]["condition"] == {
        "type": "ONE_OF_LIST",
        "values": [{"userEnteredValue": v} for v in pain],
    }
    assert rules[2]["condition"]["values"] == [
        {"userEnteredValue": "Climb"},
        {"userEnteredValue": "Board"},
    ]
    assert set(rules) == {0, 1, 2}  # auto:_key and the system columns have none
    (scale,) = pre["conditionalFormats"]
    assert scale["ranges"] == [{"sheetId": scale["ranges"][0]["sheetId"], "startRowIndex": 2,
                                "startColumnIndex": 1, "endColumnIndex": 2}]  # fmt: skip
    points = scale["gradientRule"]
    values = [points[p]["value"] for p in ("minpoint", "midpoint", "maxpoint")]
    assert values == ["1", "5,5", "10"]  # rule values are read in the sheet's locale, it_IT
    assert points["minpoint"]["colorStyle"] == rgb("63BE7B")  # lower is better: 1 is green


def test_statuses_get_their_colours(client: FakeSheetsClient, load: LoadYaml) -> None:
    repo = GSheetsBackend(None, client)
    sync_module(load(FORMULA_MODULE), repo)
    rules = sheet(client, repo, "Session")["conditionalFormats"]
    status = [r["booleanRule"] for r in rules if "booleanRule" in r]
    fills = {r["condition"]["values"][0]["userEnteredValue"]: r["format"] for r in status}
    assert fills["GOOD"] == {"backgroundColorStyle": rgb("C6EFCE")}
    assert fills["LOW"] == {"backgroundColorStyle": rgb("F8CBAD")}
    minutes = {r["range"]["startColumnIndex"]: r["rule"] for r in
               sheet(client, repo, "Session")["dataValidations"]}  # fmt: skip
    assert minutes[3]["condition"] == {
        "type": "NUMBER_BETWEEN",
        "values": [{"userEnteredValue": "0"}, {"userEnteredValue": "300"}],
    }
    assert minutes[1]["condition"] == {  # session_no: a whole number from 1
        "type": "CUSTOM_FORMULA",
        "values": [{"userEnteredValue": "=AND(ISNUMBER(B3);B3=INT(B3);B3>=1)"}],  # it_IT
    }


def test_other_field_kinds(client: FakeSheetsClient, load: LoadYaml) -> None:
    module = load(
        """\
        module: test_sync
        name: Test sync
        version: 1
        kind: journal
        entities:
          fall:
            label: Fall
            tab: Falls
            key: [date]
            fields:
              date: {type: date}
              at: {type: time}
              weight: {type: number, max: 200}
              grip: {type: choice, choices: [Crimp, Open], allow_other: true}
              floor: {type: integer, min: 0}
              note: {type: text}
              height: {type: number, min: 0}
        """
    )
    repo = GSheetsBackend(None, client)
    sync_module(module, repo)
    rules = {r["range"]["startColumnIndex"]: r["rule"] for r in
             sheet(client, repo, "Falls")["dataValidations"]}  # fmt: skip
    assert rules[1]["condition"]["type"] == "NUMBER_BETWEEN"  # a time of day
    assert rules[2]["condition"] == {
        "type": "NUMBER_LESS_THAN_EQ",
        "values": [{"userEnteredValue": "200"}],
    }
    assert rules[3]["strict"] is False  # allow_other: a warning only
    assert rules[4]["condition"]["values"] == [
        {"userEnteredValue": "=AND(ISNUMBER(E3);E3=INT(E3);E3>=0)"}
    ]
    assert rules[6]["condition"] == {
        "type": "NUMBER_GREATER_THAN_EQ",
        "values": [{"userEnteredValue": "0"}],
    }
    assert cell(client, repo, "Falls", 3, 5)["effectiveFormat"] == {
        "numberFormat": {"type": "TEXT"}
    }


def test_headers_and_formula_columns_are_protected_with_a_warning(
    client: FakeSheetsClient, module: Module, created: GSheetsBackend
) -> None:
    def protected() -> list[tuple[str, Json, bool]]:
        found = sheet(client, created, "Pre")["protectedRanges"]
        return [(p["description"], p["range"], p["warningOnly"]) for p in found]

    sheet_id = sheet(client, created, "Pre")["properties"]["sheetId"]
    assert protected() == [
        ("climb-log: header rows", {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 2},
         True),
        ("climb-log: auto:_key", {"sheetId": sheet_id, "startRowIndex": 2, "startColumnIndex": 3,
                                  "endColumnIndex": 4}, True),
    ]  # fmt: skip
    before = protected()
    sync_module(module, created)
    assert protected() == before  # made again, not twice


def test_rules_on_other_columns_are_kept(client: FakeSheetsClient, module: Module) -> None:
    body = spreadsheet_body("Journal", existing_tabs())
    spreadsheet_id = client.create(body)
    pre = client.books[spreadsheet_id]["sheets"][0]
    sheet_id = pre["properties"]["sheetId"]

    def columns(first: int, end: int) -> Json:
        return {"sheetId": sheet_id, "startRowIndex": 2, "startColumnIndex": first,
                "endColumnIndex": end}  # fmt: skip

    hand = {"booleanRule": {"condition": {"type": "NOT_BLANK"}, "format": {}}}
    whole_rows = {"sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": 5}
    pre["conditionalFormats"] = [
        {"ranges": [columns(3, 4)], **hand},  # weather: not the module's
        {"ranges": [columns(0, 4), whole_rows], **hand},  # spans date … weather, and rows
    ]
    repo = GSheetsBackend(spreadsheet_id, client)
    sync_module(module, repo)
    rules = client.books[spreadsheet_id]["sheets"][0]["conditionalFormats"]
    kept = [r["ranges"] for r in rules if "booleanRule" in r]
    # the spanning rule is cut down to the columns the module doesn't know: auto:status, weather
    assert kept == [[columns(3, 4)], [columns(2, 3), columns(3, 4), whole_rows]]


def test_settings_have_named_ranges(
    client: FakeSheetsClient, module: Module, created: GSheetsBackend
) -> None:
    assert created.spreadsheet_id is not None
    sheet_id = sheet(client, created, "_settings")["properties"]["sheetId"]

    def names() -> dict[str, Json]:
        assert created.spreadsheet_id is not None
        return {n["name"]: n["range"] for n in client.books[created.spreadsheet_id]["namedRanges"]}

    assert names()["low_max"] == {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": 2,
                                  "startColumnIndex": 1, "endColumnIndex": 2}  # fmt: skip
    assert list(names()) == ["low_max", "start", "strict", "motto"]
    sync_module(module, created)  # re-pointed, never twice (Google refuses a name twice)
    assert len(names()) == 4


# ---- Formula buffer and grid ----


def test_the_grid_grows_for_the_formula_buffer(client: FakeSheetsClient, module: Module) -> None:
    rows = [[D20, 3, None, None, None, None]] * 1100
    spreadsheet_id = client.create(
        spreadsheet_body("Journal", {"Pre": tab(["date", "pain", "kind"], *rows)})
    )
    repo = GSheetsBackend(spreadsheet_id, client)
    sync_module(module, repo)
    pre = client.books[spreadsheet_id]["sheets"][0]
    assert pre["properties"]["gridProperties"]["rowCount"] == 1302  # 200 past the last row
    assert repo.read_formulas("Pre").rows[-1].number == 1302


def test_columns_past_the_grid_are_added(client: FakeSheetsClient, module: Module) -> None:
    keys = [f"x{n}" for n in range(26)]
    spreadsheet_id = client.create(spreadsheet_body("Journal", {"Pre": tab(keys)}))
    repo = GSheetsBackend(spreadsheet_id, client)
    done = sync_module(module, repo)
    assert "Pre: added column 'date'" in done
    grid = client.books[spreadsheet_id]["sheets"][0]["properties"]["gridProperties"]
    assert grid["columnCount"] == 26 + 6
    assert repo.read_table("Pre").columns[26:] == (
        *("date", "pain", "kind", "auto:_key", "updated_at", "deleted"),
    )


def test_a_formula_changed_by_hand_is_put_back(
    client: FakeSheetsClient, module: Module, created: GSheetsBackend
) -> None:
    created.apply([Append("Pre", {"date": D20})])
    assert created.spreadsheet_id is not None
    pre = sheet(client, created, "Pre")
    key = pre["data"][0]["rowData"][2]["values"][3]
    key["userEnteredValue"] = {"formulaValue": "=1"}
    assert sync_module(module, created) == ["Pre: rewrote 1 changed cells of 'auto:_key'"]


def test_a_formula_changed_in_the_module_is_new(
    client: FakeSheetsClient, module: Module, created: GSheetsBackend
) -> None:
    for row in sheet(client, created, "Pre")["data"][0]["rowData"][2:202]:  # the buffer
        row["values"][3]["userEnteredValue"] = {"formulaValue": "=1"}
    assert sync_module(module, created) == ["Pre: new formula in 'auto:_key'"]


def test_key_values_of_any_kind_and_a_short_grid(client: FakeSheetsClient, module: Module) -> None:
    body = spreadsheet_body("Journal", {"_meta": [["key", "value"]]})
    body["sheets"][0]["properties"]["gridProperties"] = {"rowCount": 2, "columnCount": 2}
    spreadsheet_id = client.create(body)
    requests, _ = sync_requests(
        client.get_layout(spreadsheet_id), workbook_layout(module), {"a": None, "b": True, "c": 1}
    )
    client.batch_update(spreadsheet_id, requests)  # Google would refuse rows past the grid
    repo = GSheetsBackend(spreadsheet_id, client)
    assert repo.read_kv("_meta") == {"a": None, "b": "Yes", "c": 1}  # as in .xlsx


def test_google_formats() -> None:
    assert google_format(None) is None
    assert google_format("General") is None
    assert google_format("@") == {"type": "TEXT"}
    assert google_format("DD/MM/YYYY HH:MM") == {"type": "DATE_TIME", "pattern": "dd/mm/yyyy hh:mm"}
    assert google_format("HH:MM") == {"type": "TIME", "pattern": "hh:mm"}
    assert google_format("0.0") == {"type": "NUMBER", "pattern": "0.0"}


def test_an_unreadable_key_value_tab_stops_before_anything_is_sent(
    client: FakeSheetsClient, module: Module
) -> None:
    spreadsheet_id = client.create(spreadsheet_body("Journal", {"_meta": [["k", "v"]]}))
    with pytest.raises(StorageError, match="needs the headers 'key' and 'value'"):
        sync_requests(client.get_layout(spreadsheet_id), workbook_layout(module), {})
