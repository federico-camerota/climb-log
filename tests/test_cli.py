# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from conftest import WriteYaml
from typer.testing import CliRunner

from climblog import cli

runner = CliRunner()


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace uvicorn.run with a stub that records its arguments instead of starting a server."""
    calls: list[dict[str, Any]] = []

    def fake_run(app: str, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)
    return calls


@pytest.mark.parametrize("args", [["--help"], ["serve", "--help"]])
def test_help_exits_cleanly(args: list[str]) -> None:
    assert runner.invoke(cli.app, args).exit_code == 0


def test_serve_binds_localhost_on_default_port(uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.app, ["serve"])
    assert result.exit_code == 0
    assert uvicorn_calls == [
        {
            "app": "climblog.main:create_app",
            "factory": True,
            "host": "127.0.0.1",
            "port": 8000,
            "reload": False,
        }
    ]


def test_serve_port_and_reload_options(uvicorn_calls: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.app, ["serve", "--port", "8123", "--reload"])
    assert result.exit_code == 0
    assert uvicorn_calls[0]["port"] == 8123
    assert uvicorn_calls[0]["reload"] is True
    assert uvicorn_calls[0]["host"] == "127.0.0.1"


def test_serve_has_no_host_option(uvicorn_calls: list[dict[str, Any]]) -> None:
    # Binding beyond localhost must wait for LAN mode with a PIN (D-010).
    result = runner.invoke(cli.app, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert uvicorn_calls == []


# ---- climblog check ----

FINGERS = Path("design/modules/finger-strength.yaml").absolute()
MOCKUP = Path("design/mockups/mockup-finger-strength.xlsx")


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A config with the fictional finger-strength mock-up, named by CLIMBLOG_CONFIG."""
    shutil.copy(MOCKUP, tmp_path / "fingers.xlsx")
    file = tmp_path / "config.toml"
    file.write_text(
        f'[modules.finger_strength]\ndefinition = "{FINGERS}"\nworkbook = "fingers.xlsx"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLIMBLOG_CONFIG", str(file))
    return file


def add_module(config: Path, name: str, definition: Path, workbook: str) -> None:
    with config.open("a", encoding="utf-8") as file:
        file.write(f'[modules.{name}]\ndefinition = "{definition}"\nworkbook = "{workbook}"\n')


def test_check_in_sync_changes_nothing(config: Path) -> None:
    workbook = config.parent / "fingers.xlsx"
    before = workbook.stat().st_mtime_ns
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 0
    assert result.output == f"finger_strength ({workbook})\n  ok\n"
    assert workbook.stat().st_mtime_ns == before
    assert not (config.parent / ".local").exists()  # no backup folder either


def test_check_lists_differences_and_fails(config: Path) -> None:
    workbook = openpyxl.load_workbook(config.parent / "fingers.xlsx")
    del workbook["Curl sets"]
    workbook["_meta"]["B3"] = 2
    workbook.save(config.parent / "fingers.xlsx")
    result = runner.invoke(cli.app, ["check", "finger_strength"])
    assert result.exit_code == 1
    assert result.output.splitlines()[1:] == [
        "  sync: _meta: synced with v2, the YAML is v3",
        "  sync: Curl sets: the tab is missing",
    ]


def test_check_info_alone_passes(config: Path) -> None:
    workbook = openpyxl.load_workbook(config.parent / "fingers.xlsx")
    workbook["_settings"].delete_rows(2)
    workbook.save(config.parent / "fingers.xlsx")
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 0
    assert "  info: _settings: no row for " in result.output


def test_check_reports_each_module(config: Path, write: WriteYaml) -> None:
    add_module(config, "broken", write("module: broken\n"), "fingers.xlsx")
    add_module(config, "fingers", FINGERS, "fingers.xlsx")
    result = runner.invoke(cli.app, ["check", "finger_strength", "broken", "fingers"])
    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[1] == "  ok"
    assert lines[2].startswith("broken (") and "test.yaml" in lines[3]
    assert lines[-1] == f"  error: {FINGERS} defines module 'finger_strength', not 'fingers'"


def test_check_missing_workbook(config: Path) -> None:
    (config.parent / "fingers.xlsx").unlink()
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert result.output.splitlines()[1].startswith("  error: workbook not found")


def test_check_option_wins_over_environment(config: Path, tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["check", "--config", str(tmp_path / "other.toml")])
    assert result.exit_code == 1
    assert (
        result.output == f"{tmp_path / 'other.toml'}: no config file here (see README, Configure)\n"
    )


def test_check_unknown_or_no_modules(config: Path) -> None:
    result = runner.invoke(cli.app, ["check", "journal", "shoulder"])
    assert (result.exit_code, result.output) == (1, "not in the config: journal, shoulder\n")
    config.write_text("", encoding="utf-8")
    result = runner.invoke(cli.app, ["check"])
    assert (result.exit_code, result.output) == (1, f"{config}: no modules configured\n")
