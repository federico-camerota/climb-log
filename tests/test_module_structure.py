# SPDX-License-Identifier: GPL-3.0-or-later
"""Templates, split entities and child entities (03-module-framework.md §1, §2.1b, §3)."""

from pathlib import Path

import pytest
from conftest import LoadYaml, Problems

from climblog.modules import load_module
from climblog.modules.schema import ReferenceTemplateUse, ScaleField

DRAFTS = Path(__file__).parent.parent / "design" / "modules"

# A small fictional module: a session split over two tabs, with a soreness template,
# and a child entity of sets.
BASE = """\
module: test_journal
name: Test journal
version: 1
kind: journal
scales:
  s10: {min: 1, max: 10, direction: lower_better}
templates:
  soreness:
    fingers: {type: scale, scale: s10, tags: [soreness]}
    skin: {type: scale, scale: s10, tags: [soreness], since: 2026-10-20}
entities:
  session:
    label: Session
    key: [date, session_type]
    sections:
      info: {label: Info, tab: Sessions}
      body: {label: Body, phase: pre, tab: Body}
    fields:
      date: {type: date, section: "*"}
      session_type: {type: choice, choices: [Hangs, Curls]}
      venue: {type: text, section: info}
      pre_: {template: soreness, section: body, phase: pre}
      note: {type: text, section: body}
  set:
    label: Set
    tab: Sets
    key: [date, set_no]
    parent: {entity: session, key: [date], fixed: {session_type: Hangs}}
    fields:
      date: {type: date}
      set_no: {type: integer}
      kg: {type: number}
"""


def test_templates_expand_in_place_with_placement(load: LoadYaml) -> None:
    session = load(BASE).entities["session"]
    assert list(session.fields) == [
        "date",
        "session_type",
        "venue",
        "pre_fingers",
        "pre_skin",
        "note",
    ]
    skin = session.fields["pre_skin"]
    assert isinstance(skin, ScaleField)
    assert (skin.section, skin.phase, skin.tags, str(skin.since)) == (
        "body",
        "pre",
        ["soreness"],
        "2026-10-20",
    )


def test_tab_fields_repeat_the_key_on_every_tab(load: LoadYaml) -> None:
    module = load(BASE)
    session, sets = module.entities["session"], module.entities["set"]
    assert session.tab_fields() == {
        "Sessions": ["date", "session_type", "venue"],
        "Body": ["date", "session_type", "pre_fingers", "pre_skin", "note"],
    }
    assert session.main_tab == "Sessions"
    assert sets.tab_fields() == {"Sets": ["date", "set_no", "kg"]}
    assert sets.main_tab == "Sets"


def test_anchor_tab_chooses_the_main_tab(load: LoadYaml) -> None:
    module = load(BASE.replace("    sections:\n", "    anchor_tab: Body\n    sections:\n"))
    assert module.entities["session"].main_tab == "Body"


def test_sections_without_tabs_only_group_fields(load: LoadYaml) -> None:
    text = BASE.replace(
        "    fields:\n      date: {type: date}\n",
        "    sections:\n      main: {label: Main}\n    fields:\n      date: {type: date}\n",
    ).replace("kg: {type: number}", "kg: {type: number, section: main}")
    assert load(text).entities["set"].tab_fields() == {"Sets": ["date", "set_no", "kg"]}


def test_journal_draft_matches_the_legacy_tabs() -> None:
    journal = load_module(DRAFTS / "journal.yaml")
    session = journal.entities["session"]
    tabs = session.tab_fields()
    assert list(tabs) == [
        "Session",
        "Wellbeing",
        "Physical",
        "Mental",
        "Session Feel",
        "Wins & Reflect",
    ]
    assert sum(1 for f in session.fields if f.startswith("ph_pre_")) == 7
    assert tabs["Physical"][:3] == ["date", "session_no", "ph_pre_fingers"]
    assert sum(1 for f in journal.entities["rest_day"].fields if f.startswith("body_")) == 7


def test_reference_templates_wait_for_reference_tables() -> None:
    fear = load_module(DRAFTS / "fear-of-falling.yaml")
    assert isinstance(fear.entities["q20"].fields["q_"], ReferenceTemplateUse)


SET_FIELDS = "    parent: {entity: session, key: [date], fixed: {session_type: Hangs}}\n" + (
    "    fields:\n      date: {type: date}\n      "
)
SESSION_FIELDS = (
    "    sections:\n      info: {label: Info, tab: Sessions}\n"
    "      body: {label: Body, phase: pre, tab: Body}\n    fields:\n"
    '      date: {type: date, section: "*"}\n'
    "      session_type: {type: choice, choices: [Hangs, Curls]}\n      "
)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        # templates
        (
            "{template: soreness, section",
            "{template: sorenes, section",
            "22:14 entities.session.fields.pre_.template: unknown template 'sorenes'",
        ),
        (
            "skin: {type: scale, scale: s10, tags: [soreness], since: 2026-10-20}",
            "skin: {template: soreness}",
            "10:5 templates.soreness.skin: a template cannot use another template",
        ),
        (
            "fingers: {type: scale, scale: s10,",
            "fingers: {type: scale, scale: s10, section: body,",
            "9:40 templates.soreness.fingers.section: set the section where the template is used",
        ),
        (
            "section: body, phase: pre}",
            "section: body, label: Pre}",
            "22:49 entities.session.fields.pre_.label: unknown key (typo?)",
        ),
        (
            "      note: {type: text, section: body}",
            "      note: {type: text, section: body}\n      pre_skin: {type: text, section: body}",
            "24:7 entities.session.fields.pre_skin: field 'pre_skin' is defined twice",
        ),
        # sections and tabs
        ("venue: {type: text, section: info}", "venue: {type: text, section: inf}",
         "21:7 entities.session.fields.venue: unknown section 'inf' (known: info, body)"),
        ("venue: {type: text, section: info}", "venue: {type: text}",
         "21:7 entities.session.fields.venue: the entity is split across tabs"),
        ("venue: {type: text, section: info}", "venue: {type: text, section: '*'}",
         "21:7 entities.session.fields.venue: only key fields can be on every tab"),
        ("    label: Session\n", "    label: Session\n    tab: Sessions\n",
         "14:5 entities.session.tab: a split entity gets its tabs from its sections"),
        ("body: {label: Body, phase: pre, tab: Body}", "body: {label: Body, phase: pre}",
         "17:7 entities.session.sections.body: in a split entity every section needs a tab"),
        ("    key: [date, session_type]\n", "",
         "12:3 entities.session: a split entity needs a natural `key` to join its tabs"),
        ("    sections:\n", "    anchor_tab: Notes\n    sections:\n",
         "15:5 entities.session.anchor_tab: 'Notes' is not a tab of this entity"),
        ("    tab: Sets\n", "",
         "24:3 entities.set: an entity needs a `tab` (or sections with tabs)"),
        ("    tab: Sets\n", "    tab: Sets\n    anchor_tab: Sets\n",
         "27:5 entities.set.anchor_tab: only split entities have an anchor tab"),
        ("tab: Sets", "tab: body",
         "26:5 entities.set.tab: tab 'body' is already used by entity 'session'"),
        ("tab: Sets", "tab: _Settings",
         "26:5 entities.set.tab: '_Settings' is a tab the app manages itself"),
        ("tab: Sets", "tab: Sets/Reps",
         "26:5 entities.set.tab: a tab name cannot contain / (spreadsheet rule)"),
        ("tab: Sets", "tab: " + "S" * 32,
         "26:5 entities.set.tab: a tab name must be 1 to 31 characters"),
        # parents
        ("{entity: session, key", "{entity: sesion, key",
         "28:14 entities.set.parent.entity: unknown entity 'sesion' (known: session)"),
        ("{entity: session, key", "{entity: set, key",
         "28:14 entities.set.parent.entity: an entity cannot be its own parent"),
        ("fixed: {session_type: Hangs}", "fixed: {session_type: Pulls}",
         "28:52 entities.set.parent.fixed.session_type: 'Pulls' is not a choice of 'session_type'"),
        ("fixed: {session_type: Hangs}", "fixed: {}",
         "28:5 entities.set.parent: `key` and `fixed` must together be the key of 'session'"),
        ("    key: [date, set_no]\n", "    key: [set_no]\n",
         "28:37 entities.set.parent.key[0]: 'date' must be a field in this entity's key"),
        # `default: next` (D-050)
        ("set_no: {type: integer}", "set_no: {type: number, default: next}",
         "31:30 entities.set.fields.set_no.default: `default: next` needs an integer key field"),
        ("kg: {type: number}", "kg: {type: number, default: next}",
         "32:26 entities.set.fields.kg.default: `default: next` needs an integer key field"),
        ("key: [date, set_no]\n" + SET_FIELDS + "set_no: {type: integer}",
         "key: [set_no]\n" + SET_FIELDS + "set_no: {type: integer, default: next}",
         "31:31 entities.set.fields.set_no.default: `default: next` needs an integer key field"),
        ("key: [date, session_type]\n" + SESSION_FIELDS,
         "key: [date, session_type, n]\n" + SESSION_FIELDS
         + "n: {type: integer, default: next, section: '*'}\n      ",
         "21:26 entities.session.fields.n.default: `default: next` needs an integer key field"),
        # field evolution
        ("date: {type: date, section: \"*\"}", "date: {type: date, section: \"*\", retired: true}",
         "19:7 entities.session.fields.date: a key or required field cannot be retired"),
        ("venue: {type: text, section: info}",
         "venue: {type: text, section: info, renamed_from: note}",
         "21:42 entities.session.fields.venue.renamed_from: 'note' is still a field"),
    ],
)  # fmt: skip
def test_problems_point_at_the_line(problems: Problems, old: str, new: str, expected: str) -> None:
    assert old in BASE
    found = problems(BASE.replace(old, new))
    assert any(p.startswith(expected) for p in found), found


def test_grandchildren_are_not_allowed(problems: Problems) -> None:
    rep = (
        "  rep:\n    label: Rep\n    tab: Reps\n    key: [date, set_no, rep_no]\n"
        "    parent: {entity: set, key: [date, set_no]}\n"
        "    fields:\n      date: {type: date}\n      set_no: {type: integer}\n"
        "      rep_no: {type: integer}\n"
    )
    found = problems(BASE + rep)
    assert found == ["37:14 entities.rep.parent.entity: 'set' is itself a child (one level only)"]


def test_a_bad_template_field_is_reported_once(problems: Problems) -> None:
    text = BASE.replace("fingers: {type: scale, scale: s10,", "fingers: {type: scale, scale: s11,")
    text = text.replace(
        "      note: {type: text, section: body}",
        "      note: {type: text, section: body}\n      post_: {template: soreness, section: body}",
    )
    assert problems(text) == [
        "9:28 templates.soreness.fingers.scale: unknown scale 's11' (known: s10)"
    ]


def test_two_fields_cannot_be_renamed_from_the_same_key(problems: Problems) -> None:
    text = BASE.replace(
        "venue: {type: text, section: info}",
        "venue: {type: text, section: info, renamed_from: place}\n"
        "      gym: {type: text, section: info, renamed_from: place}",
    )
    assert problems(text) == [
        "22:7 entities.session.fields.gym: 'venue' is already renamed from 'place'"
    ]


def _with_visible_if(condition: str) -> str:
    return BASE.replace(
        "venue: {type: text, section: info}",
        f'venue: {{type: text, section: info, visible_if: "{condition}"}}',
    )


def test_visible_if_can_use_the_other_fields(load: LoadYaml) -> None:
    module = load(_with_visible_if("session_type == 'Hangs' and notnull(pre_fingers)"))
    assert module.entities["session"].fields["venue"].visible_if is not None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ("sesion_type == 'Hangs'", "unknown field 'sesion_type' (did you mean 'session_type'?)"),
        ("session_type == 'Hang'", "'Hang' is not a choice of 'session_type' (choices: Hangs"),
        ("pre_fingers + 1", "visible_if must be a condition (yes/no), not number"),
        ("notnull(venue)", "visible_if cannot depend on its own field"),
        ("session_type ==", "invalid expression: invalid syntax (at character 16)"),
    ],
)  # fmt: skip
def test_visible_if_problems(problems: Problems, condition: str, message: str) -> None:
    found = problems(_with_visible_if(condition))
    assert len(found) == 1
    assert found[0].startswith(f"21:42 entities.session.fields.venue.visible_if: {message}")
