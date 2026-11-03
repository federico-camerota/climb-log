# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet's Summary tab (D-085): the `summary:` block checked at load, computed in the app,
and written by schema sync with its drift check. Fictional data only; the formulas against the
app on LibreOffice and Google in `test_summary_parity.py`."""

import datetime as dt
from pathlib import Path

import openpyxl
import pytest
from conftest import Problems
from fake_sheets import FakeSheetsClient

from climblog.expr import Value
from climblog.modules import load_module
from climblog.modules.summary import summarize
from climblog.storage import GSheetsBackend, XlsxBackend, check_schema, find_drift, sync_module

JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
OCT = dt.date(2026, 10, 1)


def session(day: int, n: int = 1, **values: Value) -> dict[str, Value]:
    return {"date": OCT + dt.timedelta(days=day - 1), "session_no": n, **values}


def test_the_summary_for_a_day() -> None:
    rows = [
        session(20, venue="[ESEMPIO] Nord", session_type="Climbing", overall_status="GOOD"),
        session(28, 1, wb_score=6.0, ph_readiness=4.4, mn_score=7.0, feel_score=5.0),
        session(
            28,
            2,
            venue="[ESEMPIO] Sud",
            session_type="Strength",
            overall_status="LOW",
            wb_score=6.0,
            ph_readiness=3.25,
            mn_score=7.0,
        ),
    ]
    found = summarize(JOURNAL, {"session": rows}, {}, dt.date(2026, 10, 30))
    values = found.values
    assert (values["last_session"], values["last_type"], values["last_venue"]) == (
        dt.date(2026, 10, 28),
        "Strength",
        "[ESEMPIO] Sud",
    )
    assert values["days_ago"] == "2 day(s) ago"
    assert values["latest_status"] == "LOW"
    assert (values["weakest"], values["lowest_score"]) == ("Physical", 3.3)  # 3.25, as the sheet
    assert values["weakest_area"] == "Physical · 3.3"  # for the app's reasons (D-102)
    assert values["low_sessions"] == 1
    assert str(values["text"]).startswith("RECOVER — ")
    # side by side: newest first, a day's second session before its first, blank past the first
    assert [s["date"] for s in found.sessions] == [
        dt.date(2026, 10, 28),
        dt.date(2026, 10, 28),
        dt.date(2026, 10, 20),
        None,
    ]
    assert [s["venue"] for s in found.sessions][:3] == ["[ESEMPIO] Sud", None, "[ESEMPIO] Nord"]
    assert summarize(JOURNAL, {"session": rows}, {}, dt.date(2026, 10, 28)).values["days_ago"] == (
        "Today"
    )


def test_no_session_yet() -> None:
    values = summarize(JOURNAL, {}, {}, OCT).values
    assert (values["days_ago"], values["weakest"], values["text"]) == (
        None,
        None,
        "Log a session to get guidance",
    )


SUMMARY = """\
module: s
name: Summary
version: 1
kind: journal
entities:
  session:
    label: Session
    tab: Sessions
    key: [date]
    fields:
      date: {type: date, required: true}
      mood: {type: integer, min: 1, max: 10}
summary:
  title: A summary
  values:
    last_mood: "last(session.mood, until=date)"
"""


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (
            "  rows: [{label: Mood, value: lats_mood}]\n",
            "summary.rows[0].value: no value 'lats_mood' (the module has no recommendation:)",
        ),
        (
            "  rows: [{label: Advice, value: text}]\n",
            "summary.rows[0].value: no value 'text' (the module has no recommendation:)",
        ),
        (
            "    app: {expr: 'last_mood + 1', sheet_formula: false}\n"
            "  rows: [{label: Mood, value: app}]\n",
            "summary.rows[0].value: 'app' is app only (sheet_formula: false)",
        ),
        (
            "    app: {expr: 'last_mood + 1', sheet_formula: false}\n"
            "    more: 'app + 1'\n"
            "  rows: [{label: Mood, value: more}]\n",
            "summary.values.more: reads app: app only (sheet_formula: false)",
        ),
        (
            "  tab: Sessions\n  rows: [{label: Mood, value: last_mood}]\n",
            "summary.tab: 'Sessions' is already a tab of the module",
        ),
        (
            "  rows: [{label: Mood, value: last_mood}]\n"
            "  side_by_side: {entity: session, groups: [{label: X, fields: [mod]}]}\n",
            "summary.side_by_side.groups[0].fields[0]: 'session' has no field or derived",
        ),
    ],
)
def test_a_summary_is_checked_when_the_module_loads(
    problems: Problems, block: str, expected: str
) -> None:
    found = problems(SUMMARY + block)
    assert any(expected in line for line in found), found


def test_n_must_be_from_1_to_12(problems: Problems) -> None:
    text = SUMMARY.replace(
        'last_mood: "last(session.mood, until=date)"',
        'last_mood: "last(session.mood, until=date, n=13)"',
    )
    found = problems(text + "  rows: [{label: Mood, value: last_mood}]\n")
    assert any("n must be a whole number from 1 to 12" in line for line in found), found


# ---- Written by schema sync ----


def test_sync_writes_the_summary_first_and_keeps_it(tmp_path: Path) -> None:
    path = tmp_path / "journal.xlsx"
    repo = XlsxBackend(path)
    done = sync_module(JOURNAL, repo)
    assert "created tab 'Summary'" in done
    book = openpyxl.load_workbook(path)
    sheet = book.worksheets[0]
    assert sheet.title == "Summary"
    assert (sheet["A1"].value, sheet["A3"].value, sheet["B3"].value) == (
        "Summary — Recent sessions",
        "Day",
        "=TODAY()",
    )
    assert sheet["A4"].value == "Last session"
    assert str(sheet["B4"].value).startswith("=")
    assert [d for d in check_schema(JOURNAL, repo) if d.tab == "Summary"] == []
    assert find_drift(JOURNAL, repo) == []
    assert not [line for line in sync_module(JOURNAL, repo) if "Summary" in line]  # unchanged


def test_a_summary_cell_changed_by_hand_is_drift_and_put_back(tmp_path: Path) -> None:
    path = tmp_path / "journal.xlsx"
    repo = XlsxBackend(path)
    sync_module(JOURNAL, repo)
    book = openpyxl.load_workbook(path)
    book["Summary"]["B6"] = "GOOD"  # the latest status, typed over
    book.save(path)
    [drift] = find_drift(JOURNAL, repo)
    assert (drift.tab, drift.row, drift.column, drift.sheet) == ("Summary", 6, "c1", "GOOD")
    assert "Summary: rewrote 1 changed cells" in sync_module(JOURNAL, repo)
    assert find_drift(JOURNAL, repo) == []


def test_a_missing_summary_is_a_sync_difference(tmp_path: Path) -> None:
    path = tmp_path / "journal.xlsx"
    repo = XlsxBackend(path)
    sync_module(JOURNAL, repo)
    book = openpyxl.load_workbook(path)
    del book["Summary"]
    book.save(path)
    missing = [d for d in check_schema(JOURNAL, repo) if d.tab == "Summary"]
    assert [(d.level, d.message) for d in missing] == [("sync", "the tab is missing")]


def test_sync_on_google_writes_the_summary_and_finds_no_drift() -> None:
    client = FakeSheetsClient()
    repo = GSheetsBackend(None, client)
    assert "created tab 'Summary'" in sync_module(JOURNAL, repo)
    assert repo.spreadsheet_id is not None
    first = client.books[repo.spreadsheet_id]["sheets"][0]["properties"]["title"]
    assert first == "Summary"
    assert find_drift(JOURNAL, repo) == []
    assert not [line for line in sync_module(JOURNAL, repo) if "Summary" in line]


def test_an_app_only_value_is_not_written_to_the_sheet(tmp_path: Path) -> None:
    path = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(path))
    sheet = openpyxl.load_workbook(path)["Summary"]
    written = [str(c.value) for row in sheet.iter_rows() for c in row if c.value is not None]
    assert "wb_latest" in written  # a value the rows read, below them
    assert "weakest_area" not in written  # app only (D-102)


def test_a_reason_can_be_a_summary_value(tmp_path: Path) -> None:
    from climblog.catalog import Catalog, Entry
    from climblog.config import AppConfig
    from climblog.storage import CachedRepository, RecordWriter, Snapshots

    path = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(path))
    RecordWriter(JOURNAL, XlsxBackend(path)).add(
        "session", {"date": dt.date(2026, 10, 28), "wb_mood_pre": 3, "ph_pre_fingers": 2}
    )
    catalog = Catalog(AppConfig())
    cached = CachedRepository("journal", XlsxBackend(path), Snapshots(tmp_path / "s"))
    entry = Entry("journal", JOURNAL, [], cached)
    advice = catalog.advice(entry, dt.date(2026, 10, 30))
    assert advice is not None
    found = {r.name: r.value for r in advice.reasons}
    values = summarize(JOURNAL, catalog.full_tables(entry)[0], {}, dt.date(2026, 10, 30)).values
    assert found["weakest_area"] == values["weakest_area"] is not None
