# SPDX-License-Identifier: GPL-3.0-or-later
"""Grade charts (#101, D-094): French and gym never converted, gym grades per venue, the
pyramid of hardest grades tried, by setting and venue. Fictional data only."""

import datetime as dt
from pathlib import Path
from typing import Any

from conftest import LoadYaml, Problems

from climblog.analytics import compute_view
from climblog.analytics.grade_charts import french_label
from climblog.expr import Value
from climblog.modules import load_module

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
GRADES = next(w for w in (JOURNAL.views or {})["progress"] if w.widget == "grades")
OCT = dt.date(2026, 10, 1)


def day(n: int) -> dt.date:
    return OCT + dt.timedelta(days=n - 1)


def session(
    n: int, grade: str | None, venue: str = "[ESEMPIO] Falesia", setting: str = "Outdoor"
) -> dict[str, Value]:
    return {
        "date": day(n),
        "session_no": 1,
        "hardest_grade": grade,
        "venue": venue,
        "setting": setting,
    }


def charts(*sessions: dict[str, Value], on: dt.date = dt.date(2026, 11, 30)) -> dict[str, Any]:
    [found] = compute_view(JOURNAL, [GRADES], {"session": list(sessions)}, {}, on)
    return found


def test_grade_labels() -> None:
    assert [french_label(i) for i in (30, 31, 32, 36, 32.5)] == ["6a", "6a+", "6b", "7a", "6b"]


def test_french_is_one_series_and_gym_one_per_venue() -> None:
    found = charts(
        session(1, "6b+"),
        session(2, "5", "[ESEMPIO] Palestra Nord", "Indoor"),
        session(3, "7", "[ESEMPIO] Palestra Sud", "Indoor"),
        session(4, "6c", "[ESEMPIO] Palestra Nord", "Indoor"),  # a French grade in a gym
        session(5, "6", "[ESEMPIO] Palestra Nord", "Indoor"),
    )
    assert [s["label"] for s in found["series"]] == [
        "French",
        "Gym · [ESEMPIO] Palestra Nord",
        "Gym · [ESEMPIO] Palestra Sud",
    ]
    french, nord, _ = found["series"]
    assert [(p["grade"], p["index"]) for p in french["points"]] == [("6b+", 33), ("6c", 34)]
    assert [p["index"] for p in nord["points"]] == [5, 6]
    assert french["points"][1]["setting"] == "Indoor"
    assert [t["label"] for t in found["french_ticks"]] == ["6b+", "6c"]


def test_the_pyramid_counts_sessions_by_hardest_grade_per_month() -> None:
    found = charts(session(1, "6a"), session(2, "6b"), session(3, "6a"), session(40, "6b"))
    pyramid = found["pyramid"]
    assert pyramid["periods"] == ["2026-10", "2026-11"]
    [row] = pyramid["rows"]
    assert (row["label"], row["grades"], row["counts"]) == (
        "French",
        ["6a", "6b"],
        [[2, 0], [1, 1]],
    )
    assert found["last"] == 6


def test_by_setting_and_venue() -> None:
    found = charts(
        session(1, "6a"),
        session(2, "6c"),
        session(3, "6b"),
        session(4, "5", "[ESEMPIO] Palestra Nord", "Indoor"),
        session(5, "6", "[ESEMPIO] Palestra Nord", "Indoor"),
    )
    assert found["by_setting"] == [
        {"setting": "Outdoor", "system": "french", "sessions": 3, "hardest": "6c", "median": "6b"},
        {"setting": "Indoor", "system": "gym", "sessions": 2, "hardest": "6", "median": "5"},
    ]
    assert [r["venue"] for r in found["by_venue"]] == [
        "[ESEMPIO] Falesia",
        "[ESEMPIO] Palestra Nord",
    ]


def test_a_slash_grade_keeps_its_text() -> None:
    found = charts(session(1, "7a/7a+"), session(2, "7a"), session(3, "6c+/7a"))
    [row] = found["pyramid"]["rows"]
    assert row["grades"] == ["6c+/7a", "7a", "7a/7a+"]
    assert found["by_setting"][0]["hardest"] == "7a/7a+"


def test_bad_values_are_counted_and_later_ones_left_out() -> None:
    found = charts(
        session(1, "hard"), session(2, None), session(3, "6a"), session(60, "7a"), on=day(10)
    )
    assert found["unparsed"] == 1
    assert [p["grade"] for p in found["series"][0]["points"]] == ["6a"]


def test_nothing_logged() -> None:
    found = charts()
    assert (found["series"], found["french_ticks"], found["pyramid"]) == (
        [],
        [],
        {"periods": [], "rows": []},
    )


def test_weekly_pyramid_without_venue_or_setting(load: LoadYaml) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "      venue: session.venue\n      setting: session.setting\n      group: month\n",
        "      group: week\n",
    )
    module = load(text)
    widget = next(w for w in (module.views or {})["progress"] if w.widget == "grades")
    rows = [session(1, "5"), session(9, "6a")]
    [found] = compute_view(module, [widget], {"session": rows}, {}, day(20))
    assert [s["label"] for s in found["series"]] == ["French", "Gym"]
    assert found["pyramid"]["periods"] == ["2026-W40", "2026-W41"]
    assert (found["by_setting"], found["by_venue"]) == ([], [])


def test_the_field_must_be_a_grade(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    bad = text.replace("      grade: session.hardest_grade\n", "      grade: session.venue\n")
    assert any("'session.venue' is not a grade field" in p for p in problems(bad))
    bad = text.replace(
        "      venue: session.venue\n      setting: session.setting\n      group: month",
        "      venue: rest_day.note\n      group: month",
    )
    assert any("'rest_day.note' is not a field of 'session'" in p for p in problems(bad))
