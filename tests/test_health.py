# SPDX-License-Identifier: GPL-3.0-or-later
from fastapi.testclient import TestClient

from climblog import __version__
from climblog.main import create_app


def test_health_reports_ok_and_version() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_unknown_api_path_is_404() -> None:
    client = TestClient(create_app())
    assert client.get("/api/does-not-exist").status_code == 404
