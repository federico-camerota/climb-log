# SPDX-License-Identifier: GPL-3.0-or-later
"""Prefilled fields and next-morning items (D-022, D-114): `from:` and `from_map` checked, a
value taken from another module's same-day record (copied, joined, mapped, or none when this
field can't take it), the prefill API with no, one or two records that day, `from:` fields the
app config can't serve, and Today asking for next-morning fields for up to three days. All
fictional."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import Module
from climblog.modules.forms import due, form_fields, forms_of
from climblog.modules.prefill import Source, parse_from, source_problems, value_from
from climblog.modules.schema import BaseField
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

# The module prefilled from: a diary of sessions, two on some days.
DIARY = """\
module: diary
name: Diary
version: 1
kind: journal
entities:
  session:
    label: Session
    tab: Sessions
    key: [date, session_no]
    fields:
      date: {type: date, required: true}
      session_no: {type: integer, min: 1, default: 1}
      place: {type: choice, choices: [Gym, Crag]}
      kind: {type: choice, choices: [Climbing, Board]}
      grade: {type: grade, systems: [french, font]}
      minutes: {type: number}
forms:
  session: {entity: session}
"""

# The module that prefills: a check-in with copied, joined-and-mapped and next-morning fields.
CHECKIN = """\
module: rehab
name: Rehab
version: 1
kind: journal
scales:
  pain: {min: 0, max: 10, direction: lower_better}
entities:
  checkin:
    label: Check-in
    tab: Checkins
    key: [date]
    fields:
      date: {type: date, required: true}
      activity:
        type: choice
        choices: [Gym climbing, Crag climbing, Board]
        from: diary.session.place+kind
        from_map:
          "Gym · Climbing": Gym climbing
          "Crag · Climbing": Crag climbing
          "Gym · Board": Board
      grade: {type: grade, systems: [french], from: diary.session.grade}
      minutes: {type: integer, from: diary.session.minutes}
      pain_during: {type: scale, scale: pain}
      pain_next_am: {type: scale, scale: pain, phase: next_day}
forms:
  checkin: {entity: checkin}
  next_morning: {entity: checkin, phase: next_day}
"""
DAY = dt.date(2026, 11, 18)


@pytest.fixture
def checkin(load: LoadYaml) -> Module:
    return load(CHECKIN)


# ---- The module file ----


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("from: diary.session.grade}", "from: diary.grade}"),
        ("from: diary.session.grade}", "from: Diary.session.grade}"),
        ("from: diary.session.grade}", "from: diary.session.grade+}"),
    ],
)
def test_from_syntax(problems: Problems, change: str, message: str) -> None:
    found = problems(CHECKIN.replace(change, message))
    assert any("is not module.entity.field" in line for line in found), found


def test_from_map_needs_from(problems: Problems) -> None:
    text = CHECKIN.replace(
        "minutes: {type: integer, from: diary.session.minutes}",
        "minutes: {type: integer, from_map: {a: b}}",
    )
    assert any("from_map needs a `from:`" in line for line in problems(text))


def test_parse_from() -> None:
    assert parse_from("journal.session.setting+session_type") == Source(
        "journal", "session", ("setting", "session_type")
    )
    assert parse_from("journal.session") is None


# ---- Values ----


def field(module: Module, name: str) -> BaseField:
    found = module.entities["checkin"].fields[name]
    assert isinstance(found, BaseField)
    return found


@pytest.mark.parametrize(
    ("name", "record", "expected"),
    [
        ("activity", {"place": "Gym", "kind": "Climbing"}, "Gym climbing"),
        ("activity", {"place": "Crag", "kind": "Board"}, None),  # not mapped
        ("activity", {"place": None, "kind": "Climbing"}, None),  # "Climbing" alone: no map
        ("grade", {"grade": "6B+"}, None),  # a Font grade: not a French one
        ("grade", {"grade": "6b+"}, "6b+"),
        ("grade", {"grade": None}, None),
        ("minutes", {"minutes": 90.0}, 90),
        ("minutes", {"minutes": 45.5}, None),  # an integer field
    ],
)
def test_a_value_from_the_other_record(
    checkin: Module, name: str, record: dict[str, Value], expected: Value
) -> None:
    source = parse_from(field(checkin, name).from_ or "")
    assert source is not None
    assert value_from(checkin, field(checkin, name), source, record) == expected


def test_sources_the_app_config_lacks(load: LoadYaml, checkin: Module) -> None:
    assert source_problems(checkin, lambda m: None) == {
        ("checkin", n): f"checkin.{n}: not prefilled (no module 'diary' in the app config)"
        for n in ("activity", "grade", "minutes")
    }
    diary = load(DIARY.replace("      minutes: {type: number}\n", ""))
    found = source_problems(checkin, lambda m: diary if m == "diary" else None)
    assert found == {
        ("checkin", "minutes"): "checkin.minutes: not prefilled "
        "(diary.session has no field 'minutes')"
    }


# ---- The API ----


@pytest.fixture
def client(load: LoadYaml, checkin: Module, tmp_path: Path) -> Iterator[TestClient]:
    diary = load(DIARY)
    catalog = Catalog(AppConfig())
    for name, module in (("diary", diary), ("rehab", checkin)):
        repo = XlsxBackend(tmp_path / f"{name}.xlsx")
        sync_module(module, repo)
        catalog.entries[name] = Entry(
            name, module, [], CachedRepository(name, repo, Snapshots(tmp_path / name))
        )
        if name == "diary":
            write = RecordWriter(module, repo)
            write.add("session", {"date": "2026-11-17", "place": "Gym", "kind": "Climbing",
                                  "grade": "6c", "minutes": 90})  # fmt: skip
            write.add("session", {"date": "2026-11-18", "session_no": 1, "place": "Gym",
                                  "kind": "Board"})  # fmt: skip
            write.add("session", {"date": "2026-11-18", "session_no": 2, "place": "Crag",
                                  "kind": "Climbing", "grade": "7a"})  # fmt: skip
    yield TestClient(create_app(catalog=catalog))


def prefill(client: TestClient, day: str) -> dict[str, Any]:
    response = client.get(f"/api/modules/rehab/checkin/prefill?date={day}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_one_record_that_day(client: TestClient) -> None:
    assert prefill(client, "2026-11-17") == {
        "sources": [
            {
                "module": "diary",
                "entity": "session",
                "label": "Session 1 · Gym climbing · 6c · 90",
                "key": {"date": "2026-11-17", "session_no": 1},
                "values": {"activity": "Gym climbing", "grade": "6c", "minutes": 90},
            }
        ],
        "notes": [],
    }


def test_two_records_that_day(client: TestClient) -> None:
    sources = prefill(client, "2026-11-18")["sources"]
    assert [(s["label"], s["values"]) for s in sources] == [
        ("Session 1 · Board", {"activity": "Board"}),
        ("Session 2 · Crag climbing · 7a", {"activity": "Crag climbing", "grade": "7a"}),
    ]


def test_no_record_that_day(client: TestClient) -> None:
    assert prefill(client, "2026-11-19") == {"sources": [], "notes": []}


def test_nothing_is_written(client: TestClient) -> None:
    prefill(client, "2026-11-17")
    assert client.get("/api/modules/rehab/checkin").json()["records"] == []


def test_a_source_not_configured_is_a_note(checkin: Module, tmp_path: Path) -> None:
    catalog = Catalog(AppConfig())
    repo = XlsxBackend(tmp_path / "rehab.xlsx")
    sync_module(checkin, repo)
    cached = CachedRepository("rehab", repo, Snapshots(tmp_path / "s"))
    catalog.entries["rehab"] = Entry("rehab", checkin, [], cached)
    client = TestClient(create_app(catalog=catalog))
    notes = prefill(client, "2026-11-17")["notes"]
    assert "checkin.grade: not prefilled (no module 'diary' loaded)" in notes
    (info,) = client.get("/api/modules").json()["modules"]
    assert "checkin.grade: not prefilled (no module 'diary' in the app config)" in info["notes"]


# ---- Next-morning items on Today ----


def checkin_on(day: dt.date, **values: Value) -> dict[str, Value]:
    return {"date": day, "pain_during": 2, **values}


def mornings(module: Module, rows: list[dict[str, Value]], day: dt.date = DAY) -> list[Any]:
    return [
        (i.label, i.key["date"], i.status)
        for i in due(module, {"checkin": rows}, day).items
        if i.form == "next_morning"
    ]


def test_next_morning_items_for_three_days(checkin: Module) -> None:
    rows = [checkin_on(DAY - dt.timedelta(days=n)) for n in range(5)]
    rows[2]["pain_next_am"] = 1  # filled two days later
    assert mornings(checkin, rows) == [
        ("Next morning · Check-in of Tue 17", dt.date(2026, 11, 17), "missing"),
        ("Next morning · Check-in of Sun 15", dt.date(2026, 11, 15), "missing"),
    ]  # 18 Nov is today; 14 Nov is past the three days


def test_the_day_itself_does_not_wait_for_the_morning(checkin: Module) -> None:
    found = due(checkin, {"checkin": [checkin_on(DAY, activity="Board", grade="6a",
                                                 minutes=60)]}, DAY)  # fmt: skip
    assert [(i.form, i.status) for i in found.items] == [("checkin", "done")]


def test_a_next_morning_form_holds_its_fields_only(checkin: Module) -> None:
    assert form_fields(checkin, forms_of(checkin)["next_morning"]) == ["pain_next_am"]


def test_today_lists_them(client: TestClient) -> None:
    client.post("/api/modules/rehab/checkin", json={"values": {"date": "2026-11-17"}})
    modules = client.get("/api/today?date=2026-11-18").json()["modules"]
    (rehab,) = [m for m in modules if m["module"] == "rehab"]
    labels = [(i["form"], i["label"], i["status"]) for i in rehab["items"]]
    assert ("next_morning", "Next morning · Check-in of Tue 17", "missing") in labels
