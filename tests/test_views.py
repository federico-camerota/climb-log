# SPDX-License-Identifier: GPL-3.0-or-later
"""The views (dashboards) and their widgets' data (D-083). Fictional data only; the status board
is checked against the legacy formulas in `test_views_parity.py`."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient

from climblog.analytics import compute_view
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
OVERVIEW = JOURNAL.views["overview"] if JOURNAL.views else []
SETTINGS: dict[str, Value] = {"low_max": 4, "watch_max": 6, "trend_delta": 0.5}
OCT = dt.date(2026, 10, 1)


def session(day: int, n: int = 1, **values: Value) -> dict[str, Value]:
    return {"date": OCT + dt.timedelta(days=day - 1), "session_no": n, **values}


def widgets(*rows: dict[str, Value], day: dt.date = dt.date(2026, 10, 31)) -> list[dict[str, Any]]:
    return compute_view(JOURNAL, OVERVIEW, {"session": list(rows)}, SETTINGS, day)


def of(kind: str, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [w for w in found if w["widget"] == kind]


def test_the_kpis_read_the_latest_session_up_to_the_day() -> None:
    rows = [session(3, overall_status="GOOD"), session(10, overall_status="LOW")]
    status, since = of(
        "kpi", widgets(*rows, session(25, overall_status="WATCH"), day=OCT.replace(day=20))
    )
    assert status["value"] == "LOW"  # the session of the 25th is after the day
    assert since["value"] == 10
    assert [w["value"] for w in of("kpi", widgets())] == [None, None]


def test_a_days_second_session_is_the_latest() -> None:
    rows = [session(10, 2, overall_status="LOW"), session(10, 1, overall_status="GOOD")]
    assert of("kpi", widgets(*rows))[0]["value"] == "LOW"


def test_the_status_board_compares_the_last_4_with_the_4_before() -> None:
    scores = [5, 5, 5, 5, 7, 7, 7, 8]
    rows = [
        session(d, wb_score=s, wb_status="LOW" if s < 6 else "GOOD")
        for d, s in enumerate(scores, 1)
    ]
    [board] = of("status_board", widgets(*rows))
    wellbeing = board["rows"][0]
    assert wellbeing == {
        "label": "Wellbeing",
        "status": "GOOD",
        "score": 8,
        "average_last": 7.3,  # 7.25, rounded as the sheet (half away from zero)
        "average_previous": 5.0,
        "change": 2.3,
        "direction": "up",
        "low": 4,
    }
    assert board["rows"][1]["average_last"] is None  # no physical scores at all


def test_with_4_sessions_or_fewer_there_is_no_trend() -> None:
    [board] = of("status_board", widgets(*(session(d, wb_score=5) for d in range(1, 5))))
    row = board["rows"][0]
    assert (row["average_last"], row["average_previous"], row["direction"]) == (5.0, None, None)


def test_a_small_change_is_stable() -> None:
    scores = [5, 5, 5, 5, 5.4, 5.4, 5.4, 5.4]
    [board] = of(
        "status_board", widgets(*(session(d, wb_score=s) for d, s in enumerate(scores, 1)))
    )
    assert (board["rows"][0]["change"], board["rows"][0]["direction"]) == (0.4, "flat")


def test_the_line_has_every_session_with_bands_and_a_rolling_mean() -> None:
    rows = [session(d, wb_score=s) for d, s in [(1, 4), (2, 6), (3, None), (4, 8), (5, 9)]]
    [line] = of("line", widgets(*rows))
    assert [p["date"] for p in line["points"]] == [f"2026-10-0{d}" for d in range(1, 6)]
    assert line["points"][0]["key"] == {"session_no": 1}
    wellbeing = line["series"][0]
    assert wellbeing["label"] == "Wellbeing"
    assert wellbeing["values"] == [4.0, 6.0, None, 8.0, 9.0]
    assert wellbeing["rolling"] == [4.0, 5.0, 5.0, 6.0, 7.7]  # the values present among the last 4
    assert line["bands"] == [
        {"label": "LOW", "from": None, "to": 4.0},
        {"label": "WATCH", "from": 4.0, "to": 6.0},
        {"label": "GOOD", "from": 6.0, "to": None},
    ]
    assert (line["rolling"], line["last"]) == (4, 12)


def test_a_widget_not_drawn_yet_says_when_it_comes(load: LoadYaml) -> None:
    module = load(VIEW + "    - {widget: radar, entity: session}\n")
    assert module.views is not None
    [planned] = compute_view(module, module.views["main"], {}, {}, OCT)
    assert (planned["widget"], planned["kind"], planned["why"]) == (
        "planned",
        "radar",
        "comes with M5 or later",
    )


# ---- Part 2 (#78): calendar, side by side, reflections, rest days, monthly ----


def one(
    kind: str,
    *rows: dict[str, Value],
    rest: list[dict[str, Value]] | None = None,
    day: dt.date = dt.date(2026, 10, 31),
) -> dict[str, Any]:
    tables = {"session": list(rows), "rest_day": rest or []}
    [found] = [
        w for w in compute_view(JOURNAL, OVERVIEW, tables, SETTINGS, day) if w["widget"] == kind
    ]
    return found


def test_the_calendar_takes_a_days_worst_status_and_marks_rest_days() -> None:
    rows = [
        session(5, 1, overall_status="GOOD", setting="Indoor"),
        session(5, 2, overall_status="LOW", setting="Outdoor"),
        session(6, overall_status="WATCH", setting="Indoor"),
        session(8, overall_status="GOOD"),  # no setting: no letter
    ]
    rest: list[dict[str, Value]] = [
        {"date": OCT + dt.timedelta(days=6), "status": "GOOD"},
        {"date": OCT + dt.timedelta(days=7), "status": "LOW"},  # with a session: its letters
    ]
    found = one("heatmap_calendar", *rows, rest=rest)
    # from the first record's month, not a year of empty months
    assert (found["start"], found["end"], found["extra"]) == (
        "2026-10-01",
        "2026-10-31",
        "rest_day",
    )
    assert found["marks"] == [
        {"letter": "G", "label": "Indoor"},
        {"letter": "O", "label": "Outdoor"},
        {"letter": "H", "label": "Home wall"},
        {"letter": "R", "label": "rest day"},
    ]
    assert found["days"] == [
        {"date": "2026-10-05", "status": "LOW", "records": 2, "extra": None, "mark": "GO"},
        {"date": "2026-10-06", "status": "WATCH", "records": 1, "extra": None, "mark": "G"},
        {"date": "2026-10-07", "status": None, "records": 0, "extra": "GOOD", "mark": "R"},
        {"date": "2026-10-08", "status": "GOOD", "records": 1, "extra": "LOW", "mark": None},
    ]


def test_the_calendar_starts_at_most_months_back() -> None:
    old: dict[str, Value] = {"date": dt.date(2024, 3, 2), "status": "GOOD"}
    assert one("heatmap_calendar", rest=[old])["start"] == "2025-11-01"
    assert one("heatmap_calendar")["start"] == "2025-11-01"  # nothing logged: the 12 months


def test_the_last_sessions_side_by_side_newest_first_with_the_latest_notes() -> None:
    rows = [session(d, venue=f"[ESEMPIO] {d}", wb_note_pre=f"nota {d}") for d in range(1, 15)]
    found = one("side_by_side", *rows)
    assert found["last"] == 4
    assert [r["values"]["venue"] for r in found["records"]][:2] == ["[ESEMPIO] 14", "[ESEMPIO] 13"]
    assert len(found["records"]) == 12
    wellbeing = found["groups"][1]
    assert wellbeing["label"] == "Wellbeing"
    assert wellbeing["rows"][0] == {"field": "wb_sleep_quality", "label": "Sleep quality"}
    assert wellbeing["rows"][-1] == {"field": "wb_status", "label": "Wellbeing status"}
    assert found["notes"][0] == {
        "field": "wb_note_pre",
        "label": "Wellbeing — before",
        "text": "nota 14",
    }


def test_the_reflections_of_the_last_14_days_by_score() -> None:
    rows = [
        session(1, rf_good="[ESEMPIO] too old", rf_good_score=10),
        session(20, rf_good="[ESEMPIO] good", rf_good_score=6, reflect_status="GOOD"),
        session(
            25,
            rf_good="[ESEMPIO] better",
            rf_good_score=8,
            rf_off="[ESEMPIO] dita",
            rf_change="[ESEMPIO] riposo",
            reflect_status="NEEDS ATTENTION",
        ),
        session(28, rf_good="[ESEMPIO] same score, newer", rf_good_score=8),
        session(29, rf_good="[ESEMPIO] no score"),
        session(30, rf_good="", rf_good_score=9),
    ]
    found = one("text_feed", *rows)
    good = found["lists"][0]
    assert good["label"] == "Best 'what felt good'"
    assert [i["text"] for i in good["items"]] == [
        "[ESEMPIO] same score, newer",
        "[ESEMPIO] better",
        "[ESEMPIO] good",
    ]
    assert found["lists"][1]["items"] == []  # no 'what felt off' with a severity
    assert found["attention"]["label"] == "NEEDS ATTENTION"
    assert [i["texts"] for i in found["attention"]["items"]] == [
        ["[ESEMPIO] dita", "[ESEMPIO] riposo"]
    ]


def test_the_rest_days_of_the_last_14_days_with_averages_and_the_latest_note() -> None:
    rest: list[dict[str, Value]] = [
        {
            "date": OCT + dt.timedelta(days=d - 1),
            "wellbeing_score": w,
            "body_readiness": 7.0,
            "status": "GOOD",
            "note": n,
        }
        for d, w, n in [
            (2, 9.0, "[ESEMPIO] vecchia"),
            (20, 5.0, None),
            (25, 6.0, "[ESEMPIO] ok"),
            (30, 8.5, None),
        ]
    ]
    found = one("table", rest=rest)
    assert [c["label"] for c in found["columns"]][:3] == ["Date", "Rest type", "Wellbeing"]
    assert [r["date"] for r in found["rows"]] == ["2026-10-30", "2026-10-25", "2026-10-20"]
    assert found["averages"] == [
        {"field": "wellbeing_score", "label": "Wellbeing", "value": 6.5},
        {"field": "body_readiness", "label": "Body readiness", "value": 7.0},
    ]
    assert found["note"] == {"date": "2026-10-25", "text": "[ESEMPIO] ok"}


def test_the_monthly_averages_as_the_legacy_table() -> None:
    rows = [
        session(3, wb_score=6, ph_readiness=7, overall_status="LOW"),
        session(4, wb_score=7, overall_status="GOOD"),
        session(40, mn_score=5),  # November: after the day
    ]
    rest: list[dict[str, Value]] = [{"date": dt.date(2026, 9, 10), "wellbeing_score": 5.0}]
    found = one("monthly", *rows, rest=rest)
    assert (found["count_label"], found["overall"], found["months"]) == (
        "Sessions logged",
        "Overall",
        6,
    )
    september, october = found["rows"]
    assert september == {
        "month": "2026-09",
        "count": 0,
        "classes": [None] * 4,
        "overall": None,
        "low": None,
        "extra": [1.0, 5.0],
    }
    assert october == {
        "month": "2026-10",
        "count": 2,
        "classes": [6.5, 7.0, None, None],
        "overall": 6.8,
        "low": 1,
        "extra": [0.0, None],
    }


@pytest.mark.parametrize(
    ("widget", "expected"),
    [
        (
            "{widget: side_by_side, entity: sessions, groups: [{label: X, fields: [mood]}]}",
            "views.main[0].entity: no entity 'sessions'",
        ),
        (
            "{widget: side_by_side, entity: session, groups: [{label: X, fields: [mod]}]}",
            "views.main[0].groups[0].fields[0]: 'session' has no field or derived value 'mod'",
        ),
        (
            "{widget: table, entity: session, columns: [date], note: notes}",
            "views.main[0].note: 'session' has no field or derived value 'notes'",
        ),
        (
            "{widget: monthly, count: session, extra: [{label: X}]}",
            "views.main[0].extra[0]: give either count (an entity) or mean (entity.field)",
        ),
        (
            "{widget: heatmap_calendar, metric: session.nope}",
            "views.main[0].metric: 'session' has no field or derived value 'nope'",
        ),
        (
            "{widget: heatmap_calendar, metric: session.overall_status,"
            " mark: {field: rest_day.status, letters: {GOOD: G}}}",
            "views.main[0].mark.field: 'rest_day.status' is not a field of 'session'",
        ),
    ],
)
def test_part_2_widgets_are_checked_when_the_module_loads(
    problems: Problems, widget: str, expected: str
) -> None:
    found = problems(VIEW + f"    - {widget}\n")
    assert any(expected in line for line in found), found


VIEW = """\
module: v
name: Views
version: 1
kind: journal
settings:
  low_max: {type: number, default: 4}
entities:
  session:
    label: Session
    tab: Sessions
    key: [date]
    fields:
      date: {type: date, required: true}
      mood: {type: integer, min: 1, max: 10}
    derived:
      score: "mood * 2"
views:
  main:
"""


@pytest.mark.parametrize(
    ("widget", "expected"),
    [
        (
            "{widget: kpi, metric: session.nope}",
            "views.main[0].metric: 'session' has no field or derived value 'nope'",
        ),
        (
            "{widget: kpi, metric: sessions.mood}",
            "views.main[0].metric: 'sessions.mood' is not entity.field (entities: session)",
        ),
        (
            "{widget: kpi, metric: session.mood, agg: days_since_latest}",
            "views.main[0].agg: days_since_latest needs a date",
        ),
        (
            "{widget: line, series: [{metric: session.score}],"
            " bands: [{le: settings.high, label: X}]}",
            "views.main[0].bands[0].le: 'settings.high' is not a number or a setting",
        ),
        (
            "{widget: kpii, metric: session.mood}",
            "views.main[0]: Input tag 'kpii' found using 'widget' does not match any of the",
        ),
    ],
)
def test_a_view_is_checked_when_the_module_loads(
    problems: Problems, widget: str, expected: str
) -> None:
    found = problems(VIEW + f"    - {widget}\n")
    assert any(expected in line for line in found), found


def test_a_derived_value_and_a_setting_band_are_fine(load: LoadYaml) -> None:
    module = load(
        VIEW
        + "    - {widget: line, series: [{metric: session.score}],"
        + " bands: [{le: settings.low_max, label: LOW}, {else: OK}]}\n"
    )
    assert module.views is not None and len(module.views["main"]) == 1


# ---- The API ----


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(path))
    writer = RecordWriter(JOURNAL, XlsxBackend(path))
    for day, mood in [(28, 7), (29, 3)]:
        writer.add(
            "session",
            {"date": f"2026-10-{day}", "session_type": "Climbing", "wb_mood_pre": mood},
        )
    catalog = Catalog(AppConfig())
    cached = CachedRepository("journal", XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
    catalog.entries["journal"] = Entry("journal", JOURNAL, [], cached)
    yield TestClient(create_app(catalog=catalog))


def test_the_view_for_a_day(client: TestClient) -> None:
    body = client.get("/api/modules/journal/views/overview", params={"date": "2026-10-30"}).json()
    assert (body["module"], body["view"], body["date"]) == ("journal", "overview", "2026-10-30")
    assert [w["widget"] for w in body["widgets"]][:3] == ["kpi", "kpi", "status_board"]
    assert body["widgets"][1]["value"] == 1  # days since the 29th
    line = next(w for w in body["widgets"] if w["widget"] == "line")
    assert [p["date"] for p in line["points"]] == ["2026-10-28", "2026-10-29"]
    early = client.get("/api/modules/journal/views/overview", params={"date": "2026-10-28"})
    assert early.json()["widgets"][1]["value"] == 0


def test_an_unknown_view_or_module(client: TestClient) -> None:
    missing = client.get("/api/modules/journal/views/nope")
    assert (missing.status_code, missing.json()["detail"]) == (
        404,
        "module 'journal' has no view 'nope' (views: overview, load, progress)",
    )
    assert client.get("/api/modules/nope/views/overview").status_code == 404
