# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /api/recommendation?date=` (D-076): each module's recommendation for a day, with its
reasons. Fictional data only."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml
from fastapi.testclient import TestClient

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.main import create_app
from climblog.modules import Module
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

MODULE = """\
module: test_api_recommend
name: Test API recommend
version: 1
kind: journal
entities:
  session:
    label: Session
    tab: Sessions
    key: [date]
    fields:
      date: {type: date, required: true}
      status: {type: choice, choices: [GOOD, WATCH, LOW]}
recommendation:
  values:
    last_session: "last(session.date, until=date)"
    latest: "last(session.status, until=date)"
  rules:
    - {if: "not notnull(last_session)", message: Log a session first.}
    - {if: "latest == 'LOW'", headline: RECOVER, message: Rest.}
    - {message: Train.}
  reasons: {last_session: Last session, latest: Latest status}
"""
PLAIN = MODULE.split("recommendation:")[0]


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


def client_for(tmp_path: Path, **entries: tuple[Module, Path]) -> TestClient:
    catalog = Catalog(AppConfig())
    for name, (module, path) in entries.items():
        cached = CachedRepository(name, XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
        catalog.entries[name] = Entry(name, module, [], cached)
    return TestClient(create_app(catalog=catalog))


def workbook(module: Module, path: Path, *sessions: tuple[dt.date, str]) -> Path:
    sync_module(module, XlsxBackend(path))
    writer = RecordWriter(module, XlsxBackend(path))
    for day, status in sessions:
        writer.add("session", {"date": day, "status": status})
    return path


def test_the_recommendation_for_a_day(module: Module, tmp_path: Path) -> None:
    path = workbook(
        module,
        tmp_path / "a.xlsx",
        (dt.date(2026, 10, 20), "LOW"),
        (dt.date(2026, 10, 25), "GOOD"),
    )
    client = client_for(tmp_path, journal=(module, path))

    body = client.get("/api/recommendation", params={"date": "2026-10-22"}).json()
    assert body["date"] == "2026-10-22"
    assert body["problems"] == []
    [item] = body["items"]
    assert (item["module"], item["headline"], item["text"]) == (
        "journal",
        "RECOVER",
        "RECOVER — Rest.",
    )
    assert item["reasons"] == [
        {"name": "last_session", "label": "Last session", "value": "2026-10-20"},
        {"name": "latest", "label": "Latest status", "value": "LOW"},
    ]
    assert item["offline"] is False

    later = client.get("/api/recommendation", params={"date": "2026-10-26"}).json()
    assert (later["items"][0]["headline"], later["items"][0]["text"]) == (None, "Train.")
    before = client.get("/api/recommendation", params={"date": "2026-10-01"}).json()
    assert before["items"][0]["message"] == "Log a session first."


def test_the_day_defaults_to_today(module: Module, tmp_path: Path) -> None:
    client = client_for(tmp_path, journal=(module, workbook(module, tmp_path / "a.xlsx")))
    body = client.get("/api/recommendation").json()
    assert body["date"] == dt.date.today().isoformat()


def test_modules_without_one_or_unreadable(load: LoadYaml, module: Module, tmp_path: Path) -> None:
    plain = load(PLAIN.replace("test_api_recommend", "test_plain"))
    client = client_for(
        tmp_path,
        plain=(plain, workbook(plain, tmp_path / "plain.xlsx")),
        journal=(module, tmp_path / "missing.xlsx"),  # no workbook and no snapshot
    )
    body = client.get("/api/recommendation", params={"date": "2026-10-22"}).json()
    assert body["items"] == []
    assert body["problems"][0].startswith("journal: workbook not found")
    assert client.get("/api/recommendation", params={"date": "22/10"}).status_code == 422
