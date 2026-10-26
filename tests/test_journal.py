# SPDX-License-Identifier: GPL-3.0-or-later
"""The climbing journal reproduces every rule of the legacy workbook (00-current-state.md §1).

One test per rule, on fictional values (D-034, D-056). The rules of `Summary - Recent`,
`Summary - Trends` and `Log Search` are app views (M3, M4), not module fields.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from climblog.expr import Value
from climblog.modules import Module, load_module
from climblog.modules.compute import compute_module

JOURNAL = Path(__file__).parent.parent / "modules" / "journal.yaml"
PARTS = ["fingers", "forearms", "elbows", "shoulders", "neck_traps", "wrists", "skin"]
LEGACY_PARTS = ["fingers", "forearms", "shoulders", "wrists", "skin"]  # before 2026-10-20
DAY = dt.date(2026, 10, 22)  # a Thursday, after elbows and neck/traps started (since:)


@pytest.fixture(scope="module")
def journal() -> Module:
    return load_module(JOURNAL)


def settings(journal: Module, **changes: Value) -> dict[str, Value]:
    return {k: s.default for k, s in journal.settings.items()} | changes


def session(journal: Module, **values: Value) -> dict[str, Value]:
    """The derived values of one fictional session (no other records)."""
    return computed(journal, [{"date": DAY, **values}])["session"][0]


def computed(
    journal: Module,
    sessions: Sequence[Mapping[str, Value]],
    rest_days: Sequence[Mapping[str, Value]] = (),
) -> dict[str, list[dict[str, Value]]]:
    tables: Mapping[str, Any] = {"session": sessions, "rest_day": rest_days}
    return compute_module(journal, tables, settings(journal))


def wellbeing(pre: tuple[int, int, int], post: tuple[int, int, int]) -> dict[str, Value]:
    """Sleep quality, mood, energy before; fatigue (↓), mood, recovery after."""
    keys_pre = ("wb_sleep_quality", "wb_mood_pre", "wb_energy_pre")
    keys_post = ("wb_fatigue_post", "wb_mood_post", "wb_recovery_feel")
    values: dict[str, Value] = dict(zip(keys_pre, pre, strict=True))
    return values | dict(zip(keys_post, post, strict=True))


def mental(**changes: int) -> dict[str, Value]:
    values: dict[str, Value] = {
        "mn_life_stress": 3,  # ↓
        "mn_confidence": 7,
        "mn_motivation": 8,
        "mn_anxiety": 4,  # ↓
        "mn_focus": 7,
        "mn_fall_commitment": 6,
        "mn_fear_response": 5,  # ↓
        "mn_route_confidence": 7,
        "mn_approach": 8,
    }
    return values | changes


# ---- Settings ----


def test_settings_have_the_legacy_defaults(journal: Module) -> None:
    assert settings(journal) == {
        "low_max": 4,
        "watch_max": 6,
        "attn_min": 8,
        "note_min": 6,
        "trend_delta": 0.5,
    }


# ---- Wellbeing ----


@pytest.mark.parametrize(
    ("pre", "status"), [((7, 8, 9), "GOOD"), ((7, 6, 9), "WATCH"), ((4, 8, 9), "LOW")]
)
def test_wellbeing_pre_status_bands_the_lowest(
    journal: Module, pre: tuple[int, int, int], status: str
) -> None:
    assert session(journal, **wellbeing(pre, (2, 8, 8)))["wb_pre_status"] == status


def test_wellbeing_pre_status_needs_all_three(journal: Module) -> None:
    values = wellbeing((7, 8, 9), (2, 8, 8))
    del values["wb_energy_pre"]
    assert session(journal, **values)["wb_pre_status"] is None


def test_wellbeing_post_status_flips_fatigue(journal: Module) -> None:
    # min(11 - 8, 9, 9) = 3 → LOW; fatigue 2 → min(9, 9, 9) → GOOD
    assert session(journal, **wellbeing((8, 8, 8), (8, 9, 9)))["wb_post_status"] == "LOW"
    assert session(journal, **wellbeing((8, 8, 8), (2, 9, 9)))["wb_post_status"] == "GOOD"


def test_wellbeing_status_is_the_worse_of_pre_and_post(journal: Module) -> None:
    result = session(journal, **wellbeing((8, 8, 8), (6, 9, 9)))  # post: 11 - 6 = 5 → WATCH
    assert (result["wb_pre_status"], result["wb_post_status"]) == ("GOOD", "WATCH")
    assert result["wb_status"] == "WATCH"


def test_wellbeing_score_is_the_mean_with_fatigue_flipped(journal: Module) -> None:
    # (7 + 8 + 9 + (11 - 3) + 6 + 7) / 6 = 45 / 6 = 7.5
    assert session(journal, **wellbeing((7, 8, 9), (3, 6, 7)))["wb_score"] == 7.5


def test_wellbeing_score_needs_all_six(journal: Module) -> None:
    values = wellbeing((7, 8, 9), (3, 6, 7))
    del values["wb_recovery_feel"]
    assert session(journal, **values)["wb_score"] is None


# ---- Physical ----


def soreness(phase: str, values: Mapping[str, int]) -> dict[str, Value]:
    return {f"ph_{phase}_{part}": value for part, value in values.items()}


def test_physical_readiness_is_11_minus_the_mean_pre_soreness(journal: Module) -> None:
    pre = dict.fromkeys(PARTS, 2) | {"fingers": 6}  # mean 18 / 7
    assert session(journal, **soreness("pre", pre))["ph_readiness"] == 8.4  # 11 - 2.57


@pytest.mark.parametrize(("worst", "status"), [(4, "GOOD"), (5, "WATCH"), (6, "WATCH"), (7, "LOW")])
def test_physical_status_bands_the_worst_pre_soreness(
    journal: Module, worst: int, status: str
) -> None:
    pre = dict.fromkeys(PARTS, 1) | {"shoulders": worst}  # ≥ 11 - LowMax = 7 → LOW
    assert session(journal, **soreness("pre", pre))["ph_status"] == status


def test_post_soreness_is_recorded_but_not_scored(journal: Module) -> None:
    pre = soreness("pre", dict.fromkeys(PARTS, 2))
    result = session(journal, **pre, **soreness("post", dict.fromkeys(PARTS, 9)))
    assert (result["ph_readiness"], result["ph_status"]) == (9.0, "GOOD")


def test_new_body_parts_count_from_their_start(journal: Module) -> None:
    old = {"date": dt.date(2026, 10, 1), **soreness("pre", dict.fromkeys(LEGACY_PARTS, 3))}
    old["ph_pre_elbows"] = 9  # typed before elbows were tracked: left out (since:)
    result = computed(journal, [old])["session"][0]
    assert (result["ph_readiness"], result["ph_status"]) == (8.0, "GOOD")


# ---- Mental ----


def test_mental_score_is_the_mean_with_the_down_items_flipped(journal: Module) -> None:
    # 8 + 7 + 8 + 7 + 7 + 6 + 6 + 7 + 8 = 64 → 64 / 9 = 7.1 (stress 3, anxiety 4, fear 5 flipped)
    assert session(journal, **mental())["mn_score"] == 7.1


def test_mental_score_needs_all_nine(journal: Module) -> None:
    values = mental()
    del values["mn_focus"]
    assert session(journal, **values)["mn_score"] is None


def test_mental_status_is_the_lowest_with_missing_as_10(journal: Module) -> None:
    assert session(journal, **mental())["mn_status"] == "WATCH"  # fear 5 → 6, commitment 6
    assert session(journal, mn_confidence=9, mn_anxiety=8)["mn_status"] == "LOW"  # 11 - 8 = 3
    assert session(journal, mn_confidence=9)["mn_status"] == "GOOD"  # the rest count as 10


# ---- Session feel ----


def test_feel_score_and_status(journal: Module) -> None:
    result = session(journal, feel_enjoyment=9, feel_satisfaction=6, feel_effort=10)
    assert result["feel_score"] == 7.5  # effort is informational
    assert result["feel_status"] == "WATCH"  # min 6
    assert session(journal, feel_enjoyment=9)["feel_score"] is None


# ---- Overall ----


def test_overall_score_is_the_mean_of_the_four_scores(journal: Module) -> None:
    values = (
        wellbeing((7, 8, 9), (3, 6, 7))  # 7.5
        | soreness("pre", dict.fromkeys(PARTS, 2))  # readiness 9.0
        | mental()  # 7.1
        | {"feel_enjoyment": 9, "feel_satisfaction": 6}  # 7.5
    )
    result = session(journal, **values)
    assert result["overall_score"] == round((7.5 + 9.0 + 7.1 + 7.5) / 4, 1)


def test_overall_status_is_the_worst_of_the_four(journal: Module) -> None:
    values = (
        wellbeing((8, 8, 8), (2, 8, 8))  # GOOD
        | soreness("pre", dict.fromkeys(PARTS, 2) | {"skin": 7})  # LOW
        | {"feel_enjoyment": 9, "feel_satisfaction": 8}  # GOOD
    )
    assert session(journal, **values)["overall_status"] == "LOW"


# ---- Reflection ----


@pytest.mark.parametrize(
    ("severity", "priority", "status"),
    [
        (3, 5, "GOOD"),
        (6, 2, "WORTH NOTING"),  # ≥ NoteMin
        (2, 8, "NEEDS ATTENTION"),  # ≥ AttnMin
        (None, None, None),
    ],
)
def test_reflection_status(
    journal: Module, severity: int | None, priority: int | None, status: str | None
) -> None:
    result = session(journal, rf_off_severity=severity, rf_change_priority=priority)
    assert result["reflect_status"] == status


# ---- Session details ----


def test_weekday_month_and_days_since_the_previous_session(journal: Module) -> None:
    rows: list[dict[str, Value]] = [
        {"date": dt.date(2026, 10, 18)},
        {"date": DAY},
        {"date": DAY, "session_no": 2},  # a second session the same day
    ]
    result = computed(journal, rows)["session"]
    assert [r["weekday"] for r in result] == ["Sun", "Thu", "Thu"]
    assert result[1]["month"] == "2026-10"
    assert [r["days_since_prev"] for r in result] == [None, 4, 0]


def test_log_check_lists_the_incomplete_classes(journal: Module) -> None:
    # As the legacy formula: Wellbeing, Mental, Feel need their score, Reflect its status
    # (severity or priority), Physical every pre and post soreness value.
    full = (
        wellbeing((7, 8, 9), (3, 6, 7))
        | soreness("pre", dict.fromkeys(PARTS, 2))
        | soreness("post", dict.fromkeys(PARTS, 3))
        | mental()
        | {"feel_enjoyment": 9, "feel_satisfaction": 6}  # effort is informational
        | {"rf_change_priority": 4}  # enough for the reflection status
    )
    assert session(journal, **full)["log_check"] == "Complete"
    missing = dict(full)
    del missing["ph_post_elbows"], missing["rf_change_priority"]
    assert session(journal, **missing)["log_check"] == "Missing: Physical, Reflect"
    assert session(journal)["log_check"] == "Missing: Wellbeing, Physical, Mental, Feel, Reflect"


# ---- Rest days ----


def rest_day(**values: Value) -> dict[str, Value]:
    return {"date": dt.date(2026, 10, 24), **values}


def test_rest_day_scores_and_statuses(journal: Module) -> None:
    body = {f"body_{part}": 2 for part in PARTS} | {"body_skin": 6}
    day = rest_day(sleep_quality=8, mood=7, energy=6, motivation=9, life_stress=3, **body)
    result = computed(journal, [], [day])["rest_day"][0]
    assert result["wellbeing_score"] == 7.6  # (8 + 7 + 6 + 9 + (11 - 3)) / 5
    assert result["wellbeing_status"] == "WATCH"  # lowest: energy 6
    assert result["body_readiness"] == 8.4  # 11 - 18 / 7
    assert result["body_status"] == "WATCH"  # worst 6 → 11 - 6 = 5
    assert result["status"] == "WATCH"


def test_days_since_the_last_climb(journal: Module) -> None:
    sessions = [{"date": dt.date(2026, 10, 18)}, {"date": dt.date(2026, 10, 21)}]
    rests = [rest_day(), rest_day(date=dt.date(2026, 10, 21)), rest_day(date=dt.date(2026, 10, 1))]
    result = computed(journal, sessions, rests)["rest_day"]
    assert [r["days_since_climb"] for r in result] == [3, 3, None]  # strictly before the day
    assert [r["weekday"] for r in result] == ["Sat", "Wed", "Thu"]
