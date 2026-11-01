# SPDX-License-Identifier: GPL-3.0-or-later
"""What is due on a day (D-080): the journal's forms, done / partial / missing, and the form
fields rule shared with the frontend's forms. Fictional data only."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml
from fastapi.testclient import TestClient

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import Module, load_module
from climblog.modules.forms import due, form_fields, forms_of
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
DAY = dt.date(2026, 10, 30)
FORMS = forms_of(JOURNAL)
PRE = form_fields(JOURNAL, FORMS["pre_session"])
POST = form_fields(JOURNAL, FORMS["post_session"])
Row = dict[str, Value]


def filled(names: list[str], **more: Value) -> Row:
    """Every field of the list filled (the status only asks whether a value is there)."""
    return {name: 1 for name in names} | more


def session(values: Row | None = None, *, n: int = 1, day: dt.date = DAY) -> Row:
    return {"date": day, "session_no": n, **(values or {})}


def items(*sessions: Row, rest_days: tuple[Row, ...] = ()) -> list[tuple[str, Value, str]]:
    found = due(JOURNAL, {"session": list(sessions), "rest_day": list(rest_days)}, DAY)
    return [(i.form, i.key.get("session_no"), i.status) for i in found.items]


def test_nothing_logged_yet_offers_a_session_or_a_rest_day() -> None:
    day = due(JOURNAL, {"session": [session(day=DAY - dt.timedelta(days=3))]}, DAY)
    assert [(i.form, i.status, i.key) for i in day.items] == [
        ("pre_session", "missing", {"date": DAY}),
        ("rest_day", "missing", {"date": DAY}),
    ]
    assert day.any_one is True
    assert (day.last, day.last_label) == (DAY - dt.timedelta(days=3), "Session")


def test_a_session_lists_its_pre_and_post_forms() -> None:
    assert items(session(filled(PRE))) == [
        ("pre_session", 1, "done"),
        ("post_session", 1, "missing"),
    ]


def test_partial_says_which_sections_are_missing() -> None:
    pre = filled(PRE)
    del pre["wb_mood_pre"], pre["mn_confidence"]
    found = due(JOURNAL, {"session": [session(pre | {"log_check": "Missing: Feel"})]}, DAY)
    first = found.items[0]
    assert (first.status, first.missing) == ("partial", ["Wellbeing · before", "Mental · before"])
    assert first.log_check == "Missing: Feel"
    assert found.any_one is False


def test_notes_are_optional() -> None:
    pre = {k: v for k, v in filled(PRE).items() if not k.endswith(("_note_pre", "partners"))}
    assert items(session(pre))[0] == ("pre_session", 1, "done")


def test_two_sessions_on_a_day() -> None:
    assert items(session(filled(PRE), n=2), session(filled(PRE + POST))) == [
        ("pre_session", 1, "done"),
        ("post_session", 1, "done"),
        ("pre_session", 2, "done"),
        ("post_session", 2, "missing"),
    ]


def test_a_rest_day_instead() -> None:
    rest: Row = {"date": DAY, "rest_type": "Full rest"}
    assert items(rest_days=(rest,)) == [("rest_day", None, "partial")]


def test_a_field_tracked_since_a_later_day_is_not_missing() -> None:
    pre = filled(PRE)
    del pre["ph_pre_elbows"]  # tracked since 2026-10-20 (journal.yaml)
    early = due(
        JOURNAL, {"session": [session(pre, day=dt.date(2026, 10, 1))]}, dt.date(2026, 10, 1)
    )
    assert early.items[0].status == "done"
    assert items(session(pre))[0] == ("pre_session", 1, "partial")


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ("pre_session", {"venue", "setting", "wb_sleep_hours", "wb_mood_pre"}),
        ("post_session", {"minutes", "notes", "wb_fatigue_post"}),
        ("rest_day", {"rest_type", "mood"}),
    ],
)
def test_form_fields_as_the_frontend(load: LoadYaml, form: str, expected: set[str]) -> None:
    """The fictional `DIARY` module of `frontend/src/test/api.ts`: the same fields per form."""
    module = load(DIARY)
    assert set(form_fields(module, forms_of(module)[form])) == expected


DIARY = """\
module: diary
name: Training diary
version: 1
kind: journal
scales:
  s10: {min: 1, max: 10, direction: higher_better}
  s10_down: {min: 1, max: 10, direction: lower_better}
entities:
  session:
    label: Session
    key: [date, session_no]
    anchor_tab: Session
    sections:
      info: {label: Session details, phase: pre, tab: Session}
      wb_pre: {label: Wellbeing · before, phase: pre, tab: Wellbeing}
      wb_post: {label: Wellbeing · after, phase: post, tab: Wellbeing}
    fields:
      date: {type: date, required: true, section: "*"}
      session_no: {type: integer, default: 1, min: 1, section: "*", label: "Session #"}
      venue: {type: text, section: info}
      setting: {type: choice, choices: [Indoor, Outdoor], section: info}
      minutes: {type: duration, section: info, phase: post}
      notes: {type: text, multiline: true, section: info, phase: post}
      old: {type: text, section: info, retired: true}
      wb_sleep_hours: {type: number, min: 0, max: 14, unit: h, section: wb_pre}
      wb_mood_pre: {type: scale, scale: s10, section: wb_pre}
      wb_fatigue_post: {type: scale, scale: s10_down, section: wb_post}
  rest_day:
    label: Rest day
    tab: Rest Days
    key: [date]
    fields:
      date: {type: date, required: true}
      rest_type: {type: choice, choices: [Full rest, Active recovery]}
      mood: {type: scale, scale: s10}
forms:
  pre_session: {entity: session, phase: pre, sections: [info, wb_pre]}
  post_session: {entity: session, phase: post, sections: [wb_post]}
  rest_day: {entity: rest_day}
"""


# ---- The API ----


@pytest.fixture
def client(load: LoadYaml, tmp_path: Path) -> TestClient:
    module = load(DIARY)
    path = tmp_path / "diary.xlsx"
    sync_module(module, XlsxBackend(path))
    writer = RecordWriter(module, XlsxBackend(path))
    writer.add("session", {"date": dt.date(2026, 10, 28), "venue": "[ESEMPIO] Nord"})
    writer.add("session", {"date": DAY, "setting": "Indoor", "wb_mood_pre": 7})
    catalog = Catalog(AppConfig())
    cached = CachedRepository("diary", XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
    catalog.entries["diary"] = Entry("diary", module, [], cached)
    return TestClient(create_app(catalog=catalog))


def test_the_api_lists_the_day(client: TestClient) -> None:
    body = client.get("/api/today", params={"date": "2026-10-30"}).json()
    assert body["problems"] == []
    [diary] = body["modules"]
    assert (diary["module"], diary["any_one"], diary["last"], diary["days_since"]) == (
        "diary",
        False,
        "2026-10-30",
        0,
    )
    assert [(i["form"], i["status"], i["missing"]) for i in diary["items"]] == [
        ("pre_session", "partial", ["Wellbeing · before"]),
        ("post_session", "missing", ["Session details", "Wellbeing · after"]),
    ]
    assert diary["items"][0]["key"] == {"date": "2026-10-30", "session_no": 1}


def test_the_api_on_a_day_without_records(client: TestClient) -> None:
    body = client.get("/api/today", params={"date": "2026-10-31"}).json()
    [diary] = body["modules"]
    assert diary["any_one"] is True
    assert [i["form"] for i in diary["items"]] == ["pre_session", "rest_day"]
    assert (diary["last"], diary["days_since"], diary["last_label"]) == ("2026-10-30", 1, "Session")


def test_modules_without_forms_are_left_out(load: LoadYaml, tmp_path: Path) -> None:
    plain: Module = load(DIARY.split("forms:")[0].replace("module: diary", "module: plain"))
    catalog = Catalog(AppConfig())
    cached = CachedRepository("plain", XlsxBackend(tmp_path / "x.xlsx"), Snapshots(tmp_path / "s"))
    catalog.entries["plain"] = Entry("plain", plain, [], cached)
    body = TestClient(create_app(catalog=catalog)).get("/api/today").json()
    assert body["modules"] == [] and body["problems"] == []
