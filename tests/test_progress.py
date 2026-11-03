# SPDX-License-Identifier: GPL-3.0-or-later
"""Before/after changes and soreness by body part and week (#100, D-093). Fictional data."""

import datetime as dt
from pathlib import Path
from typing import Any

from conftest import LoadYaml, Problems

from climblog.analytics import compute_view
from climblog.expr import Value
from climblog.modules import load_module

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
PROGRESS = (JOURNAL.views or {})["progress"]
MON = dt.date(2026, 10, 5)


def day(n: int) -> dt.date:
    return MON + dt.timedelta(days=n)


def session(n: int, **values: Value) -> dict[str, Value]:
    return {"date": day(n), "session_no": 1, **values}


def widgets(
    sessions: list[dict[str, Value]], rests: list[dict[str, Value]] | None = None, on: int = 13
) -> tuple[dict[str, Any], dict[str, Any]]:
    tables = {"session": sessions, "rest_day": rests or []}
    found = compute_view(JOURNAL, PROGRESS, tables, {}, day(on))
    return found[0], found[1]


def test_pairs_give_means_before_after_and_change_with_n() -> None:
    sessions = [
        session(
            0,
            session_type="Climbing",
            wb_mood_pre=6,
            wb_mood_post=8,
            ph_pre_fingers=2,
            ph_post_fingers=5,
        ),
        session(
            1,
            session_type="Hangboard",
            wb_mood_pre=7,
            wb_mood_post=6,
            ph_pre_fingers=1,
            ph_post_fingers=6,
        ),
        session(2, session_type="Climbing", wb_mood_pre=5, wb_mood_post=None),  # no pair
    ]
    deltas, _ = widgets(sessions)
    assert deltas["groups"] == ["Climbing", "Hangboard"]
    mood, fingers = deltas["pairs"][0], deltas["pairs"][1]
    assert mood == {
        "label": "Mood",
        "lower_better": False,
        "all": {"n": 2, "pre": 6.5, "post": 7, "change": 0.5},
        "groups": [
            {"n": 1, "pre": 6, "post": 8, "change": 2},
            {"n": 1, "pre": 7, "post": 6, "change": -1},
        ],
    }
    assert (fingers["label"], fingers["lower_better"], fingers["all"]["change"]) == (
        "Fingers",
        True,
        4,
    )
    labels = [p["label"] for p in deltas["pairs"]]
    assert labels == [
        "Mood",
        "Fingers",
        "Forearms",
        "Elbows",
        "Shoulders",
        "Neck / traps",
        "Wrists",
        "Skin",
    ]
    skin = deltas["pairs"][-1]
    assert skin["all"] == {"n": 0, "pre": None, "post": None, "change": None}


def test_soreness_by_body_part_and_week() -> None:
    sessions = [
        session(0, ph_pre_fingers=2, ph_post_fingers=4),
        session(2, ph_pre_fingers=4, ph_post_fingers=6),
        session(9, ph_pre_fingers=3),
    ]
    rests: list[dict[str, Value]] = [{"date": day(8), "body_fingers": 5}]
    _, heat = widgets(sessions, rests)
    assert heat["weeks"] == ["2026-W41", "2026-W42"]
    assert heat["parts"][:2] == ["Fingers", "Forearms"]
    before, after, rest = heat["sources"]
    assert (before["label"], before["values"][0], before["n"][0]) == (
        "Before sessions",
        [3, 3],
        [2, 1],
    )
    assert after["values"][0] == [5, None]
    assert rest["values"][0] == [None, 5]
    assert before["values"][1] == [None, None]  # no forearms logged
    assert (heat["scale"], heat["lower_better"], heat["shown"]) == ((1, 10), True, 12)


def test_nothing_logged_and_later_records() -> None:
    deltas, heat = widgets([session(20, wb_mood_pre=5, wb_mood_post=7)], on=3)
    assert deltas["pairs"][0]["all"]["n"] == 0  # after the day
    assert heat["weeks"] == []


def test_without_by_there_are_no_groups(load: LoadYaml) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    module = load(text.replace("      by: session.session_type\n", "", 1))
    widget = (module.views or {})["progress"][0]
    [found] = compute_view(
        module, [widget], {"session": [session(0, wb_mood_pre=4, wb_mood_post=6)]}, {}, day(1)
    )
    assert (found["groups"], found["pairs"][0]["groups"]) == ([], [])


def test_pairs_and_templates_are_checked(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    bad = text.replace("post: session.wb_mood_post}", "post: rest_day.mood}")
    found = problems(bad)
    assert any("'rest_day.mood' is not a field of 'session'" in p for p in found)
    bad = text.replace("template_pairs: [{template: soreness,", "template_pairs: [{template: sore,")
    assert any("no template 'sore'" in p for p in problems(bad))
    bad = text.replace(
        "{label: Rest days, fields: rest_day.body_}", "{label: Rest days, fields: rest_day.b_}"
    )
    assert any("'rest_day' has no field b_fingers" in p for p in problems(bad))
    bad = text.replace(
        "      by: session.session_type\n    - widget: body_heatmap",
        "      by: rest_day.rest_type\n    - widget: body_heatmap",
    )
    assert any("is not a field of the pairs' entity" in p for p in problems(bad))
    bad = text.replace("post: session.ph_post_}]", "post: rest_day.body_}]")
    assert any("the pairs must be of one entity" in p for p in problems(bad))
    bad = text.replace(
        "{label: Rest days, fields: rest_day.body_}", "{label: Rest days, fields: rest.body_}"
    )
    assert any("no entity 'rest'" in p for p in problems(bad))
    bad = text.replace(
        "      pairs: [{label: Mood, pre: session.wb_mood_pre, post: session.wb_mood_post}]\n"
        "      template_pairs: [{template: soreness, pre: session.ph_pre_, "
        "post: session.ph_post_}]\n",
        "",
    )
    assert any("give pairs or template_pairs" in p for p in problems(bad))


def test_a_pair_of_plain_numbers_has_no_direction(load: LoadYaml) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    module = load(
        text.replace(
            "pairs: [{label: Mood, pre: session.wb_mood_pre, post: session.wb_mood_post}]",
            "pairs: [{label: Sleep, pre: session.wb_sleep_hours, post: session.duration_min}]",
        )
    )
    widget = (module.views or {})["progress"][0]
    [found] = compute_view(module, [widget], {"session": []}, {}, day(1))
    assert found["pairs"][0]["lower_better"] is None


def test_values_before_a_fields_since_are_left_out() -> None:
    # elbows are tracked from 2026-10-20 (`since:` in journal.yaml): day(15)
    sessions = [
        session(0, ph_pre_elbows=2, ph_post_elbows=6),  # typed before it was tracked
        session(16, ph_pre_elbows=3, ph_post_elbows=4),
    ]
    deltas, heat = widgets(sessions, on=20)
    elbows = next(p for p in deltas["pairs"] if p["label"] == "Elbows")
    assert elbows["all"] == {"n": 1, "pre": 3, "post": 4, "change": 1}
    row = heat["parts"].index("Elbows")
    assert heat["sources"][0]["values"][row] == [None, None, 3]  # weeks of 10-05, 10-12, 10-19


def test_a_retired_body_part_shows_while_it_has_values(load: LoadYaml) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    module = load(
        text.replace(
            "    skin:       {type: scale, scale: s10_down, tags: [soreness]}",
            "    skin:       {type: scale, scale: s10_down, tags: [soreness], retired: true}",
        )
    )
    views = (module.views or {})["progress"]

    def labels(sessions: list[dict[str, Value]]) -> tuple[list[str], list[str]]:
        deltas, heat = compute_view(module, views, {"session": sessions}, {}, day(6))
        return [p["label"] for p in deltas["pairs"]], heat["parts"]

    pairs, parts = labels([session(0, ph_pre_fingers=2, ph_post_fingers=4)])
    assert "Skin" not in pairs and "Skin" not in parts  # retired, no values: hidden
    pairs, parts = labels([session(0, ph_pre_skin=2, ph_post_skin=4)])
    assert "Skin" in pairs and "Skin" in parts  # its history still shows


def test_charted_pairs_and_templates_are_numbers(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    bad = text.replace(
        "pairs: [{label: Mood, pre: session.wb_mood_pre, post: session.wb_mood_post}]",
        "pairs: [{label: Words, pre: session.venue, post: session.notes}]",
    )
    found = problems(bad)
    assert any("'session.venue' is not a number" in p for p in found)
    assert any("'session.notes' is not a number" in p for p in found)
    bad = text.replace(
        "    skin:       {type: scale, scale: s10_down, tags: [soreness]}\n",
        "    skin:       {type: scale, scale: s10_down, tags: [soreness]}\n"
        "    where:      {type: text}\n",
    )
    found = problems(bad)
    assert any(
        "template_pairs[0]: 'soreness' has fields that aren't numbers: where" in p for p in found
    )
    assert any("template: 'soreness' has fields that aren't numbers: where" in p for p in found)
