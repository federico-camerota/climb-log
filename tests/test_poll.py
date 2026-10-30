# SPDX-License-Identifier: GPL-3.0-or-later
"""Change polling for Google modules while `climblog serve` runs (04-storage.md §3, D-068).

On the in-memory Google, with a config naming fictional modules: one on Google, one local.
"""

import asyncio
import datetime as dt
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from fake_sheets import FakeSheetsClient, cell_data
from fastapi import FastAPI
from fastapi.testclient import TestClient

from climblog import main, poll
from climblog.catalog import Catalog, served
from climblog.config import AppConfig, load_config
from climblog.modules import load_module
from climblog.storage import GSheetsBackend, XlsxBackend, sync_module

ROOT = Path(__file__).parent.parent
FINGERS = ROOT / "modules" / "finger-strength.yaml"
MOCKUP = ROOT / "design" / "mockups" / "mockup-finger-strength.xlsx"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeSheetsClient:
    fake = FakeSheetsClient()
    monkeypatch.setattr(AppConfig, "sheets_client", lambda self: fake)
    return fake


@pytest.fixture
def config(tmp_path: Path, client: FakeSheetsClient, monkeypatch: pytest.MonkeyPatch) -> Path:
    """finger_strength on Google (a fictional sheet), `local` in a workbook."""
    module = load_module(FINGERS)
    google = GSheetsBackend(None, client)
    sync_module(module, google)
    shutil.copy(MOCKUP, tmp_path / "fingers.xlsx")
    sync_module(module, XlsxBackend(tmp_path / "fingers.xlsx"))
    local = tmp_path / "local.yaml"
    local.write_text(FINGERS.read_text().replace("module: finger_strength", "module: local"))
    file = tmp_path / "config.toml"
    file.write_text(
        f'[modules.finger_strength]\ndefinition = "{FINGERS}"\n'
        f'google_sheet = "{google.spreadsheet_id}"\n'
        f'[modules.local]\ndefinition = "{local}"\nworkbook = "fingers.xlsx"\n'
        f'[snapshots]\nfolder = "{tmp_path / "snapshots"}"\n'
        f'[backups]\nfolder = "{tmp_path / "backups"}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLIMBLOG_CONFIG", str(file))
    return file


def test_only_google_modules_are_polled(config: Path, client: FakeSheetsClient) -> None:
    catalog = Catalog(load_config(config))
    assert [e.name for e in poll.google_entries(catalog)] == ["finger_strength"]
    client.calls.clear()
    poll.poll_once(catalog)
    assert client.calls.count("get_grid") == 1
    snapshot = catalog.entries["finger_strength"].repo
    assert snapshot is not None and snapshot.as_of is not None
    assert (config.parent / "snapshots" / "finger_strength.json.gz").exists()
    assert not (config.parent / "snapshots" / "local.json.gz").exists()


def test_a_phone_edit_is_picked_up_and_backed_up(config: Path, client: FakeSheetsClient) -> None:
    catalog = Catalog(load_config(config))
    poll.poll_once(catalog)
    (spreadsheet_id,) = client.books
    sheet = client.books[spreadsheet_id]["sheets"][0]
    update = {"rows": [{"values": [cell_data(dt.datetime(2026, 10, 30))]}],
              "start": {"sheetId": sheet["properties"]["sheetId"], "rowIndex": 2,
                        "columnIndex": 0}, "fields": "userEnteredValue"}  # fmt: skip
    client.batch_update(spreadsheet_id, [{"updateCells": update}])  # typed on the phone
    repo = catalog.entries["finger_strength"].repo
    assert repo is not None
    source = repo.source
    assert isinstance(source, GSheetsBackend)
    source.max_age = dt.timedelta(0)  # don't wait the minute
    poll.poll_once(catalog)
    tab = sheet["properties"]["title"]
    assert repo.read_table(tab).rows[0].cells["date"] == dt.datetime(2026, 10, 30)
    assert len(list((config.parent / "backups" / "finger_strength").glob("*.xlsx"))) == 1


def test_a_module_that_cannot_be_read_is_logged(
    config: Path, client: FakeSheetsClient, caplog: pytest.LogCaptureFixture
) -> None:
    catalog = Catalog(load_config(config))
    client.books.clear()  # gone from Google
    with caplog.at_level(logging.WARNING):
        poll.poll_once(catalog)
    assert caplog.messages[0].startswith("could not read module finger_strength: workbook not")


def test_polling_runs_until_cancelled(
    config: Path, client: FakeSheetsClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rounds: list[Catalog] = []

    def counted(catalog: Catalog) -> None:
        rounds.append(catalog)
        if len(rounds) == 2:
            raise asyncio.CancelledError  # stop the loop after its second round

    monkeypatch.setattr(poll, "poll_once", counted)
    file = config.read_text(encoding="utf-8") + "[google]\npoll_seconds = 0.01\n"
    config.write_text(file, encoding="utf-8")
    app = FastAPI()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(poll.poll(app))
    assert len(rounds) == 2
    assert rounds[0] is app.state.catalog  # the API's catalog, loaded once


@pytest.mark.parametrize("google", ["poll_seconds = 0\n", None])
def test_nothing_to_poll(config: Path, monkeypatch: pytest.MonkeyPatch, google: str | None) -> None:
    def never(catalog: Catalog) -> None:
        raise AssertionError("polled")

    monkeypatch.setattr(poll, "poll_once", never)
    if google:
        config.write_text(config.read_text(encoding="utf-8") + f"[google]\n{google}", "utf-8")
    else:  # no module on Google
        text = config.read_text(encoding="utf-8").split("[modules.local]")[1]
        config.write_text("[modules.local]" + text, encoding="utf-8")
    asyncio.run(poll.poll(FastAPI()))  # returns at once


def test_the_served_app_polls(config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []

    async def fake_poll(app: FastAPI) -> None:
        started.append(app)
        await asyncio.sleep(3600)  # cancelled when the app stops

    monkeypatch.setattr(main, "poll", fake_poll)
    app = main.serve_app()
    with TestClient(app) as http:
        assert http.get("/api/health").status_code == 200
    assert started == [app]
    with TestClient(main.create_app()) as http:  # the tests' app: no polling
        http.get("/api/health")
    assert len(started) == 1


def test_the_catalog_is_loaded_once(config: Path) -> None:
    state = FastAPI().state
    assert served(state) is served(state)


def test_a_missing_config_serves_no_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLIMBLOG_CONFIG", str(tmp_path / "none.toml"))
    catalog = served(FastAPI().state)
    assert poll.google_entries(catalog) == []
