# SPDX-License-Identifier: GPL-3.0-or-later
"""Widget library v1 (#98, D-091): bars, weekbars, stacked, box_by, scatter, and the line's
split_by and x. Fictional data only."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from conftest import Problems
from pydantic import TypeAdapter

from climblog.analytics import compute_view
from climblog.expr import Value
from climblog.modules import load_module
from climblog.modules.schema import Widget

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
FINGERS = load_module(ROOT / "modules" / "finger-strength.yaml")
OCT = dt.date(2026, 10, 1)  # a Thursday
END = dt.date(2026, 10, 31)
WIDGET: TypeAdapter[Widget] = TypeAdapter(Widget)


def day(n: int) -> dt.date:
    return OCT + dt.timedelta(days=n - 1)


def session(n: int, no: int = 1, **values: Value) -> dict[str, Value]:
    return {"date": day(n), "session_no": no, **values}


def one(
    spec: dict[str, Any],
    sessions: list[dict[str, Value]],
    rests: list[dict[str, Value]] | None = None,
    on: dt.date = END,
) -> dict[str, Any]:
    tables = {"session": sessions, "rest_day": rests or []}
    [found] = compute_view(JOURNAL, [WIDGET.validate_python(spec)], tables, {}, on)
    return found


# ---- bars ----


def test_bars_per_week_with_n() -> None:
    sessions = [
        session(1, session_load=100),
        session(2, session_load=50),
        session(9, session_load=80),
    ]
    found = one({"widget": "bars", "metric": "session.session_load", "agg": "sum"}, sessions)
    assert found["categories"] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"]
    assert found["values"] == [150, 80, None, None, None]
    assert found["n"] == [2, 1, 0, 0, 0]
    assert (found["metric"], found["agg"], found["last"]) == ("Session load", "sum", 12)


def test_bars_by_a_field_follow_its_choices() -> None:
    sessions = [
        session(1, session_type="Hangboard", feel_score=6),
        session(2, session_type="Climbing", feel_score=8),
        session(3, session_type="Climbing", feel_score=7),
        session(4, feel_score=9),  # no type: left out
    ]
    spec = {"widget": "bars", "metric": "session.feel_score", "by": "session.session_type"}
    found = one(spec, sessions)
    assert (found["categories"], found["values"], found["n"]) == (
        ["Climbing", "Hangboard"],
        [7.5, 6],
        [2, 1],
    )


def test_bars_by_weekday_run_monday_to_sunday() -> None:
    sessions = [session(4, weekday="Sun", feel_score=5), session(5, weekday="Mon", feel_score=8)]
    spec = {"widget": "bars", "metric": "session.feel_score", "by": "session.weekday", "agg": "max"}
    assert one(spec, sessions)["categories"] == ["Mon", "Sun"]


# ---- weekbars ----


def test_weekbars_count_by_value_in_the_levels_order() -> None:
    sessions = [
        session(1, overall_status="LOW"),
        session(2, overall_status="GOOD"),
        session(2, 2, overall_status="GOOD"),
        session(12, overall_status="WATCH"),
    ]
    found = one({"widget": "weekbars", "metric": "session.overall_status"}, sessions)
    assert found["weeks"] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"]
    assert found["starts"][0] == "2026-09-28"
    assert found["stacks"] == [
        {"label": "GOOD", "values": [2, 0, 0, 0, 0]},
        {"label": "WATCH", "values": [0, 0, 1, 0, 0]},
        {"label": "LOW", "values": [1, 0, 0, 0, 0]},
    ]


def test_weekbars_sum_split_by_a_field() -> None:
    sessions = [
        session(1, session_type="Climbing", duration_min=90),
        session(2, session_type="Hangboard", duration_min=30),
        session(6, session_type="Climbing", duration_min=60),
    ]
    spec = {
        "widget": "weekbars",
        "metric": "session.duration_min",
        "agg": "sum",
        "split_by": "session.session_type",
        "weeks": 4,
    }
    found = one(spec, sessions, on=day(12))
    assert found["stacks"] == [
        {"label": "Climbing", "values": [90, 60, 0]},
        {"label": "Hangboard", "values": [30, 0, 0]},
    ]
    assert found["shown"] == 4
    assert one({**spec, "split_by": None}, sessions, on=day(12))["stacks"] == [
        {"label": "", "values": [120, 60, 0]}
    ]


def test_weekbars_mean_leaves_a_week_without_records_empty() -> None:
    sessions = [session(1, feel_score=6), session(2, feel_score=7), session(12, feel_score=8)]
    spec = {"widget": "weekbars", "metric": "session.feel_score", "agg": "mean"}
    assert one(spec, sessions)["stacks"] == [
        {"label": "", "values": [6.5, None, 8, None, None]}  # no bar, not a mean of 0
    ]
    counted = one({**spec, "agg": "count"}, sessions)["stacks"]
    assert counted == [{"label": "", "values": [2, 0, 1, 0, 0]}]


def test_weekbars_without_records_and_program_weeks() -> None:
    assert one({"widget": "weekbars", "metric": "session.overall_status"}, [])["weeks"] == []
    spec = {"widget": "weekbars", "metric": "session.overall_status", "group": "program_week"}
    assert one(spec, [])["widget"] == "planned"


# ---- stacked ----


def test_stacked_metrics_of_two_entities_per_month() -> None:
    spec = {
        "widget": "stacked",
        "series": [
            {"metric": "session.duration_min", "label": "Climbing"},
            {"metric": "rest_day.sleep_hours"},
        ],
        "group": "month",
    }
    found = one(spec, [session(1, duration_min=90)], [{"date": day(2), "sleep_hours": 8}])
    assert found["categories"] == ["2026-10"]
    assert [(s["label"], s["values"]) for s in found["series"]] == [
        ("Climbing", [90]),
        ("Sleep hours", [8]),
    ]


# ---- box_by ----


def test_box_by_gives_tukey_boxes_with_outliers() -> None:
    scores = [5, 6, 6, 7, 7, 7, 8, 1]  # 1 is far below the others
    sessions = [session(i + 1, session_type="Climbing", feel_score=s) for i, s in enumerate(scores)]
    sessions.append(session(20, session_type="Hangboard", feel_score=4))
    spec = {"widget": "box_by", "metric": "session.feel_score", "by": "session.session_type"}
    found = one(spec, sessions)
    climbing, hangboard = found["boxes"]
    assert climbing == {
        "label": "Climbing",
        "n": 8,
        "low": 5,
        "q1": 5.75,
        "median": 6.5,
        "q3": 7,
        "high": 8,
        "outliers": [1],
    }
    assert (hangboard["n"], hangboard["median"], hangboard["outliers"]) == (1, 4, [])
    assert (found["metric"], found["by"]) == ("Feel score", "Session type")


def test_box_by_order_and_time_bins() -> None:
    sessions = [
        session(1, session_type="Climbing", feel_score=5),
        session(2, session_type="Hangboard", feel_score=6),
    ]
    spec = {"widget": "box_by", "metric": "session.feel_score", "by": "session.session_type"}
    found = one({**spec, "order": ["Hangboard"]}, sessions)
    assert [b["label"] for b in found["boxes"]] == ["Hangboard", "Climbing"]
    assert one({**spec, "bins": ["morning"]}, sessions)["widget"] == "planned"


# ---- scatter ----


def test_scatter_per_record_with_a_trend_line_and_colours() -> None:
    sessions = [
        session(1, wb_sleep_hours=6, feel_score=5, setting="Indoor"),
        session(2, wb_sleep_hours=7, feel_score=7, setting="Outdoor"),
        session(3, wb_sleep_hours=8, feel_score=9, setting="Indoor"),
        session(4, wb_sleep_hours=None, feel_score=3),  # no pair
    ]
    spec = {
        "widget": "scatter",
        "x": "session.wb_sleep_hours",
        "y": "session.feel_score",
        "color": "session.setting",
    }
    found = one(spec, sessions)
    assert found["n"] == 3
    assert found["points"][1] == {"x": 7, "y": 7, "date": "2026-10-02", "group": "Outdoor"}
    assert found["trend"] == {"slope": 2, "intercept": -7, "from": 6, "to": 8}
    assert (found["x_label"], found["y_label"]) == ("Sleep hours", "Feel score")


def test_scatter_across_entities_by_day_with_a_lag() -> None:
    sessions = [session(1, feel_score=8), session(3, feel_score=5)]
    rests: list[dict[str, Value]] = [{"date": day(2), "mood": 7}, {"date": day(4), "mood": 4}]
    spec = {"widget": "scatter", "x": "session.feel_score", "y": "rest_day.mood", "lag": 1}
    found = one(spec, sessions, rests)
    assert [(p["x"], p["y"], p["date"]) for p in found["points"]] == [
        (8, 7, "2026-10-01"),
        (5, 4, "2026-10-03"),
    ]
    assert found["trend"] is None  # fewer than 3 points


def test_scatter_trend_needs_spread_in_x() -> None:
    sessions = [session(i, wb_sleep_hours=7, feel_score=i) for i in (1, 2, 3)]
    spec = {"widget": "scatter", "x": "session.wb_sleep_hours", "y": "session.feel_score"}
    assert one(spec, sessions)["trend"] is None


# ---- line: split_by and x ----


def test_a_line_per_value_of_a_field() -> None:
    sessions = [
        session(1, setting="Indoor", feel_score=6),
        session(2, setting="Outdoor", feel_score=8),
        session(3, setting="Indoor", feel_score=7),
    ]
    spec = {
        "widget": "line",
        "series": [{"metric": "session.feel_score", "label": "Feel"}],
        "split_by": ["session.setting"],
    }
    found = one(spec, sessions)
    assert [(s["label"], s["values"]) for s in found["series"]] == [
        ("Feel · Indoor", [6, None, 7]),
        ("Feel · Outdoor", [None, 8, None]),
    ]
    assert len(found["points"]) == 3


def test_a_line_over_another_x() -> None:
    sessions = [
        session(1, days_since_prev=None, feel_score=6),
        session(2, days_since_prev=1, feel_score=5),
        session(4, days_since_prev=2, feel_score=8),
        session(5, days_since_prev=1, feel_score=6),
    ]
    spec = {
        "widget": "line",
        "series": [{"metric": "session.feel_score"}],
        "x": "session.days_since_prev",
    }
    found = one(spec, sessions)
    assert (found["x"], found["x_label"], found["points"]) == ([1, 2], "Days since prev", [])
    assert found["series"][0]["values"] == [5.5, 8]
    found = one(spec, [*sessions, session(6, days_since_prev=1, feel_score=6)])
    assert found["series"][0]["values"] == [5.666667, 8]  # as the bars: not to one decimal


def test_line_legends_are_the_fields_labels() -> None:
    spec = {"widget": "line", "series": [{"metric": "session.wb_sleep_hours"}]}
    found = one(spec, [session(1, wb_sleep_hours=7, setting="Indoor")])
    assert found["series"][0]["label"] == "Sleep hours"
    found = one(
        {**spec, "split_by": ["session.setting"]}, [session(1, wb_sleep_hours=7, setting="Indoor")]
    )
    assert found["series"][0]["label"] == "Sleep hours · Indoor"


def test_a_split_by_another_entity_is_planned() -> None:
    widget = next(
        w
        for w in (FINGERS.views or {})["overview"]
        if getattr(w, "split_by", None) and w.widget == "line"
    )
    [found] = compute_view(FINGERS, [widget], {"session": []}, {}, END)
    assert found["widget"] == "planned"


# ---- checks at load ----


def test_fields_must_be_of_the_metrics_entity(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "views:\n  overview:\n",
        "views:\n  overview:\n"
        "    - {widget: bars, metric: session.feel_score, by: rest_day.rest_type}\n"
        "    - {widget: weekbars, metric: session.nope}\n"
        "    - {widget: scatter, x: session.feel_score, y: session.wb_score,\n"
        "       color: rest_day.mood}\n"
        "    - {widget: line, series: [{metric: session.feel_score}], x: rest_day.mood}\n"
        "    - {widget: weekbars, metric: session.duration_min, agg: sum,\n"
        "       split_by: rest_day.rest_type}\n",
    )
    found = problems(text)
    assert any(
        "views.overview[0].by: 'rest_day.rest_type' is not a field of 'session'" in p for p in found
    )
    assert any(
        "views.overview[1].metric: 'session' has no field or derived value 'nope'" in p
        for p in found
    )
    assert any("views.overview[2].color" in p for p in found)
    assert any("views.overview[3].x" in p for p in found)
    assert any("views.overview[4].split_by" in p for p in found)


def test_charts_plot_numbers_only(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "views:\n  overview:\n",
        "views:\n  overview:\n"
        "    - {widget: bars, metric: session.venue}\n"
        "    - {widget: box_by, metric: session.notes, by: session.weekday}\n"
        "    - {widget: stacked,\n"
        "       series: [{metric: session.duration_min}, {metric: session.setting}]}\n"
        "    - {widget: scatter, x: session.hardest_grade, y: session.feel_score}\n"
        "    - {widget: line, series: [{metric: session.overall_status}]}\n"
        "    - {widget: weekbars, metric: session.venue, agg: mean}\n"
        "    - {widget: weekbars, metric: session.venue, agg: count}\n"
        "    - {widget: bars, metric: session.wb_score}\n",
    )
    found = [p for p in problems(text) if "is not a number" in p]
    at = [p.partition(": '")[0].rpartition(" ")[2] for p in found]
    assert at == [
        "views.overview[0].metric",
        "views.overview[1].metric",
        "views.overview[2].series[1].metric",
        "views.overview[3].x",
        "views.overview[4].series[0].metric",
        "views.overview[5].metric",
    ]  # counting any value (6) and a derived number (7) are fine


def test_count_by_value_cannot_split(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "views:\n  overview:\n",
        "views:\n  overview:\n"
        "    - {widget: weekbars, metric: session.overall_status, split_by: session.setting}\n",
    )
    assert any("drop split_by" in p for p in problems(text))


@pytest.mark.parametrize("kind", ["bars", "weekbars", "stacked", "box_by", "scatter"])
def test_no_widget_of_v1_is_still_planned(kind: str) -> None:
    specs: dict[str, dict[str, Any]] = {
        "bars": {"metric": "session.feel_score"},
        "weekbars": {"metric": "session.overall_status"},
        "stacked": {"series": [{"metric": "session.duration_min"}]},
        "box_by": {"metric": "session.feel_score", "by": "session.session_type"},
        "scatter": {"x": "session.feel_score", "y": "session.wb_score"},
    }
    assert one({"widget": kind, **specs[kind]}, [session(1, feel_score=5)])["widget"] == kind
