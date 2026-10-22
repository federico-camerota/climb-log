# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path

import pytest
from conftest import LoadYaml, Problems, WriteYaml
from typer.testing import CliRunner

from climblog import cli
from climblog.modules import Module, load_module
from climblog.modules.schema import ChoiceField, NumericScale, OrdinalScale, ScaleField

ROOT = Path(__file__).parent.parent

# A small fictional module; tests append or replace parts of it.
BASE = """\
module: test_journal
name: Test journal
version: 1
kind: journal
status_levels: [GOOD, WATCH, LOW]
settings:
  low_max: {type: number, default: 4}
scales:
  s10: {min: 1, max: 10, direction: higher_better}
  freq: {type: ordinal, choices: [Rarely, Sometimes, Often], direction: lower_better}
entities:
  session:
    label: Session
    tab: Sessions
    key: [date]
    fields:
      date: {type: date, required: true}
      mood: {type: scale, scale: s10}
"""


def with_field(field: str) -> str:
    return BASE + f"      {field}\n"


def test_valid_module_loads_with_typed_parts(load: LoadYaml) -> None:
    module = load(BASE)
    assert module.module == "test_journal"
    assert module.settings["low_max"].default == 4
    assert isinstance(module.scales["s10"], NumericScale)
    assert isinstance(module.scales["freq"], OrdinalScale)
    assert isinstance(module.entities["session"].fields["mood"], ScaleField)


@pytest.mark.parametrize(
    "field",
    [
        "start: {type: time}",
        "sleep_hours: {type: number, min: 0, max: 14, step: 0.5, unit: h}",
        "attempts: {type: integer, min: 0}",
        "setting: {type: choice, choices: [Indoor, Outdoor], allow_other: true}",
        "flare: {type: choice, scale: freq}",
        "kind: {type: choice, choices: [Gym 1], choice_map: {G1: Gym 1}}",
        "tags_used: {type: multichoice, choices: [a, b]}",
        "red_flag: {type: bool, label: Red flag?}",
        "notes: {type: text, multiline: true, phase: post}",
        "grade: {type: grade, systems: [french, gym]}",
        "duration_min: {type: duration}",
        "pred_hurt: {type: percent}",
        "activity: {type: text, from: journal.session.setting}",
        "elbows: {type: scale, scale: s10, tags: [soreness], since: 2026-10-20}",
    ],
)
def test_every_field_type_loads(load: LoadYaml, field: str) -> None:
    load(with_field(field))


def test_unquoted_yes_and_no_stay_text(load: LoadYaml) -> None:
    # YAML 1.1 (PyYAML) would read these as true/false: the "Norway problem".
    module = load(with_field("answer: {type: choice, choices: [Yes, No, On, Off]}"))
    field = module.entities["session"].fields["answer"]
    assert isinstance(field, ChoiceField)
    assert field.choices == ["Yes", "No", "On", "Off"]


def test_extra_level_lists_are_allowed(load: LoadYaml) -> None:
    module = load(BASE.replace("status_levels:", "reflect_levels: [OK, ATTN]\nstatus_levels:"))
    assert module.model_extra == {"reflect_levels": ["OK", "ATTN"]}


def test_unchecked_blocks_are_accepted(load: LoadYaml) -> None:
    load(BASE + "views:\n  overview:\n    - {widget: kpi, metric: session.mood}\n")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            with_field("mood2: {type: scale, scale: s10, requried: true}"),
            "19:40 entities.session.fields.mood2.requried: unknown key (typo?)",
        ),
        (
            with_field("mood2: {type: scael, scale: s10}"),
            "19:7 entities.session.fields.mood2: missing or unknown field `type`",
        ),
        (
            with_field("mood2: {type: scale, scale: s11}"),
            "19:28 entities.session.fields.mood2.scale: unknown scale 's11' (known: s10, freq)",
        ),
        (
            with_field("mood2: {type: scale, scale: freq}"),
            "19:28 entities.session.fields.mood2.scale: scale 'freq' is ordinal",
        ),
        (
            with_field("flare: {type: choice, scale: s10}"),
            "19:29 entities.session.fields.flare.scale: a choice field needs an ordinal scale",
        ),
        (
            with_field("flare: {type: choice}"),
            "19:7 entities.session.fields.flare: give either `choices` or an ordinal `scale`",
        ),
        (
            with_field("hours: {type: number, min: 10, max: 2}"),
            "19:7 entities.session.fields.hours: min (10) is greater than max (2)",
        ),
        (
            with_field("grade: {type: grade, system: french}"),
            "19:7 entities.session.fields.grade.systems: required key is missing",
        ),
        (
            with_field("rung: {type: ref, reference: rungs}"),
            "19:25 entities.session.fields.rung.reference: unknown reference table 'rungs'",
        ),
        (
            with_field("deleted: {type: bool}"),
            "19:7 entities.session.fields.deleted: 'deleted' is reserved",
        ),
        (
            with_field("Mood: {type: scale, scale: s10}"),
            "19:7 entities.session.fields.Mood: String should match pattern",
        ),
        (
            BASE.replace("key: [date]", "key: [date, session_no]"),
            "15:17 entities.session.key[1]: key field 'session_no' is not a field",
        ),
        (
            BASE.replace("tab: Sessions", "tab: Sessions\n    date_field: mood"),
            "15:5 entities.session.date_field: date field 'mood' must be a field of type date",
        ),
        (
            BASE.replace("default: 4", "default: four"),
            "7:3 settings.low_max: default 'four' is not a valid number",
        ),
        (
            BASE.replace("min: 1, max: 10", "min: 10, max: 1"),
            "9:3 scales.s10: min (10) must be less than max (1)",
        ),
        (
            with_field("mood2: scale"),
            "19:7 entities.session.fields.mood2: missing or unknown field `type`",
        ),
        (BASE + "reflect_levels: OK\n", "19:1 reflect_levels: a level list must be a list"),
        (BASE.replace("name:", "nmae:"), "1:1 name: required key is missing"),
        (BASE.replace("kind: journal", "kind: diary"), "4:1 kind: Input should be 'journal'"),
    ],
)
def test_problems_point_at_the_line(problems: Problems, text: str, expected: str) -> None:
    found = problems(text)
    assert any(p.startswith(expected) for p in found), found


def test_unknown_top_level_key_is_reported(problems: Problems) -> None:
    assert problems(BASE + "descripton: typo\n") == ["19:1 descripton: unknown key (typo?)"]


def test_all_problems_are_reported_at_once(problems: Problems) -> None:
    text = with_field("a: {type: scale, scale: nope}") + "      b: {type: ref, reference: none}\n"
    assert len(problems(text)) == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("module: [unclosed\n", "2:1 invalid YAML"),
        ("module: a\nmodule: b\n", "2:1 invalid YAML"),
        ("- just\n- a list\n", "1:1 a module file must be a mapping"),
    ],
)
def test_unreadable_files(problems: Problems, text: str, expected: str) -> None:
    found = problems(text)
    assert found[0].startswith(expected), found


@pytest.mark.parametrize("file", sorted((ROOT / "design" / "modules").glob("*.yaml")), ids=str)
def test_design_drafts_load(file: Path) -> None:
    load_module(file)


def test_committed_json_schema_is_current() -> None:
    committed = json.loads((ROOT / "modules" / "module.schema.json").read_text(encoding="utf-8"))
    assert committed == Module.model_json_schema(), (
        "Regenerate it: uv run climblog module schema > modules/module.schema.json"
    )


runner = CliRunner()


def test_cli_validate_reports_ok_and_problems(write: WriteYaml) -> None:
    good = runner.invoke(cli.app, ["module", "validate", str(write(BASE))])
    assert good.exit_code == 0
    assert good.output.endswith(": ok\n")

    bad = runner.invoke(cli.app, ["module", "validate", str(write(BASE + "typo: 1\n"))])
    assert bad.exit_code == 1
    assert "typo: unknown key" in bad.output


def test_cli_schema_prints_json_schema() -> None:
    result = runner.invoke(cli.app, ["module", "schema"])
    assert result.exit_code == 0
    assert json.loads(result.output)["title"] == "Module"
