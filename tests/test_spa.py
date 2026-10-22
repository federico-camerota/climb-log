# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from climblog.main import create_app

INDEX = "<!doctype html><div id=root></div>"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    """A fake `make build` output."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX)
    (static / "assets" / "app-1a2b.js").write_text("console.log('app')")
    (static / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    (tmp_path / "secret.txt").write_text("outside the static dir")
    return static


@pytest.fixture
def client(static_dir: Path) -> TestClient:
    return TestClient(create_app(static_dir=static_dir))


@pytest.mark.parametrize("path", ["/", "/explore", "/log/journal/2026-10-20"])
def test_app_paths_return_index(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_assets_are_served(client: TestClient) -> None:
    response = client.get("/assets/app-1a2b.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_root_files_are_served(client: TestClient) -> None:
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.content == b"\x00\x00\x01\x00"


def test_missing_asset_is_404(client: TestClient) -> None:
    assert client.get("/assets/missing.js").status_code == 404


@pytest.mark.parametrize("path", ["/api", "/api/nope", "/api/modules/x/y"])
def test_unknown_api_path_is_json_404(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_api_routes_take_precedence(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


@pytest.mark.parametrize("path", ["/%2e%2e/secret.txt", "/..%2fsecret.txt"])
def test_files_outside_static_dir_are_not_served(client: TestClient, path: str) -> None:
    # The handler receives "../secret.txt"; it must fall back to the app, not read the file.
    response = client.get(path)
    assert response.request.url.path == "/../secret.txt"
    assert response.text == INDEX


def test_unbuilt_frontend_explains_what_to_do(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=tmp_path / "missing"))
    response = client.get("/")
    assert response.status_code == 503
    assert "make build" in response.text
    assert client.get("/api/health").status_code == 200
