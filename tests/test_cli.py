# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

import pytest
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
