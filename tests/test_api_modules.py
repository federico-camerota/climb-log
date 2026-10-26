# SPDX-License-Identifier: GPL-3.0-or-later
"""The read API: modules with their schemas, records with derived values (D-058)."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from climblog.catalog import Catalog
from climblog.config import load_config
from climblog.main import create_app

FINGERS = Path("design/modules/finger-strength.yaml").absolute()
MOCKUP = Path("design/mockups/mockup-finger-strength.xlsx")


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """The fictional finger-strength mock-up, a module whose YAML is broken, snapshots in tmp."""
    shutil.copy(MOCKUP, tmp_path / "fingers.xlsx")
    (tmp_path / "broken.yaml").write_text("module: broken\n", encoding="utf-8")
    file = tmp_path / "config.toml"
    file.write_text(
        f'[modules.finger_strength]\ndefinition = "{FINGERS}"\nworkbook = "fingers.xlsx"\n'
        '[modules.broken]\ndefinition = "broken.yaml"\nworkbook = "broken.xlsx"\n'
        '[snapshots]\nfolder = "snapshots"\n',
        encoding="utf-8",
    )
    return file


@pytest.fixture
def client(config: Path) -> TestClient:
    return TestClient(create_app(catalog=Catalog(load_config(config))))


def test_modules_are_listed_with_their_schema(client: TestClient) -> None:
    response = client.get("/api/modules")
    assert response.status_code == 200
    body = response.json()
    fingers, broken = body["modules"]
    assert (fingers["id"], fingers["name"], fingers["version"], fingers["kind"]) == (
        "finger_strength",
        "Finger strength",
        3,
        "journal",
    )
    assert fingers["problems"] == []
    schema = fingers["module_schema"]
    assert set(schema["entities"]) == {"session", "hang_set", "curl_set"}
    assert schema["entities"]["session"]["fields"]["date"] == {"type": "date", "required": True}
    assert broken["id"] == "broken" and broken["module_schema"] is None
    assert any("name" in problem for problem in broken["problems"])
    assert body["problems"] == []


def test_records_come_with_their_derived_values(client: TestClient, config: Path) -> None:
    response = client.get("/api/modules/finger_strength/session")
    assert response.status_code == 200
    body = response.json()
    assert (body["module"], body["entity"], body["offline"]) == (
        "finger_strength",
        "session",
        False,
    )
    assert body["as_of"] is not None
    first = body["records"][0]
    assert first["values"]["date"] == "2026-10-14"  # a date field reads as a day
    assert first["values"]["session_type"] == "Max hangs"
    assert first["values"]["start_time"] == "18:30:00"
    assert first["derived"]["readiness"] == 8.0  # 11 - mean(2, 3, 4)
    assert first["derived"]["readiness_status"] == "GOOD"
    assert first["derived"]["n_sets"] == 4
    assert first["rows"] == {"Sessions": 3}
    assert (config.parent / "snapshots" / "finger_strength.json.gz").exists()


def test_data_issues_of_the_entitys_tabs(client: TestClient) -> None:
    sets = client.get("/api/modules/finger_strength/hang_set").json()
    assert {issue["tab"] for issue in sets["issues"]} == {"Hang sets"}
    assert any("no Sessions row" in issue["message"] for issue in sets["issues"])  # the orphan
    sessions = client.get("/api/modules/finger_strength/session").json()
    assert all(issue["tab"] == "Sessions" for issue in sessions["issues"])


def test_offline_the_snapshot_is_served(client: TestClient, config: Path) -> None:
    online = client.get("/api/modules/finger_strength/session").json()
    (config.parent / "fingers.xlsx").unlink()
    fresh = TestClient(create_app(catalog=Catalog(load_config(config))))  # a new app session
    offline = fresh.get("/api/modules/finger_strength/session").json()
    assert offline["offline"] is True
    assert offline["records"] == online["records"]


def test_errors(client: TestClient, config: Path) -> None:
    assert client.get("/api/modules/nope/session").status_code == 404
    assert client.get("/api/modules/finger_strength/nope").status_code == 404
    broken = client.get("/api/modules/broken/session")
    assert broken.status_code == 409
    assert broken.json()["detail"]["message"] == "module 'broken' doesn't load"
    (config.parent / "fingers.xlsx").unlink()  # no workbook and no snapshot yet
    missing = client.get("/api/modules/finger_strength/session")
    assert missing.status_code == 503
    assert "workbook not found" in missing.json()["detail"]


def test_the_catalog_loads_from_the_app_config_on_first_use(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLIMBLOG_CONFIG", str(config))
    app = create_app()
    assert app.state.catalog is None  # nothing read when the app is built
    modules = TestClient(app).get("/api/modules").json()["modules"]
    assert [m["id"] for m in modules] == ["finger_strength", "broken"]


def test_a_missing_config_serves_no_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLIMBLOG_CONFIG", str(tmp_path / "none.toml"))
    body = TestClient(create_app()).get("/api/modules").json()
    assert body["modules"] == []
    assert body["problems"] == [
        f"{tmp_path / 'none.toml'}: no config file here (see README, Configure)"
    ]


def test_a_module_whose_id_differs_is_listed_with_the_problem(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    file.write_text(
        f'[modules.fingers]\ndefinition = "{FINGERS}"\nworkbook = "fingers.xlsx"\n',
        encoding="utf-8",
    )
    (entry,) = Catalog(load_config(file)).entries.values()
    assert entry.module is None
    assert entry.problems == [f"{FINGERS} defines module 'finger_strength', not 'fingers'"]
