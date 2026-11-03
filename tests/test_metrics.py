# SPDX-License-Identifier: GPL-3.0-or-later
"""The metric catalogue and metric queries (05-analytics §1, D-088, D-090). Fictional data only."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LoadYaml
from fastapi.testclient import TestClient

from climblog.analytics.metrics import Query, QueryError, Result, catalogue, run_query
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
FINGERS = load_module(ROOT / "modules" / "finger-strength.yaml")
OCT = dt.date(2026, 10, 1)
TODAY = dt.date(2026, 11, 3)


def day(n: int) -> dt.date:
    return OCT + dt.timedelta(days=n - 1)


def session(n: int, no: int = 1, **values: Value) -> dict[str, Value]:
    return {"date": day(n), "session_no": no, **values}


def rest(n: int, **values: Value) -> dict[str, Value]:
    return {"date": day(n), **values}


def run(
    *metrics: str,
    sessions: list[dict[str, Value]] | None = None,
    rests: list[dict[str, Value]] | None = None,
    fingers: list[dict[str, Value]] | None = None,
    **options: Any,
) -> Result:
    sources: dict[str, Any] = {
        "journal": (JOURNAL, {"session": sessions or [], "rest_day": rests or []})
    }
    if fingers is not None:
        sources["fingers"] = (FINGERS, {"session": fingers})
    return run_query(Query(list(metrics), **options), sources, TODAY)


def values(result: Result, i: int = 0) -> list[float | None]:
    return result.series[i].values


def labels(result: Result) -> list[str]:
    return [p.label for p in result.points]


# ---- The catalogue ----


def test_the_catalogue_has_the_numeric_fields_and_derived_values() -> None:
    found = catalogue("journal", JOURNAL)
    by_id = {m.id: m for m in found.metrics}
    sleep = by_id["journal.session.wb_sleep_hours"]
    assert (sleep.label, sleep.section, sleep.unit, sleep.scale) == (
        "Sleep hours",
        "Wellbeing · before",
        "h",
        (0, 14),
    )
    assert by_id["journal.session.wb_mood_pre"].direction == "higher_better"
    assert by_id["journal.session.ph_pre_fingers"].direction == "lower_better"
    assert by_id["journal.session.duration_min"].unit == "min"
    score = by_id["journal.session.wb_score"]
    assert (score.derived, score.label) == (True, "Wb score")
    assert "journal.rest_day.sleep_hours" in by_id
    # keys, dates, texts, choices and statuses are no metrics
    for name in ["session_no", "date", "venue", "session_type", "wb_status", "log_check"]:
        assert f"journal.session.{name}" not in by_id
    assert "journal.session.days_since_prev" in by_id  # a number of days


def test_choice_fields_are_the_filters() -> None:
    filters = {f.id: f for f in catalogue("journal", JOURNAL).filters}
    kind = filters["journal.session.session_type"]
    assert kind.choices[:2] == ["Climbing", "Hangboard"]
    assert kind.label == "Session type"
    assert "journal.rest_day.rest_type" in filters


def test_ordinal_choices_and_percent_fields(load: LoadYaml) -> None:
    module = load(
        """
        module: log
        name: Log
        version: 1
        kind: journal
        scales:
          freq: {type: ordinal, choices: [Rarely, Often], direction: neutral}
        entities:
          day:
            label: Day
            tab: Days
            date_field: date
            key: [date]
            fields:
              date: {type: date, required: true}
              how_often: {type: choice, scale: freq}
              share: {type: percent}
              note: {type: text}
        """
    )
    found = catalogue("log", module)
    assert [(f.id, f.choices) for f in found.filters] == [
        ("log.day.how_often", ["Rarely", "Often"])
    ]
    [share] = found.metrics
    assert (share.id, share.unit, share.scale) == ("log.day.share", "%", (0, 100))
    rows: list[dict[str, Value]] = [{"date": day(1), "share": 30}, {"date": day(1), "share": 50}]
    result = run_query(Query(["log.day.share"], agg="min"), {"log": (module, {"day": rows})}, TODAY)
    assert values(result) == [30]


# ---- One point per record ----


def test_one_point_per_record_keeps_a_days_second_session() -> None:
    result = run(
        "journal.session.wb_score",
        "journal.session.feel_score",
        sessions=[session(2, 2, wb_score=6), session(2, 1, wb_score=8, feel_score=7)],
        group="none",
    )
    assert [(p.label, p.key) for p in result.points] == [
        ("2026-10-02", {"session_no": 1}),
        ("2026-10-02", {"session_no": 2}),
    ]
    assert (values(result), values(result, 1)) == ([8, 6], [7, None])
    assert result.series[1].n == [1, 0]


def test_one_point_per_record_needs_one_entity_and_no_lag() -> None:
    with pytest.raises(QueryError, match="one entity"):
        run("journal.session.wb_score", "journal.rest_day.mood", group="none")
    with pytest.raises(QueryError, match="lag"):
        run("journal.session.wb_score", group="none", lag=1)


# ---- By day, week and month ----


def test_a_day_with_two_sessions_takes_the_aggregate() -> None:
    sessions = [session(2, 1, wb_score=8), session(2, 2, wb_score=5), session(4, wb_score=7)]
    assert values(run("journal.session.wb_score", sessions=sessions)) == [6.5, 7]
    result = run("journal.session.wb_score", sessions=sessions, agg="latest")
    assert values(result) == [5, 7]  # the day's second session
    assert values(run("journal.session.wb_score", sessions=sessions, agg="max")) == [8, 7]
    assert run("journal.session.wb_score", sessions=sessions).series[0].n == [2, 1]


def test_modules_and_entities_are_joined_by_day() -> None:
    result = run(
        "journal.session.wb_sleep_hours",
        "journal.rest_day.sleep_hours",
        "fingers.session.session_rpe",
        sessions=[session(1, wb_sleep_hours=7), session(3, wb_sleep_hours=6.5)],
        rests=[rest(2, sleep_hours=9)],
        fingers=[{"date": day(3), "session_type": "Max hangs", "session_rpe": 8}],
    )
    assert labels(result) == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert [s.values for s in result.series] == [
        [7, None, 6.5],
        [None, 9, None],
        [None, None, 8],
    ]


def test_weeks_start_on_monday_and_have_no_gaps() -> None:
    # 2026-10-01 is a Thursday; nothing is logged in the week of the 12th
    sessions = [
        session(1, session_load=100),
        session(5, session_load=50),
        session(20, session_load=80),
    ]
    result = run(
        "journal.session.session_load", sessions=sessions, group="week", agg="sum", end=day(25)
    )
    assert labels(result) == ["2026-W40", "2026-W41", "2026-W42", "2026-W43"]
    assert [p.start for p in result.points] == [day(-2), day(5), day(12), day(19)]
    assert result.points[0].end == day(4)
    assert values(result) == [100, 50, None, 80]
    counted = run(
        "journal.session.session_load", sessions=sessions, group="week", agg="count", end=day(25)
    )
    assert values(counted) == [1, 1, 0, 1]


def test_months_run_to_the_end_day() -> None:
    sessions = [session(1, wb_score=6), session(10, wb_score=8)]
    result = run(
        "journal.session.wb_score", sessions=sessions, group="month", end=dt.date(2026, 12, 2)
    )
    assert labels(result) == ["2026-10", "2026-11", "2026-12"]
    assert values(result) == [7, None, None]
    assert result.points[0].end == dt.date(2026, 10, 31)


def test_start_and_end_bound_the_records() -> None:
    sessions = [session(d, wb_score=d) for d in (1, 5, 9)]
    result = run("journal.session.wb_score", sessions=sessions, start=day(2), end=day(8))
    assert (labels(result), values(result)) == (["2026-10-05"], [5])
    assert values(run("journal.session.wb_score", sessions=sessions, end=day(4))) == [1]
    after_today = [session(40, wb_score=3)]  # 2026-11-09, after TODAY
    assert run("journal.session.wb_score", sessions=after_today).points == []
    with pytest.raises(QueryError, match="after end"):
        run("journal.session.wb_score", start=day(9), end=day(2))


def test_a_rolling_mean_over_the_points() -> None:
    sessions = [session(d, wb_score=s) for d, s in [(1, 4), (2, 6), (3, None), (4, 8)]]
    result = run("journal.session.wb_score", sessions=sessions, rolling=2)
    assert result.series[0].rolling == [4, 5, 6, 8]
    with pytest.raises(QueryError, match="rolling"):
        run("journal.session.wb_score", rolling=1)


def test_a_lag_reads_the_later_metrics_k_days_later() -> None:
    # how did I feel the day after a session? the rest day's mood of day d + 1 counts for d
    result = run(
        "journal.session.feel_score",
        "journal.rest_day.mood",
        sessions=[session(1, feel_score=8), session(3, feel_score=5)],
        rests=[rest(2, mood=7), rest(4, mood=4)],
        lag=1,
    )
    assert labels(result) == ["2026-10-01", "2026-10-03"]
    assert [s.values for s in result.series] == [[8, 5], [7, 4]]
    assert result.lag == 1


# ---- Filters ----


def test_a_filter_keeps_its_entitys_records_with_those_values() -> None:
    sessions = [
        session(1, session_type="Climbing", wb_score=8),
        session(2, session_type="Hangboard", wb_score=4),
        session(3, session_type="Endurance / ARC", wb_score=6),
    ]
    kept = {"journal.session.session_type": ["Climbing", "Endurance / ARC"]}
    result = run(
        "journal.session.wb_score",
        "journal.rest_day.mood",
        sessions=sessions,
        rests=[rest(2, mood=5)],
        filters=kept,
    )
    assert labels(result) == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert values(result) == [8, None, 6]  # the hangboard day is the rest day's only
    assert values(result, 1) == [None, 5, None]  # the filter is the sessions'


def test_bad_filters_are_errors() -> None:
    with pytest.raises(QueryError, match="unknown filter"):
        run("journal.session.wb_score", filters={"journal.session.venue": ["x"]})
    with pytest.raises(QueryError, match="no choice 'Bouldering'"):
        run("journal.session.wb_score", filters={"journal.session.session_type": ["Bouldering"]})
    with pytest.raises(QueryError, match="none of the metrics"):
        run("journal.session.wb_score", filters={"journal.rest_day.rest_type": ["Full rest"]})


def test_unknown_or_too_many_metrics_are_errors() -> None:
    with pytest.raises(QueryError, match=r"unknown metric\(s\): journal.session.wb_status"):
        run("journal.session.wb_status")
    with pytest.raises(QueryError, match="at least one"):
        run()
    with pytest.raises(QueryError, match="at most 12"):
        run(*["journal.session.wb_score"] * 13)


# ---- The API ----


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(path))
    writer = RecordWriter(JOURNAL, XlsxBackend(path))
    for d, kind, sleep in [(5, "Climbing", 7), (6, "Hangboard", 6), (14, "Climbing", 8)]:
        writer.add(
            "session",
            {"date": f"2026-10-{d:02d}", "session_type": kind, "wb_sleep_hours": sleep},
        )
    catalog = Catalog(AppConfig())
    cached = CachedRepository("journal", XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
    catalog.entries["journal"] = Entry("journal", JOURNAL, [], cached)
    catalog.entries["broken"] = Entry("broken", None, ["a problem"])
    gone = CachedRepository("gone", XlsxBackend(tmp_path / "gone.xlsx"), Snapshots(tmp_path / "s2"))
    catalog.entries["gone"] = Entry("gone", JOURNAL, [], gone)  # no workbook, no snapshot
    yield TestClient(create_app(catalog=catalog))


def test_the_catalogue_api(client: TestClient) -> None:
    body = client.get("/api/metrics").json()
    sleep = next(m for m in body["metrics"] if m["id"] == "journal.session.wb_sleep_hours")
    assert sleep == {
        "id": "journal.session.wb_sleep_hours",
        "module": "journal",
        "entity": "session",
        "field": "wb_sleep_hours",
        "label": "Sleep hours",
        "section": "Wellbeing · before",
        "derived": False,
        "unit": "h",
        "scale": [0.0, 14.0],
        "direction": None,
    }
    assert {m["module"] for m in body["metrics"]} == {"journal", "gone"}  # not the broken one
    assert any(f["id"] == "journal.session.session_type" for f in body["filters"])


def test_the_query_api(client: TestClient) -> None:
    params: dict[str, Any] = {
        "metric": "journal.session.wb_sleep_hours",
        "group": "week",
        "end": "2026-10-18",
        "filter": "journal.session.session_type=Climbing",
    }
    body = client.get("/api/metrics/query", params=params).json()
    assert [p["label"] for p in body["points"]] == ["2026-W41", "2026-W42"]
    assert body["series"] == [
        {
            "metric": "journal.session.wb_sleep_hours",
            "values": [7.0, 8.0],
            "n": [1, 1],
            "rolling": None,
            "bands": None,  # no dashboard line draws sleep hours with bands
        }
    ]
    assert body["sources"][0]["module"] == "journal"
    # the class scores: the bands the dashboard's scores line draws, from the settings
    scores = client.get("/api/metrics/query", params={"metric": "journal.session.wb_score"})
    assert scores.json()["series"][0]["bands"] == [
        {"label": "LOW", "from": None, "to": 4.0},
        {"label": "WATCH", "from": 4.0, "to": 6.0},
        {"label": "GOOD", "from": 6.0, "to": None},
    ]


def test_the_query_api_says_what_is_wrong(client: TestClient) -> None:
    bad = client.get("/api/metrics/query", params={"metric": "journal.session.nope"})
    assert (bad.status_code, bad.json()["detail"]) == (
        400,
        "unknown metric(s): journal.session.nope",
    )
    no_value = client.get(
        "/api/metrics/query", params={"metric": "journal.session.wb_score", "filter": "x"}
    )
    assert no_value.status_code == 400
    assert client.get("/api/metrics/query").status_code == 422  # no metric
    other = client.get("/api/metrics/query", params={"metric": "broken.session.x"})
    assert other.json()["detail"] == "unknown metric(s): broken.session.x"
    gone = client.get("/api/metrics/query", params={"metric": "gone.session.wb_score"})
    assert gone.status_code == 503


def test_values_before_a_fields_since_are_left_out() -> None:
    # elbows are tracked from 2026-10-20 (`since:` in journal.yaml): a value typed before counts
    # for nothing, as in the formulas and the progress view (03 §2.2)
    sessions = [
        session(5, ph_pre_elbows=4, ph_pre_fingers=2),
        session(25, ph_pre_elbows=2, ph_pre_fingers=3),
    ]
    both = run(
        "journal.session.ph_pre_elbows",
        "journal.session.ph_pre_fingers",
        sessions=sessions,
        group="none",
    )
    assert values(both) == [None, 2] and values(both, 1) == [2, 3]  # the record stays
    weekly = run("journal.session.ph_pre_elbows", sessions=sessions, group="month")
    assert (values(weekly), weekly.series[0].n) == ([2, None], [1, 0])  # October, November
