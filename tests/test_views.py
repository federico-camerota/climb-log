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


def test_widgets_not_drawn_yet_say_when_they_come() -> None:
    planned = of("planned", widgets())
    assert [(w["kind"], w["why"]) for w in planned] == [
        ("heatmap_calendar", "comes with #78"),
        ("side_by_side", "comes with #78"),
        ("text_feed", "comes with #78"),
        ("table", "comes with #78"),
    ]


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
        "module 'journal' has no view 'nope' (views: overview)",
    )
    assert client.get("/api/modules/nope/views/overview").status_code == 404
