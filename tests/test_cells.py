# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading cells by field type, and data issues (04-storage.md §3b, §4, D-046)."""

import datetime as dt

import pytest
from conftest import LoadYaml

from climblog.expr import Value
from climblog.modules import Module
from climblog.modules.schema import BaseField
from climblog.storage import CellError, DataIssue, RawCell, RowParser, parse_cell

# A fictional module with a field of every type.
MODULE = """\
module: test_cells
name: Test cells
version: 1
kind: journal
scales:
  s10: {min: 1, max: 10, direction: higher_better}
  freq: {type: ordinal, choices: [Rarely, Sometimes, Often], direction: lower_better}
reference:
  rungs: {}
entities:
  log:
    label: Log
    tab: Log
    fields:
      date: {type: date, required: true}
      at: {type: datetime}
      start: {type: time}
      kg: {type: number, min: -20, max: 100}
      reps: {type: integer}
      mood: {type: scale, scale: s10}
      hurt_pct: {type: percent}
      minutes: {type: duration, max: 600}
      kind: {type: choice, choices: [Max hangs, Finger curls], choice_map: {Hangboard: Max hangs}}
      grip: {type: choice, choices: [Half crimp, Open hand], allow_other: true}
      shrug: {type: choice, scale: freq}
      tags: {type: multichoice, choices: [Indoor, Outdoor, Board]}
      red_flag: {type: bool}
      notes: {type: text, multiline: true}
      grade: {type: grade, systems: [french]}
      gym_grade: {type: grade, systems: [french, gym]}
      rung: {type: ref, reference: rungs}
      venue: {type: choice, choices: [Gym, Crag], required: true, visible_if: "kind == 'Max hangs'"}
      elbows: {type: scale, scale: s10, required: true, since: 2026-10-20}
"""


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


def cell(module: Module, key: str, raw: RawCell) -> Value:
    field = module.entities["log"].fields[key]
    assert isinstance(field, BaseField)
    return parse_cell(module, field, raw)


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        # blanks
        ("kg", None, None),
        ("kg", "", None),
        ("kg", "   ", None),
        # numbers: decimal commas (D-024)
        ("kg", 12.5, 12.5),
        ("kg", "7,5", 7.5),
        ("kg", " 7.5 ", 7.5),
        ("kg", "-2", -2),
        ("kg", ",5", 0.5),
        ("reps", 8.0, 8),
        ("reps", "8", 8),
        ("mood", "7,5", 7.5),
        ("hurt_pct", "75%", 75),
        ("hurt_pct", 40, 40),
        # durations in minutes
        ("minutes", 90, 90),
        ("minutes", "1:30", 90),
        ("minutes", "45,5", 45.5),
        ("minutes", dt.time(1, 15), 75),
        ("minutes", dt.timedelta(hours=2, seconds=30), 120.5),
        # dates: ISO and day-first, never month-first
        ("date", dt.date(2026, 10, 24), dt.date(2026, 10, 24)),
        ("date", dt.datetime(2026, 10, 24, 18, 30), dt.date(2026, 10, 24)),
        ("date", "2026-10-24", dt.date(2026, 10, 24)),
        ("date", "24/10/2026", dt.date(2026, 10, 24)),
        ("date", "24.10.2026", dt.date(2026, 10, 24)),
        ("date", "24-10-26", dt.date(2026, 10, 24)),
        ("date", "03/04/2026", dt.date(2026, 4, 3)),  # 3 April
        ("date", 46319, dt.date(2026, 10, 24)),  # a serial
        ("date", "24/10/2026 18:30", dt.date(2026, 10, 24)),
        ("at", "24/10/2026 18:30", dt.datetime(2026, 10, 24, 18, 30)),
        ("at", "2026-10-24T18:30:15", dt.datetime(2026, 10, 24, 18, 30, 15)),
        ("at", dt.date(2026, 10, 24), dt.datetime(2026, 10, 24)),
        ("at", 46319.75, dt.datetime(2026, 10, 24, 18, 0)),
        ("at", dt.datetime(2026, 10, 24, 7, 5), dt.datetime(2026, 10, 24, 7, 5)),
        ("start", "18:30", dt.time(18, 30)),
        ("start", "7:05:09", dt.time(7, 5, 9)),
        ("start", 0.5, dt.time(12, 0)),
        ("start", dt.time(9, 0), dt.time(9, 0)),
        ("start", dt.datetime(2026, 10, 24, 6, 45), dt.time(6, 45)),
        # choices: case and surrounding spaces don't matter; legacy values; other text
        ("kind", "max hangs ", "Max hangs"),
        ("kind", "FINGER CURLS", "Finger curls"),
        ("kind", "hangboard", "Max hangs"),  # choice_map
        ("grip", "open hand", "Open hand"),
        ("grip", " Pocket ", "Pocket"),  # allow_other
        ("shrug", "often", "Often"),  # an ordinal scale's choices
        ("tags", "board; indoor", "Board; Indoor"),
        ("tags", "Outdoor;", "Outdoor"),
        ("tags", ";", None),
        # Yes/No
        ("red_flag", True, True),
        ("red_flag", "Yes", True),
        ("red_flag", "y", True),
        ("red_flag", "TRUE", True),
        ("red_flag", "Sì", True),
        ("red_flag", "si", True),
        ("red_flag", 1, True),
        ("red_flag", "No", False),
        ("red_flag", "n", False),
        ("red_flag", 0, False),
        # text: raw (04 §3b)
        ("notes", "po' stanco", "po' stanco"),
        ("notes", "=1+1", "=1+1"),
        ("notes", "  rientro lento\nPiù riposo  ", "  rientro lento\nPiù riposo  "),
        ("notes", "   ", "   "),
        ("notes", "", None),
        ("notes", 5, "5"),
        ("notes", 7.0, "7"),
        ("notes", 7.5, "7.5"),
        ("notes", True, "TRUE"),
        ("notes", dt.datetime(2026, 10, 24), "2026-10-24"),
        ("notes", dt.datetime(2026, 10, 24, 18, 30), "2026-10-24 18:30:00"),
        ("notes", dt.time(18, 30), "18:30:00"),
        # grades (D-047): canonical text; references (checked in M5): stripped text
        ("grade", " 6b+ ", "6b+"),
        ("grade", "6B+", "6b+"),
        ("grade", "6a/6a+", "6a/6a+"),
        ("gym_grade", 6, "6"),  # a number cell
        ("gym_grade", 6.0, "6"),
        ("rung", "A3", "A3"),
    ],
)
def test_values(module: Module, key: str, raw: RawCell, expected: Value) -> None:
    value = cell(module, key, raw)
    assert value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize(
    ("key", "raw", "message"),
    [
        ("kg", "7.5x", "'7.5x' is not a number"),
        ("kg", "1.234,5", "'1.234,5' is not a number"),  # no thousands separators
        ("kg", True, "'TRUE' is not a number"),
        ("kg", dt.date(2026, 1, 1), "'2026-01-01' is not a number"),
        ("kg", 120, "120 is above the maximum 100"),
        ("kg", "-25", "-25 is below the minimum -20"),
        ("reps", 7.5, "7.5 is not a whole number"),
        ("mood", 11, "11 is above the maximum 10"),
        ("mood", "0", "0 is below the minimum 1"),
        ("hurt_pct", "120%", "120 is above the maximum 100"),
        ("minutes", "1:75", "'1:75' is not a duration in minutes or h:mm"),
        ("minutes", "lots", "'lots' is not a duration"),
        ("minutes", 700, "700 is above the maximum 600"),
        ("date", "31/02/2026", "'31/02/2026' is not a valid date"),
        ("date", "2026/10/24", "'2026/10/24' is not a date (e.g. 2026-10-24 or 24/10/2026)"),
        ("date", "24/10-2026", "'24/10-2026' is not a date"),  # mixed separators
        ("date", "Oct 24", "'Oct 24' is not a date"),
        ("date", "24/10/2026 25:00", "'24/10/2026 25:00' is not a valid date"),
        ("date", 0, "0 is not a date"),
        ("date", True, "'TRUE' is not a date"),
        ("date", dt.time(9, 0), "'09:00:00' is not a date"),
        ("at", "tomorrow", "'tomorrow' is not a date and time"),
        ("at", False, "'FALSE' is not a date and time"),
        ("at", dt.time(9, 0), "'09:00:00' is not a date and time"),
        ("start", "25:00", "'25:00' is not a valid time"),
        ("start", "6pm", "'6pm' is not a time (e.g. 18:30)"),
        ("start", 1.5, "1.5 is not a time"),
        ("start", True, "'TRUE' is not a time"),
        ("start", dt.date(2026, 10, 24), "'2026-10-24' is not a time"),
        ("kind", "Max hang", "'Max hang' is not one of: Max hangs, Finger curls"),
        ("tags", "Indoor; Gym", "'Gym' is not one of: Indoor, Outdoor, Board"),
        ("red_flag", "maybe", "'maybe' is not Yes or No"),
        ("red_flag", 2, "2 is not Yes or No"),
        ("grade", 6, "6 is not a French grade (e.g. 6b+)"),  # bare French number
        ("gym_grade", "5+", "'5+' is not a French grade (e.g. 6b+) or a gym grade (a number)"),
        ("grade", "6" * 50, "'" + "6" * 39 + "…' is not a French grade"),  # shortened
        ("kind", "x" * 60, "'" + "x" * 39 + "…' is not one of"),  # shortened
    ],
)
def test_bad_cells(module: Module, key: str, raw: RawCell, message: str) -> None:
    with pytest.raises(CellError) as error:
        cell(module, key, raw)
    assert error.value.message.startswith(message), error.value.message


# ---- Rows ----


def test_a_row_with_bad_cells_still_loads(module: Module) -> None:
    raw: dict[str, RawCell] = {
        "date": "24/10/2026",
        "kg": "7,5x",
        "mood": 12,
        "kind": "max hangs",
        "venue": "Gym",
        "elbows": 3,
        "notes": "Più riposo tra le serie",
        "unknown_column": "ignored",
    }
    values, issues = RowParser(module, "log").parse(raw, tab="Log", row=7)
    assert values["date"] == dt.date(2026, 10, 24)
    assert values["kg"] is None and values["mood"] is None  # bad cells count as missing
    assert values["kind"] == "Max hangs"
    assert values["notes"] == "Più riposo tra le serie"
    assert "unknown_column" not in values
    assert issues == [
        DataIssue("Log", 7, "kg", "'7,5x' is not a number"),
        DataIssue("Log", 7, "mood", "12 is above the maximum 10"),
    ]


@pytest.mark.parametrize(
    ("raw", "missing"),
    [
        ({"date": "2026-10-24", "kind": "Max hangs", "elbows": 2}, ["venue"]),
        ({"date": "2026-10-24", "kind": "Finger curls", "elbows": 2}, []),  # venue hidden
        ({"date": "2026-10-24", "venue": "Gym"}, ["elbows"]),
        ({"date": "2026-10-19", "venue": "Gym"}, []),  # before elbows' `since:`
        ({"kind": "Finger curls"}, ["date", "elbows"]),  # undated: since cannot excuse it
        ({"date": "yesterday", "elbows": 2}, []),  # a bad date is one issue, not two
    ],
)
def test_required_fields(module: Module, raw: dict[str, RawCell], missing: list[str]) -> None:
    _, issues = RowParser(module, "log").parse(raw, tab="Log", row=3)
    required = [i.field for i in issues if i.message == "required, but empty"]
    assert required == missing


def test_note_contents_never_reach_an_issue(module: Module) -> None:
    """Text cells never fail, so whatever a note says stays out of messages."""
    secret = "Diario: ginocchio dolorante, non dirlo"
    raw: dict[str, RawCell] = {"date": "bad", "notes": secret, "kg": "x"}
    _, issues = RowParser(module, "log").parse(raw, tab="Log", row=3)
    assert issues
    assert all("ginocchio" not in issue.message for issue in issues)


def test_blank_cells_read_as_the_default(load: LoadYaml) -> None:
    """D-048: blank = default; a default that is not valid for its field is used as written."""
    text = MODULE.replace(
        "      red_flag: {type: bool}",
        "      red_flag: {type: bool, default: false}\n"
        "      arms: {type: choice, choices: [One arm, Two arms], default: two arms}\n"
        "      odd: {type: number, default: lots}",
    )
    values, _ = RowParser(load(text), "log").parse({"date": "2026-10-24"}, tab="Log", row=3)
    assert (values["red_flag"], values["arms"], values["odd"]) == (False, "Two arms", "lots")
