# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving a module from a local workbook to a new Google Sheet, and making a new one (D-067).

On the in-memory Google (which computes no formulas, so the value half of the drift check is
left to the live test, `CLIMBLOG_GOOGLE_LIVE=1`). Fictional workbooks only.
"""

import datetime as dt
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from backends import LIVE, GSheets
from conftest import LoadYaml
from fake_sheets import FakeSheetsClient
from parity import generate
from typer.testing import CliRunner
from workbooks import D20, SYNC_MODULE, existing_tabs, write_workbook

from climblog import cli
from climblog.config import AppConfig, config_path, load_config
from climblog.expr import Value
from climblog.modules import Module, load_module
from climblog.storage import (
    Append,
    DataIssue,
    EntityData,
    GSheetsBackend,
    ModuleData,
    StorageError,
    SyncRefused,
    XlsxBackend,
    load_data,
    move,
    move_to_google,
    sync_module,
)
from climblog.storage.google_client import RestSheetsClient

ROOT = Path(__file__).parent.parent
FINGERS = ROOT / "modules" / "finger-strength.yaml"
MOCKUP = ROOT / "design" / "mockups" / "mockup-finger-strength.xlsx"
runner = CliRunner()


@pytest.fixture
def client() -> FakeSheetsClient:
    return FakeSheetsClient()


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(SYNC_MODULE)


def hand_made(module: Module, tmp_path: Path) -> XlsxBackend:
    """`existing_tabs` with more rows (a bad value, a soft-deleted row, a row without a date),
    synced: a workbook moves once it checks clean."""
    tabs = {name: list(rows) for name, rows in existing_tabs().items()}
    tabs["Pre"] += [
        [dt.datetime(2026, 10, 21), "7.5x", None, "rain"],  # a data issue
        [None, 4, None, None],  # no date: a data issue too
    ]
    tabs["Post"] += [[dt.datetime(2026, 10, 22), 6, "  'po' stanco", None, None, D20]]
    local = XlsxBackend(write_workbook(tmp_path / "local.xlsx", tabs))
    sync_module(module, local)
    return local


def test_a_module_is_copied_raw_and_checked(
    client: FakeSheetsClient, module: Module, tmp_path: Path
) -> None:
    local = hand_made(module, tmp_path)
    before = local.path.read_bytes()
    google = GSheetsBackend(None, client)
    report = move_to_google(module, local, google)
    assert report.differences == []
    assert report.copied == {"Pre": 3, "Post": 2}
    assert report.not_copied == ["Pre: column 'weather'", "Post: column 'old_note'"]
    assert local.path.read_bytes() == before  # only read
    post = google.read_table("Post").rows
    assert post[1].cells == {  # `feel` (renamed by sync), a note as typed, deleted kept
        "date": dt.datetime(2026, 10, 22),
        "mood": 6,
        "note": "  'po' stanco",
        "deleted": D20,
    }
    assert google.read_table("Pre").rows[1].cells["pain"] == "7.5x"  # a data issue travels
    issues = [(i.tab, i.field) for i in load_data(module, google).issues]
    assert ("Pre", "pain") in issues
    assert google.read_kv("_settings")["low_max"] == 3  # the workbook's value, not the default
    assert report.spreadsheet_id == google.spreadsheet_id


def test_the_repos_modules_move_with_fictional_data(
    client: FakeSheetsClient, tmp_path: Path
) -> None:
    for file in (FINGERS, ROOT / "modules" / "journal.yaml"):
        module = load_module(file)
        folder = tmp_path / module.module
        folder.mkdir()
        local = XlsxBackend(generate(module, folder, seed=1).path)
        report = move_to_google(module, local, GSheetsBackend(None, client))
        assert report.differences == [], file.name
        assert sum(report.copied.values()) > 40


def test_a_workbook_out_of_step_is_not_moved(
    client: FakeSheetsClient, module: Module, tmp_path: Path
) -> None:
    local = XlsxBackend(write_workbook(tmp_path / "local.xlsx", existing_tabs()))  # not synced
    with pytest.raises(SyncRefused, match=r"not moved: .*`climblog check test_sync --apply`"):
        move_to_google(module, local, GSheetsBackend(None, client))
    assert client.books == {}  # no sheet made


def test_a_copy_that_differs_is_reported(
    client: FakeSheetsClient, module: Module, tmp_path: Path
) -> None:
    google = GSheetsBackend(None, client)
    write = google.apply

    def lose_one(edits: list[Append]) -> list[int]:
        return write(edits[:-1])

    google.apply = lose_one  # type: ignore[method-assign,assignment]
    report = move_to_google(module, hand_made(module, tmp_path), google)
    assert report.differences == ["Post: 2 rows copied, 1 on Google"]  # a deleted row
    assert google.spreadsheet_id in client.books  # kept for a look


def test_tabs_missing_from_the_workbook(
    client: FakeSheetsClient, module: Module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tabs the check would ask to sync, were it skipped: nothing to copy from them."""
    local = XlsxBackend(write_workbook(tmp_path / "local.xlsx", {"Pre": existing_tabs()["Pre"]}))
    monkeypatch.setattr(move, "check_schema", lambda module, repo: [])
    report = move_to_google(module, local, GSheetsBackend(None, client))
    assert report.copied == {"Pre": 1}  # no Post, no _settings


def test_what_the_check_compares(module: Module) -> None:
    def data(settings: dict[str, Value], *records: dict[str, Value], issue: str = "") -> ModuleData:
        issues = [DataIssue("Pre", 4, "pain", issue)] if issue else []
        return ModuleData(settings, {"session": EntityData(list(records))}, issues)

    day: dict[str, Value] = {"date": dt.date(2026, 10, 20), "old_note": "x"}
    same = data({"a": 1}, day)
    assert move._compare(module, same, data({"a": 1}, {**day, "old_note": None})) == []  # retired
    assert move._compare(module, same, data({"a": 2}, day, day, issue="row 4: bad")) == [
        "the settings differ",
        "session: 1 records, 2 on Google",
        "data issues differ: 0 only in the workbook, 1 only on Google",
    ]
    assert move._compare(module, data({}, day), data({}, {**day, "date": None})) == [
        "session: 1 records read differently on Google"
    ]


# ---- The commands ----


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: FakeSheetsClient) -> Path:
    """The fictional finger-strength mock-up as a local module, and the fake Google."""
    shutil.copy(MOCKUP, tmp_path / "fingers.xlsx")
    sync_module(load_module(FINGERS), XlsxBackend(tmp_path / "fingers.xlsx"))
    file = tmp_path / "config.toml"
    file.write_text(
        f'[modules.finger_strength]\ndefinition = "{FINGERS}"\nworkbook = "fingers.xlsx"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLIMBLOG_CONFIG", str(file))
    monkeypatch.setattr(AppConfig, "sheets_client", lambda self: client)
    return file


def test_move_prints_the_config_line(config: Path, client: FakeSheetsClient) -> None:
    result = runner.invoke(cli.app, ["module", "move", "finger_strength", "--to-google"])
    assert result.exit_code == 0, result.output
    (spreadsheet_id,) = client.books
    lines = result.output.splitlines()
    assert (
        lines[0]
        == f"finger_strength: copying {config.parent / 'fingers.xlsx'} to a new Google Sheet"
    )
    assert lines[1] == (
        "  created Google Sheet 'Finger strength': "
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    )
    assert lines[2].startswith("  rows copied: ")
    assert lines[-1] == f'google_sheet = "{spreadsheet_id}"'
    assert client.parents[spreadsheet_id] == client.folders["climb-log"]


def test_move_reports_differences(config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def differing(module: Module, local: object, google: GSheetsBackend) -> object:
        google.spreadsheet_id = "fictional-sheet-id-0123456789"
        from climblog.storage import MoveReport

        return MoveReport(google.spreadsheet_id, {"Hangs": 2}, ["Hangs: column 'x'"], ["oops"])

    monkeypatch.setattr(cli, "move_to_google", differing)
    result = runner.invoke(cli.app, ["module", "move", "finger_strength", "--to-google"])
    assert result.exit_code == 1
    assert result.output.splitlines()[2:] == [
        "  rows copied: Hangs 2",
        "  not copied (not in the module): Hangs: column 'x'",
        "  the copy differs; the sheet is kept for a look, the module stays local:",
        "    oops",
    ]


def test_move_refusals(config: Path, tmp_path: Path) -> None:
    def run(*args: str) -> list[str]:
        result = runner.invoke(cli.app, ["module", "move", *args])
        assert result.exit_code == 1
        return result.output.splitlines()

    assert run("finger_strength") == [
        "only --to-google: a module moves from a local workbook to Google Sheets"
    ]
    assert run("journal", "--to-google") == ["not in the config: journal"]
    on_google = tmp_path / "google.toml"
    on_google.write_text(
        f'[modules.finger_strength]\ndefinition = "{FINGERS}"\n'
        'google_sheet = "fictional-sheet-id-0123456789"\n',
        encoding="utf-8",
    )
    assert run("finger_strength", "--to-google", "--config", str(on_google)) == [
        "finger_strength is already on Google (Google Sheet fictional-sheet-id-0123456789)"
    ]
    assert run("x", "--to-google", "--config", str(tmp_path / "none.toml"))[0].endswith(
        "no config file here (see README, Configure)"
    )
    (tmp_path / "fingers.xlsx").unlink()
    assert run("finger_strength", "--to-google")[-1].startswith("error: workbook not found")


def test_create_makes_a_synced_sheet(config: Path, client: FakeSheetsClient, write: object) -> None:
    yaml = config.parent / "test-sync.yaml"
    yaml.write_text(SYNC_MODULE, encoding="utf-8")
    result = runner.invoke(cli.app, ["module", "create", str(yaml), "--google"])
    assert result.exit_code == 0, result.output
    (spreadsheet_id,) = client.books
    assert result.output.splitlines() == [
        "created Google Sheet 'Test sync' in your Drive folder 'climb-log':",
        f"  https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        "Add this to the config:",
        "[modules.test_sync]",
        f'definition = "{yaml}"',
        f'google_sheet = "{spreadsheet_id}"',
    ]
    assert GSheetsBackend(spreadsheet_id, client).list_tables() == [
        "Pre", "Post", "_settings", "_meta"
    ]  # fmt: skip


def test_create_refusals(config: Path, tmp_path: Path, client: FakeSheetsClient) -> None:
    def run(*args: str) -> list[str]:
        result = runner.invoke(cli.app, ["module", "create", *args])
        assert result.exit_code == 1
        return result.output.splitlines()

    assert run(str(FINGERS)) == [
        "only --google: a local workbook is made by `climblog check MODULE --apply`"
    ]
    assert run(str(FINGERS), "--google") == [
        f"module 'finger_strength' is already in the config ({config.parent / 'fingers.xlsx'})"
    ]
    broken = tmp_path / "broken.yaml"
    broken.write_text("module: x\n", encoding="utf-8")
    assert run(str(broken), "--google")[0].startswith(str(broken))
    assert run(str(FINGERS), "--google", "--config", str(tmp_path / "none.toml"))[0].endswith(
        "no config file here (see README, Configure)"
    )
    yaml = tmp_path / "test-sync.yaml"
    yaml.write_text(SYNC_MODULE, encoding="utf-8")

    def refuse(spreadsheet_id: str, requests: object) -> object:
        raise StorageError("Google answered 400: Invalid requests")

    client.batch_update = refuse  # type: ignore[method-assign,assignment]
    assert run(str(yaml), "--google") == ["error: Google answered 400: Invalid requests"]
    assert client.books == {}


# ---- Live (CLIMBLOG_GOOGLE_LIVE=1) ----


@pytest.fixture
def live() -> Iterator[GSheets]:  # pragma: no cover - live only
    made = GSheets(RestSheetsClient(load_config(config_path()).google_session), live=True)
    yield made
    made.close()


@pytest.mark.skipif(not LIVE, reason="set CLIMBLOG_GOOGLE_LIVE=1 to run on Google")
def test_moving_the_fictional_journal_to_google(
    live: GSheets, tmp_path: Path
) -> None:  # pragma: no cover - live only
    module = load_module(ROOT / "modules" / "journal.yaml")
    local = XlsxBackend(generate(module, tmp_path, seed=3).path)
    report = move_to_google(module, local, live.new())
    assert report.differences == []
