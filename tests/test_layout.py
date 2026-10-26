# SPDX-License-Identifier: GPL-3.0-or-later
"""The workbook a module expects: columns, labels, groups, validation (04 §1, D-052)."""

import pytest
from conftest import LoadYaml

from climblog.modules import Module
from climblog.storage import workbook_layout
from climblog.storage.layout import (
    ColourScale,
    ColumnSpec,
    DateRule,
    ListRule,
    RangeRule,
    TabLayout,
)

# A fictional module with one field of each kind that the layout treats differently.
MODULE = """\
module: test_layout
name: Test layout
version: 4
kind: journal
settings:
  low_max: {type: number, default: 4, label: LOW at or below}
  start: {type: date, default: 2026-10-01}
scales:
  s10_down: {min: 1, max: 10, direction: lower_better}
  s10: {min: 1, max: 10, direction: higher_better}
  rpe: {min: 1, max: 10, direction: neutral}
  half: {min: 0, max: 2.5, direction: higher_better}
  effort: {type: ordinal, choices: [Easy, Hard], direction: neutral}
entities:
  session:
    label: Session
    key: [date, session_no]
    anchor_tab: Session
    sections:
      info: {label: Info, tab: Session}
      after: {label: After, tab: After, phase: post}
    fields:
      date: {type: date, required: true, section: "*"}
      session_no: {type: integer, min: 1, default: 1, section: "*"}
      start: {type: time, section: info}
      kind: {type: choice, choices: [Climb, Board], allow_other: true, section: info}
      pain: {type: scale, scale: s10_down, phase: pre, section: info}
      mood: {type: scale, scale: s10, section: after, renamed_from: feel}
      rpe: {type: scale, scale: rpe, section: after}
      tired: {type: scale, scale: half, section: after}
      effort: {type: choice, scale: effort, section: after}
      note: {type: text, multiline: true, label: "Note (it)", section: after}
      old: {type: integer, retired: true, section: after}
  fall:
    label: Fall
    tab: Falls
    id_prefix: fall
    date_field: at
    fields:
      id: {type: text}
      at: {type: datetime}
      height_m: {type: number, min: 0, max: 30, unit: m}
      weight: {type: number, max: 200}
      kg: {type: number}
      reps: {type: integer, min: 1}
      safe: {type: bool}
      grade: {type: grade, systems: [french]}
"""


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


def tabs(module: Module) -> dict[str, TabLayout]:
    return {tab.name: tab for tab in workbook_layout(module).tabs}


def columns(module: Module, tab: str) -> dict[str, ColumnSpec]:
    return {c.key: c for c in tabs(module)[tab].columns}


def test_tabs_and_column_order(module: Module) -> None:
    layout = workbook_layout(module)
    assert (layout.module, layout.version) == ("test_layout", 4)
    assert [t.name for t in layout.tabs] == ["Session", "After", "Falls"]
    assert list(columns(module, "Session")) == [
        *("date", "session_no", "start", "kind", "pain"),
        *("updated_at", "deleted"),
    ]
    assert list(columns(module, "After")) == [
        *("date", "session_no", "mood", "rpe", "tired", "effort", "note", "old"),
        *("updated_at", "deleted"),
    ]


def test_settings_rows(module: Module) -> None:
    settings = workbook_layout(module).settings
    assert [(s.key, s.label) for s in settings] == [("low_max", "LOW at or below"), ("start", "")]


def test_groups_follow_key_phase_and_section(module: Module) -> None:
    session, after = columns(module, "Session"), columns(module, "After")
    assert [session[k].group for k in ("date", "session_no", "start", "pain")] == [
        *("key", "key", "any", "pre"),
    ]
    assert after["mood"].group == "post"  # from the section's phase
    assert after["updated_at"].group == "system"
    assert columns(module, "Falls")["id"].group == "key"  # the generated id


def test_labels(module: Module) -> None:
    session, after, falls = (columns(module, t) for t in ("Session", "After", "Falls"))
    assert session["session_no"].label == "Session no"
    assert session["pain"].label == "Pain\n(1\u201310 ↓)"
    assert after["mood"].label == "Mood\n(1\u201310)"
    assert after["tired"].label == "Tired\n(0\u20132.5)"
    assert after["note"].label == "Note (it)"  # a label that says it already
    assert falls["height_m"].label == "Height m\n(m)"
    assert falls["updated_at"].label == "updated_at\n(app fills)"
    assert (after["mood"].renamed_from, after["mood"].old_label) == ("feel", "Feel\n(1\u201310)")
    assert after["old"].retired


def test_validation_by_type(module: Module) -> None:
    session, after, falls = (columns(module, t) for t in ("Session", "After", "Falls"))
    ten = tuple(str(n) for n in range(1, 11))
    assert session["date"].validation == DateRule("date")
    assert session["start"].validation == DateRule("time")
    assert session["session_no"].validation == RangeRule("whole", 1, None)
    assert session["kind"].validation == ListRule(("Climb", "Board"), strict=False)
    assert session["pain"].validation == ListRule(ten)
    assert after["rpe"].validation == ListRule(ten)
    assert after["tired"].validation == RangeRule("decimal", 0, 2.5)
    assert after["effort"].validation == ListRule(("Easy", "Hard"))
    assert after["note"].validation is None
    assert falls["height_m"].validation == RangeRule("decimal", 0, 30)
    assert falls["weight"].validation == RangeRule("decimal", None, 200)
    assert falls["kg"].validation is None
    assert falls["reps"].validation == RangeRule("whole", 1, None)
    assert falls["safe"].validation == ListRule(("Yes", "No"))
    assert falls["grade"].validation is None
    assert falls["at"].validation is None


def test_formats_colours_and_widths(module: Module) -> None:
    session, after, falls = (columns(module, t) for t in ("Session", "After", "Falls"))
    assert [session[k].number_format for k in ("date", "start", "kind")] == [
        *("DD/MM/YYYY", "HH:MM", None),
    ]
    assert falls["at"].number_format == "DD/MM/YYYY HH:MM"
    assert falls["id"].number_format == "@"
    assert session["pain"].colour_scale == ColourScale(1, 10, lower_better=True)
    assert after["mood"].colour_scale == ColourScale(1, 10, lower_better=False)
    assert after["rpe"].colour_scale is None  # neutral
    assert [after[k].width for k in ("note", "date", "effort", "rpe")] == [40, 11, 14, 10]
    assert falls["id"].width == 32


def test_reference_templates_leave_unknown_columns_alone(load: LoadYaml) -> None:
    module = load(
        """\
        module: test_layout
        name: Test layout
        version: 1
        kind: program
        entities:
          quiz:
            label: Quiz
            tab: Quiz
            key: [date]
            fields:
              date: {type: date}
              q_: {template_from_reference: questions, type: integer}
        """
    )
    (quiz,) = workbook_layout(module).tabs
    assert quiz.unknown_ok
    assert [c.key for c in quiz.columns] == ["date", "updated_at", "deleted"]
