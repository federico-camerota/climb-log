# SPDX-License-Identifier: GPL-3.0-or-later
"""The drift check on Google Sheets, and formula parity computed by Google (03 §2.2b, D-066).

On the in-memory Google: a formula changed by hand is found, and one typed by hand in the it_IT
syntax is the same formula. With `CLIMBLOG_GOOGLE_LIVE=1`: fictional modules synced into new
sheets on your Google account, fictional rows typed in through the backend, and every value
Google computes must be the app's (`parity.py`), with no drift. Never in CI.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from backends import LIVE, GSheets
from conftest import LoadYaml
from fake_sheets import FakeSheetsClient
from formula_module import MODULE
from parity import compare, generate_google
from workbooks import D20, SYNC_MODULE

from climblog.config import config_path, load_config
from climblog.modules import Module, load_module
from climblog.storage import Append, GSheetsBackend, find_drift, sync_module
from climblog.storage.google_client import RestSheetsClient
from climblog.storage.gsheets import grid_rows, local_formula

ROOT = Path(__file__).parent.parent


# ---- The drift check, on the in-memory Google ----


@pytest.fixture
def synced(load: LoadYaml) -> tuple[Module, GSheetsBackend, FakeSheetsClient]:
    client = FakeSheetsClient()
    module = load(SYNC_MODULE)
    repo = GSheetsBackend(None, client)
    sync_module(module, repo)
    repo.apply([Append("Pre", {"date": D20})])
    return module, repo, client


def key_cell(client: FakeSheetsClient, repo: GSheetsBackend) -> dict[str, object]:
    assert repo.spreadsheet_id is not None
    pre = client.books[repo.spreadsheet_id]["sheets"][0]
    cell: dict[str, object] = pre["data"][0]["rowData"][2]["values"][3]
    return cell


def test_a_synced_sheet_has_no_drift(
    synced: tuple[Module, GSheetsBackend, FakeSheetsClient],
) -> None:
    module, repo, _ = synced
    assert find_drift(module, repo) == []


def test_a_formula_changed_on_google_is_drift(
    synced: tuple[Module, GSheetsBackend, FakeSheetsClient],
) -> None:
    module, repo, client = synced
    key_cell(client, repo)["userEnteredValue"] = {"formulaValue": "=1"}
    (drift,) = find_drift(module, repo)
    assert (drift.kind, drift.tab, drift.row, drift.column) == ("formula", "Pre", 3, "auto:_key")


def test_the_same_formula_typed_in_italian_syntax_is_no_drift(
    synced: tuple[Module, GSheetsBackend, FakeSheetsClient],
) -> None:
    module, repo, client = synced
    cell = key_cell(client, repo)
    entered = cell["userEnteredValue"]
    assert isinstance(entered, dict)
    cell["userEnteredValue"] = {"formulaValue": local_formula(entered["formulaValue"])}
    assert find_drift(module, repo) == []


# ---- Formula parity, computed by Google (live only) ----

live = pytest.mark.skipif(not LIVE, reason="set CLIMBLOG_GOOGLE_LIVE=1 to run on Google")


@pytest.fixture
def harness() -> Iterator[GSheets]:  # pragma: no cover - live only
    config = load_config(config_path())
    made = GSheets(RestSheetsClient(config.google_session), live=True)
    yield made
    made.close()


def mismatches(module: Module, harness: GSheets, seed: int) -> list[str]:  # pragma: no cover
    repo = harness.new()
    generate_google(module, repo, seed)
    drift = [str(d) for d in find_drift(module, repo)]
    assert repo.spreadsheet_id is not None
    book = harness.client.get_grid(repo.spreadsheet_id)
    sheets = {s["properties"]["title"]: grid_rows(s) for s in book["sheets"]}
    return [*drift, *compare(module, repo, sheets)]


@live
@pytest.mark.parametrize("seed", [1, 2])
def test_every_construct_matches_the_app(
    load: LoadYaml, harness: GSheets, seed: int
) -> None:  # pragma: no cover - live only
    assert mismatches(load(MODULE), harness, seed) == []


@live
@pytest.mark.parametrize(
    "file", [ROOT / "modules" / "finger-strength.yaml", ROOT / "modules" / "journal.yaml"], ids=str
)
def test_modules_match_the_app(file: Path, harness: GSheets) -> None:  # pragma: no cover
    assert mismatches(load_module(file), harness, 1) == []
