# SPDX-License-Identifier: GPL-3.0-or-later
"""A fictional module using every construct the formula compiler translates (D-053)."""

MODULE = """\
module: test_formulas
name: Test formulas
version: 1
kind: journal
status_levels: [GOOD, WATCH, LOW]
settings:
  low_max: {type: number, default: 4}
  watch_max: {type: number, default: 6}
  strict: {type: bool, default: true}
scales:
  s10: {min: 1, max: 10, direction: higher_better}
  s10_down: {min: 1, max: 10, direction: lower_better}
entities:
  session:
    label: Session
    key: [date, session_no]
    anchor_tab: Session
    sections:
      info: {label: Info, tab: Session}
      body: {label: Body, tab: Body, phase: pre}
    fields:
      date: {type: date, required: true, section: "*"}
      session_no: {type: integer, min: 1, default: 1, section: "*"}
      kind: {type: choice, choices: [Climb, Board, Rest], section: info}
      minutes: {type: number, min: 0, max: 300, section: info}
      effort: {type: scale, scale: s10, section: info}
      warmup: {type: bool, default: true, section: info}
      pain: {type: bool, section: info}
      note: {type: text, section: info}
      fingers: {type: scale, scale: s10_down, tags: [sore], section: body}
      elbows: {type: scale, scale: s10_down, tags: [sore], since: 2026-09-20, section: body}
      skin: {type: scale, scale: s10_down, tags: [sore], section: body}
    derived:
      load: "minutes * effort"
      per_min: "effort / minutes"
      neg: "-effort"
      gap: "days_between(prev(date), date)"
      prev_load: "prev(load)"
      day: "weekday(date)"
      sore: "round(mean(fields(tag=sore)), 1)"
      sore_filled: "min(flip_all(fields(tag=sore)), missing_as=10)"
      sore_avg_filled: "round(mean(fields(tag=sore), missing_as=1), 2)"
      sore_sum: "sum(fingers, skin)"
      sore_flip_sum: "sum(flip_all(fields(tag=sore)))"
      n_present: "count(fingers, elbows, skin, note)"
      all_body: "all_present(fields(tag=sore))"
      hard: "effort >= 7 and not pain"
      either: "pain or warmup"
      board: "kind == 'Board'"
      not_climb: "kind != 'Climb'"
      blank_equal: "fingers == skin"
      label: "concat(kind, ' ', session_no)"
      first: "coalesce(fingers, skin, elbows)"
      has_note: "notnull(note)"
      warm_minutes: "minutes if warmup else 0"
      status:
        bands_of: "flip(max(fields(tag=sore)))"
        bands:
          - {le: settings.low_max, label: LOW}
          - {le: settings.watch_max, label: WATCH}
          - {else: GOOD}
      effort_status:
        require: "notnull(effort)"
        when:
          - {if: "pain", then: LOW}
          - {if: "effort >= 8", then: WATCH}
          - {else: GOOD}
      overall: "worst_of(status, effort_status)"
      advice:
        map_from: overall
        map: {LOW: Rest, WATCH: Easy, GOOD: Train}
      sets: "count(children(set))"
      top: "max(children(set).kg)"
      total: "sum(children(set).volume)"
      avg_kg: "mean(children(set).kg)"
      low_kg: "min(children(set).kg)"
      n_kg: "count(children(set).kg)"
      strict_hard: "hard and settings.strict"
      flagged: "pain or False"
      half: "effort / 2"
      five: "effort == 5"
      first_day: "coalesce(date, date)"
      level:
        bands_of: "effort"
        bands:
          - {le: 3, label: LOW}
          - {le: 6, label: WATCH}
      doubled: {expr: "effort * 2", sheet_formula: false}
      from_app_only: "doubled + 1"
      prev_app_only: "prev(doubled)"
      top_app_only: "max(children(set).heavy)"
      plus_one: {expr: "effort + 1", sheet_formula: "={effort}+1"}
      plus_two: {expr: "load + fingers", sheet_formula: "={load}+{fingers}"}
  set:
    label: Set
    tab: Sets
    key: [date, session_no, set_no]
    parent: {entity: session, key: [date, session_no]}
    fields:
      date: {type: date, required: true}
      session_no: {type: integer, min: 1, default: 1}
      set_no: {type: integer, min: 1, default: next}
      kg: {type: number, min: -20, max: 60}
      reps: {type: integer, min: 1, max: 20}
    derived:
      volume: "kg * reps"
      long: "reps > parent.minutes"
      heavy: {expr: "kg * 2", sheet_formula: false}
  rest:
    label: Rest day
    tab: Rest
    key: [date]
    fields:
      date: {type: date, required: true}
      sleep: {type: scale, scale: s10}
      start: {type: time}
    derived:
      first_start: "coalesce(start)"
      since_climb: "days_between(last(session.date, before=date), date)"
      last_effort: "last(session.effort, before=date)"
"""
