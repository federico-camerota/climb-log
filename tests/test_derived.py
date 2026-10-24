# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived fields: entry shapes, load-time checks, order and computation (03 §2.2, D-044)."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml, Problems

from climblog.expr import Kind, Value
from climblog.modules import load_module
from climblog.modules.checks import derived_plan
from climblog.modules.derived import compute

DRAFTS = Path(__file__).parent.parent / "design" / "modules"
LEVELS = ("GOOD", "WATCH", "LOW")

# A small fictional module with one entry of each shape.
BASE = """\
module: test_derived
name: Test derived
version: 1
kind: journal
status_levels: [GOOD, WATCH, LOW]
alert_levels: [OK, ALERT]
settings:
  low_max: {type: number, default: 4}
  watch_max: {type: number, default: 6}
scales:
  s10: {min: 1, max: 10, direction: higher_better}
  s10_down: {min: 1, max: 10, direction: lower_better}
entities:
  day:
    label: Day
    tab: Days
    fields:
      date: {type: date}
      mood: {type: scale, scale: s10}
      energy: {type: scale, scale: s10}
      fingers: {type: scale, scale: s10_down, tags: [soreness]}
      skin: {type: scale, scale: s10_down, tags: [soreness]}
      red_flag: {type: bool}
      kind: {type: choice, choices: [Climb, Rest]}
    derived:
      wb_status:
        require: "all_present(mood, energy)"
        bands_of: "min(mood, energy)"
        bands:
          - {le: settings.low_max, label: LOW}
          - {le: settings.watch_max, label: WATCH}
          - {else: GOOD}
      overall: "worst_of(wb_status, body_status)"
      body_status:
        bands_of: "flip(max(fields(tag=soreness)))"
        bands:
          - {le: 4, label: LOW}
          - {le: 6, label: WATCH}
          - {else: GOOD}
      alert:
        levels: alert_levels
        when:
          - {if: "red_flag", then: ALERT}
          - {if: "notnull(mood)", then: OK}
      note:
        type: text
        when:
          - {if: "red_flag", then: "Stop and rest"}
          - {else: "Carry on"}
      advice:
        map_from: overall
        map: {LOW: Rest day, WATCH: Easy session}
      score:
        require: "all_present(mood, energy)"
        expr: "round(mean(mood, energy), 1)"
      gap: "program.week * 7"
      gap_weeks: "gap / 7"
      verdict: {plugin: test.verdict}
"""
SETTINGS: dict[str, Value] = {"low_max": 4, "watch_max": 6}


def test_entries_are_ordered_by_what_they_read(load: LoadYaml) -> None:
    plan = derived_plan(load(BASE), "day")
    keys = [step.key for step in plan.steps]
    assert keys == ["wb_status", "body_status", "overall", "alert", "note", "advice", "score"]
    assert plan.deferred == ("gap", "gap_weeks", "verdict")


def test_result_kinds(load: LoadYaml) -> None:
    kinds = {step.key: step.kind for step in derived_plan(load(BASE), "day").steps}
    assert kinds["wb_status"] == Kind("text", levels=LEVELS)
    assert kinds["overall"] == Kind("text", levels=LEVELS)
    assert kinds["alert"] == Kind("text", levels=("OK", "ALERT"))
    assert kinds["note"] == Kind("text")
    assert kinds["score"] == Kind("number", scale=(1.0, 10.0))


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            {"mood": 7, "energy": 5, "fingers": 2, "skin": 7, "red_flag": True},
            {"wb_status": "WATCH", "body_status": "LOW", "overall": "LOW", "alert": "ALERT",
             "note": "Stop and rest", "advice": "Rest day", "score": 6.0},
        ),
        (
            {"mood": 8, "energy": 9, "fingers": 3},
            {"wb_status": "GOOD", "body_status": "GOOD", "overall": "GOOD", "alert": "OK",
             "note": "Carry on", "advice": None, "score": 8.5},
        ),
        (  # nothing logged: blanks, not the best band
            {},
            {"wb_status": None, "body_status": None, "overall": None, "alert": None,
             "note": "Carry on", "advice": None, "score": None},
        ),
        (  # `require` not met; worst_of ignores the blank status
            {"mood": 3, "fingers": 5},
            {"wb_status": None, "body_status": "WATCH", "overall": "WATCH", "alert": "OK",
             "note": "Carry on", "advice": "Easy session", "score": None},
        ),
    ],
)  # fmt: skip
def test_compute(load: LoadYaml, record: dict[str, Value], expected: dict[str, Value]) -> None:
    plan = derived_plan(load(BASE), "day")
    assert compute(plan, {"date": dt.date(2026, 10, 22), **record}, SETTINGS) == expected


def test_bands_follow_the_settings(load: LoadYaml) -> None:
    plan = derived_plan(load(BASE), "day")
    record: dict[str, Value] = {"mood": 5, "energy": 9}
    assert compute(plan, record, SETTINGS)["wb_status"] == "WATCH"
    assert compute(plan, record, {**SETTINGS, "low_max": 5})["wb_status"] == "LOW"


def test_a_band_limit_is_inclusive(load: LoadYaml) -> None:
    plan = derived_plan(load(BASE), "day")
    assert compute(plan, {"mood": 4, "energy": 4}, SETTINGS)["wb_status"] == "LOW"
    assert compute(plan, {"mood": 4.5, "energy": 9}, SETTINGS)["wb_status"] == "WATCH"


# Each case: (text to replace, replacement, where under entities.day.derived, message start).
@pytest.mark.parametrize(
    ("old", "new", "path", "message"),
    [
        # statuses (D-044: labels must be in the level list)
        ("watch_max, label: WATCH}", "watch_max, label: WACTH}", "wb_status.bands[1].label",
         "label 'WACTH' is not in status_levels (GOOD, WATCH, LOW)"),
        ("then: OK}", "then: FINE}", "alert.when[1].then",
         "label 'FINE' is not in alert_levels (OK, ALERT)"),
        ("levels: alert_levels", "levels: alarm_levels", "alert.levels",
         "unknown level list 'alarm_levels' (known: status_levels, alert_levels)"),
        ("        type: text\n", "", "note.when[0].then",
         "label 'Stop and rest' is not in status_levels"),
        ("worst_of(wb_status, body_status)", "worst_of(wb_status, alert)", "overall",
         "worst_of() needs statuses on one level list, not [GOOD, WATCH, LOW] and [OK, ALERT]"),
        ("worst_of(wb_status, body_status)", "worst_of(wb_status, note)", "overall",
         "worst_of() needs statuses (bands: or when: results)"),
        # expressions in each place
        ('require: "all_present(mood, energy)"\n        bands_of',
         'require: "mood"\n        bands_of', "wb_status.require",
         "`require` must give yes/no, not number"),
        ('bands_of: "min(mood, energy)"', 'bands_of: "kind"', "wb_status.bands_of",
         "`bands_of` must give a number, not text"),
        ("le: settings.low_max", "le: settings.lowmax", "wb_status.bands[0].le",
         "unknown setting 'lowmax' (did you mean 'low_max'?)"),
        ('if: "red_flag", then: ALERT', 'if: "mood", then: ALERT', "alert.when[0].if",
         "`if` must give yes/no, not number"),
        ("round(mean(mood, energy), 1)", "fields(tag=soreness)", "score.expr",
         "a derived field must be one value, not a list"),
        ("round(mean(mood, energy), 1)", "mod + 1", "score.expr",
         "unknown field 'mod' (did you mean 'mood'?) (at character 1)"),
        ("round(mean(mood, energy), 1)", "overall == 'LOWW'", "score.expr",
         "'LOWW' is not a choice of 'overall'"),
        ("round(mean(mood, energy), 1)", "mood +", "score.expr", "invalid expression"),
        # map_from
        ("map_from: overall", "map_from: mood", "advice.map_from",
         "'mood' has no fixed values (a status or a choice)"),
        ("{LOW: Rest day", "{LOWW: Rest day", "advice.map.LOWW",
         "'LOWW' is not a value of 'overall' (values: GOOD, WATCH, LOW)"),
        # names
        ("      score:\n", "      mood:\n", "mood", "'mood' is already a field of the entity"),
        ("      score:\n", "      deleted:\n", "deleted",
         "'deleted' is reserved for a column the app adds"),
        # shapes
        ("{le: 6, label: WATCH}\n          - {else: GOOD}",
         "{else: GOOD}\n          - {le: 6, label: WATCH}", "body_status",
         "`else` must be the last item"),
        ("type: text", "type: text\n        levels: alert_levels", "note",
         "give `levels` for a status or `type: text` for a message, not both"),
        ('gap_weeks: "gap / 7"', "gap_weeks: {formula: gap / 7}", "gap_weeks",
         "a derived field is an expression, or has one of: expr, bands_of, when, map_from, plugin"),
        ('gap_weeks: "gap / 7"', "gap_weeks: 7", "gap_weeks",
         "a derived field is an expression, or has one of"),
        ('gap_weeks: "gap / 7"', "gap_weeks: {when: [{else: x}]}", "gap_weeks",
         "an `else` alone is not a rule"),
    ],
)  # fmt: skip
def test_problems(problems: Problems, old: str, new: str, path: str, message: str) -> None:
    assert BASE.count(old) == 1, old
    found = problems(BASE.replace(old, new))
    assert len(found) == 1, found
    assert found[0].split(" ", 1)[1].startswith(f"entities.day.derived.{path}: {message}"), found


def test_a_status_needs_a_level_list(problems: Problems) -> None:
    """Without status_levels every unmarked status is reported; the entries reading them are not."""
    found = [
        line.split(" ", 1)[1]
        for line in problems(BASE.replace("status_levels: [GOOD, WATCH, LOW]\n", ""))
    ]
    message = "a status needs the module's `status_levels` or a `levels:` list"
    assert [line.split(":")[0] for line in found] == [
        "entities.day.derived.wb_status",
        "entities.day.derived.body_status",
    ]
    assert all(message in line for line in found)


def test_cycles_are_reported_once(problems: Problems) -> None:
    text = BASE.replace('gap_weeks: "gap / 7"', 'a: "b + 1"\n      b: "score + a"')
    found = problems(text)
    assert len(found) == 1
    assert "entities.day.derived.a: derived fields depend on each other: a → b → a" in found[0]


def test_an_entry_reading_itself_is_a_cycle(problems: Problems) -> None:
    found = problems(BASE.replace('gap_weeks: "gap / 7"', 'gap_weeks: "gap_weeks + 1"'))
    assert "derived fields depend on each other: gap_weeks → gap_weeks" in found[0]


def test_fields_selectors_are_not_dependencies(load: LoadYaml) -> None:
    """`fields(tag=soreness)` selects by tag; a derived value named `soreness` is not read."""
    text = BASE.replace('gap_weeks: "gap / 7"', 'soreness: "count(fields(tag=soreness))"')
    plan = derived_plan(load(text), "day")
    assert "soreness" in [step.key for step in plan.steps]


# ---- The drafts ----


def test_journal_session_plan() -> None:
    journal = load_module(DRAFTS / "journal.yaml")
    plan = derived_plan(journal, "session")
    assert plan.deferred == ("log_check",)
    statuses = [step.key for step in plan.steps if step.kind.levels == LEVELS]
    assert statuses == [
        "wb_pre_status",
        "wb_post_status",
        "wb_status",
        "ph_status",
        "mn_status",
        "feel_status",
        "overall_status",
    ]


def test_journal_session_follows_the_legacy_rules() -> None:
    """00-current-state.md §1 on a fictional session: worst soreness 7 → LOW, overall = worst."""
    journal = load_module(DRAFTS / "journal.yaml")
    plan = derived_plan(journal, "session")
    settings = {key: setting.default for key, setting in journal.settings.items()}
    parts = ["fingers", "forearms", "elbows", "shoulders", "neck_traps", "wrists", "skin"]
    record: dict[str, Value] = {
        "date": dt.date(2026, 10, 22),
        "wb_sleep_quality": 7,
        "wb_mood_pre": 8,
        "wb_energy_pre": 5,
        **{f"ph_pre_{part}": 2 for part in parts},
        "ph_pre_fingers": 7,
        "feel_enjoyment": 9,
        "feel_satisfaction": 8,
        "rf_off_severity": 6,
    }
    result = compute(plan, record, settings)
    assert result["wb_pre_status"] == "WATCH"  # min 5 ≤ WatchMax 6
    assert result["ph_readiness"] == 8.3  # 11 - mean(7, 2, 2, 2, 2, 2, 2)
    assert result["ph_status"] == "LOW"  # max 7 ≥ 11 - LowMax
    assert result["mn_status"] is None  # all blank stays blank, also with missing_as
    assert result["overall_score"] == 8.4  # mean of the scores present
    assert result["overall_status"] == "LOW"
    assert result["reflect_status"] == "WORTH NOTING"  # severity 6 ≥ NoteMin 6

    record["ph_pre_fingers"] = 5
    assert compute(plan, record, settings)["ph_status"] == "WATCH"  # max 5 ≥ 11 - WatchMax


def test_shoulder_action_maps_the_status() -> None:
    shoulder = load_module(DRAFTS / "shoulder.yaml")
    plan = derived_plan(shoulder, "checkin")
    settings = {key: setting.default for key, setting in shoulder.settings.items()}
    result = compute(plan, {"pain_during": 3, "pain_next_am": 1}, settings)
    assert result["status"] == "YELLOW"
    assert str(result["action"]).startswith("Hold/reduce load")
    assert plan.deferred == ()


def test_fields_wait_for_reference_templates() -> None:
    """q1..q20 come from a reference table (M5), so `fields(tag=q)` cannot be checked yet."""
    fear = load_module(DRAFTS / "fear-of-falling.yaml")
    assert derived_plan(fear, "q20").deferred == ("avg_all", "by_category")


def test_prev_orders_the_entries(load: LoadYaml) -> None:
    """`prev(x)` needs x's type, so x is checked (and computed) first."""
    text = BASE.replace(
        'gap_weeks: "gap / 7"', 'was_low: "prev(late) == \'LOW\'"\n      late: "overall"'
    )
    keys = [step.key for step in derived_plan(load(text), "day").steps]
    assert keys.index("late") < keys.index("was_low")


def test_prev_of_the_entry_itself_is_not_supported_yet(problems: Problems) -> None:
    found = problems(BASE.replace('gap_weeks: "gap / 7"', 'streak: "prev(streak) + 1"'))
    assert len(found) == 1
    assert "derived.streak: prev() of the entry itself is not supported yet" in found[0]
