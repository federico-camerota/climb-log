# SPDX-License-Identifier: GPL-3.0-or-later
"""Derived fields compiled to sheet formulas: columns, placement, formula text (D-053).

Whether the formulas give what the app computes is `test_formula_parity.py` (LibreOffice).
"""

from pathlib import Path

import pytest
from conftest import LoadYaml
from formula_module import MODULE
from typer.testing import CliRunner

from climblog import cli
from climblog.modules import Module
from climblog.modules.formulas import (
    GOOGLE,
    XLSX,
    AppOnly,
    FormulaColumn,
    Template,
    compile_formulas,
    default_columns,
    formula_columns,
)


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(MODULE)


def formulas(module: Module, dialect: object = XLSX) -> dict[str, str]:
    """Each column's formula for row 3, by `tab!key`."""
    compiled = compile_formulas(module, default_columns(module), dialect)  # type: ignore[arg-type]
    return {f"{tab}!{key}": template.at(3) for (tab, key), template in compiled.items()}


def columns(module: Module) -> dict[str, FormulaColumn]:
    placed, _ = formula_columns(module)
    return {f"{c.tab}!{c.key}": c for c in placed}


# ---- Columns ----


def test_key_columns_on_split_parent_and_child_tabs(module: Module) -> None:
    keys = [name for name, c in columns(module).items() if c.key == "auto:_key"]
    assert keys == ["Session!auto:_key", "Body!auto:_key", "Sets!auto:_key"]
    assert all(columns(module)[k].hidden for k in keys)
    assert "Rest!auto:_key" not in columns(module)  # nothing matches rest days


def test_a_derived_field_sits_on_the_tab_of_what_it_reads(module: Module) -> None:
    placed = columns(module)
    assert placed["Body!auto:sore"].tab == "Body"  # Body fields only
    assert placed["Session!auto:load"].tab == "Session"
    assert "Session!auto:overall" in placed  # reads Body and Session: the anchor tab
    assert "Sets!auto:volume" in placed


def test_labels_formats_and_levels(module: Module) -> None:
    placed = columns(module)
    assert placed["Body!auto:sore"].label == "Sore"
    assert placed["Body!auto:sore"].number_format == "0.0"
    assert placed["Body!auto:sore_avg_filled"].number_format == "0.00"
    assert placed["Session!auto:gap"].number_format == "0"  # a date difference, not a date
    assert placed["Session!auto:n_present"].number_format == "0"
    assert placed["Session!auto:load"].number_format == "General"
    assert placed["Session!auto:overall"].levels == ("GOOD", "WATCH", "LOW")
    assert placed["Session!auto:plus_one"].hand_written
    assert not placed["Session!auto:load"].hand_written


def test_app_only_entries_are_listed(module: Module) -> None:
    _, app_only = formula_columns(module)
    assert [str(a) for a in app_only] == [
        "session.doubled: app only (sheet_formula: false)",
        "session.from_app_only: app only (it reads 'doubled', which is app only)",
        "session.prev_app_only: app only (it reads 'doubled', which is app only)",
        "session.top_app_only: app only (it reads set.heavy, which is app only)",
        "set.heavy: app only (sheet_formula: false)",
    ]
    assert app_only[0] == AppOnly("session", "doubled", "sheet_formula: false")


def test_default_columns_follow_schema_sync(module: Module) -> None:
    rest = default_columns(module)["Rest"]
    assert list(rest) == [
        *("date", "sleep", "start", "updated_at", "deleted"),
        *("auto:first_start", "auto:since_climb", "auto:last_effort"),
    ]


# ---- Formulas ----


def test_blank_inputs_give_blank_results(module: Module) -> None:
    f = formulas(module)
    assert f["Session!auto:load"] == '=IF(A3="","",IF(OR(D3="",E3=""),"",D3*E3))'
    assert f["Session!auto:per_min"] == '=IF(A3="","",IF(OR(OR(E3="",D3=""),D3=0),"",E3/D3))'
    assert f["Session!auto:neg"] == '=IF(A3="","",IF(E3="","",-E3))'
    assert f["Session!auto:day"] == (
        '=IF(A3="","",CHOOSE(WEEKDAY(A3,2),"Mon","Tue","Wed","Thu","Fri","Sat","Sun"))'
    )


def test_aggregates_of_cells_use_the_native_functions(load: LoadYaml) -> None:
    module = load(
        """\
        module: test_formulas
        name: Test formulas
        version: 1
        kind: journal
        scales:
          s10: {min: 1, max: 10, direction: lower_better}
        entities:
          rest:
            label: Rest day
            tab: Rest
            key: [date]
            fields:
              date: {type: date}
              a: {type: scale, scale: s10}
              b: {type: scale, scale: s10}
            derived:
              score: "round(11 - mean(a, b), 1)"
              worst: "max(a, b)"
              both: "all_present(a, b)"
              n: "count(a, b)"
        """
    )
    f = formulas(module)
    assert f["Rest!auto:score"] == '=IF(A3="","",IF(COUNT(B3,C3)=0,"",ROUND(11-AVERAGE(B3,C3),1)))'
    assert f["Rest!auto:worst"] == '=IF(A3="","",IF(COUNT(B3,C3)=0,"",MAX(B3,C3)))'
    assert f["Rest!auto:both"] == '=IF(A3="","",COUNT(B3,C3)=2)'
    assert f["Rest!auto:n"] == '=IF(A3="","",(B3<>"")+(C3<>""))'


def test_fields_since_a_date_count_from_that_date(module: Module) -> None:
    f = formulas(module)
    assert '(INT(A3)>=DATE(2026,9,20))*(D3<>"")' in f["Body!auto:sore"]
    assert 'OR(NOT(INT(A3)>=DATE(2026,9,20)),D3<>"")' in f["Body!auto:all_body"]


def test_missing_as_fills_blanks(module: Module) -> None:
    f = formulas(module)
    assert 'IF(C3="",10,11-C3)' in f["Body!auto:sore_filled"]
    assert "/((TRUE)+(INT(A3)>=DATE(2026,9,20))+(TRUE))" in f["Body!auto:sore_avg_filled"]


def test_yes_no_fields_and_defaults(module: Module) -> None:
    f = formulas(module)
    yes = 'OR(G3="yes",G3="y",G3="true",G3="si",G3="sì",G3="1",G3=TRUE,G3=1)'
    assert f["Session!auto:hard"] == f'=IF(A3="","",AND(AND(E3<>"",E3>=7),NOT({yes})))'
    assert 'IF(F3="",TRUE,OR(F3="yes"' in f["Session!auto:either"]  # blank warm-up = Yes
    assert f["Session!auto:label"] == '=IF(A3="","",C3&" "&IF(B3="",1,B3))'  # session_no 1


def test_comparisons_with_blanks(module: Module) -> None:
    f = formulas(module)
    assert f["Session!auto:board"] == '=IF(A3="","",C3="Board")'
    assert f["Session!auto:not_climb"] == '=IF(A3="","",NOT(C3="Climb"))'
    assert f["Body!auto:blank_equal"] == (
        '=IF(A3="","",IF(AND(C3="",E3=""),TRUE,IF(OR(C3="",E3=""),FALSE,C3=E3)))'
    )
    assert f["Session!auto:has_note"] == '=IF(A3="","",H3<>"")'


def test_statuses(module: Module) -> None:
    f = formulas(module)
    assert f["Session!auto:effort_status"] == (
        '=IF(A3="","",IF(E3<>"",IF(OR(G3="yes",G3="y",G3="true",G3="si",G3="sì",G3="1",'
        'G3=TRUE,G3=1),"LOW",IF(AND(E3<>"",E3>=8),"WATCH","GOOD")),""))'
    )
    assert '<=low_max,"LOW"' in f["Body!auto:status"]
    body = "INDEX('Body'!$Q:$Q,IFERROR(MATCH(K3,'Body'!$H:$H,0),2))"
    assert f["Session!auto:overall"] == (
        f'=IF(A3="","",IF(OR({body}="LOW",Z3="LOW"),"LOW",IF(OR({body}="WATCH",Z3="WATCH"),'
        f'"WATCH",IF(OR({body}="GOOD",Z3="GOOD"),"GOOD",""))))'
    )
    assert f["Session!auto:advice"] == (
        '=IF(A3="","",IF(AA3="LOW","Rest",IF(AA3="WATCH","Easy",IF(AA3="GOOD","Train",""))))'
    )


def test_keys(module: Module) -> None:
    f = formulas(module)
    assert f["Session!auto:_key"] == '=IF(A3="","",INT(A3)*10+IF(B3="",1,B3))'
    assert f["Sets!auto:_key"] == '=IF(A3="","",INT(A3)*10+IF(B3="",1,B3))'


def test_children_are_counted_on_the_key(module: Module) -> None:
    f = formulas(module)
    assert f["Session!auto:sets"] == '=IF(A3="","",COUNTIFS(\'Sets\'!$H:$H,K3,\'Sets\'!$G:$G,""))'
    numbers = "COUNTIFS('Sets'!$H:$H,K3,'Sets'!$G:$G,\"\",'Sets'!$D:$D,\">-1E+307\")"
    assert f["Session!auto:top"] == (
        f'=IF(A3="","",IF({numbers}=0,"",'
        "_xlfn.MAXIFS('Sets'!$D:$D,'Sets'!$H:$H,K3,'Sets'!$G:$G,\"\")))"
    )
    assert "SUMIFS('Sets'!$I:$I" in f["Session!auto:total"]  # the children's derived volume
    assert "AVERAGEIFS(" in f["Session!auto:avg_kg"]
    assert "_xlfn.MINIFS(" in f["Session!auto:low_kg"]
    assert f["Session!auto:n_kg"] == f'=IF(A3="","",{numbers})'


def test_prev_parent_and_last_look_rows_up(module: Module) -> None:
    f = formulas(module)
    latest = "_xlfn.MAXIFS('Session'!$K:$K,'Session'!$K:$K,\"<\"&K3,'Session'!$J:$J,\"\")"
    assert f"MATCH({latest},'Session'!$K:$K,0)" in f["Session!auto:prev_load"]
    assert "INDEX('Session'!$D:$D,MATCH(H3,'Session'!$K:$K,0))" in f["Sets!auto:long"]
    last = "_xlfn.MAXIFS('Session'!$K:$K,'Session'!$A:$A,\"<\"&INT(A3),'Session'!$J:$J,\"\")"
    assert f"INDEX('Session'!$E:$E,MATCH({last},'Session'!$K:$K,0))" in f["Rest!auto:last_effort"]


def test_hand_written_formulas(module: Module) -> None:
    f = formulas(module)
    assert f["Session!auto:plus_one"] == "=E3+1"
    body = "INDEX('Body'!$C:$C,MATCH(K3,'Body'!$H:$H,0))"
    assert f["Session!auto:plus_two"] == f'=L3+IFERROR(IF({body}="","",{body}),"")'


def test_more_value_kinds(module: Module) -> None:
    f = formulas(module)
    yes = ",".join(
        f"strict={t}" for t in ('"yes"', '"y"', '"true"', '"si"', '"sì"', '"1"', "TRUE", "1")
    )
    assert f["Session!auto:strict_hard"] == f'=IF(A3="","",AND((S3=TRUE),OR({yes})))'
    assert f["Session!auto:flagged"].endswith(",FALSE))")
    assert f["Session!auto:half"] == '=IF(A3="","",IF(E3="","",E3/2))'  # no test for /2
    assert f["Session!auto:five"] == '=IF(A3="","",AND(E3<>"",E3=5))'
    assert (
        f["Session!auto:level"] == '=IF(A3="","",IF(E3="","",IF(E3<=3,"LOW",IF(E3<=6,"WATCH",""))))'
    )
    assert "11-C3,0)" in f["Body!auto:sore_flip_sum"]
    placed = columns(module)
    assert placed["Session!auto:first_day"].number_format == "DD/MM/YYYY"
    assert placed["Rest!auto:first_start"].number_format == "HH:MM"


def test_a_bad_placeholder_makes_the_entry_app_only(load: LoadYaml) -> None:
    module = load(
        """        module: test_formulas
        name: Test formulas
        version: 1
        kind: journal
        entities:
          rest:
            label: Rest day
            tab: Rest
            key: [date]
            fields:
              date: {type: date}
              a: {type: number}
            derived:
              b: {expr: "a + 1", sheet_formula: "={nope}+1"}
              c: {plugin: test.c, sheet_formula: "={a}*3"}
              d: {plugin: test.d, sheet_formula: "={nope}*3"}
              e: {plugin: test.e, sheet_formula: false}
        """
    )
    placed, app_only = formula_columns(module)
    assert [str(a) for a in app_only] == [
        "rest.b: app only ({nope} is not a field or a derived value with a column)",
        "rest.d: app only (a placeholder of its sheet_formula is not a field with a column)",
        "rest.e: app only (sheet_formula: false)",
    ]
    assert [c.key for c in placed] == ["auto:c"]
    assert formulas(module)["Rest!auto:c"] == "=B3*3"


def test_google_sheets_takes_plain_function_names(module: Module) -> None:
    f = formulas(module, GOOGLE)
    assert "_xlfn." not in "".join(f.values())
    assert "MAXIFS('Sets'!$D:$D" in f["Session!auto:top"]


def test_a_column_missing_from_the_workbook_leaves_its_formula_out(module: Module) -> None:
    where = default_columns(module)
    del where["Sets"]["auto:_key"]
    compiled = compile_formulas(module, where)
    assert ("Session", "auto:sets") not in compiled  # it counts on the sets' key
    assert ("Sets", "auto:_key") not in compiled
    assert ("Session", "auto:load") in compiled
    del where["Body"]
    assert ("Session", "auto:overall") not in compile_formulas(module, where)


def test_template_rows() -> None:
    assert Template('IF(A\x00="","",B\x00*2)').at(7) == '=IF(A7="","",B7*2)'


# ---- What has no formula yet ----

APP_ONLY = """\
module: test_formulas
name: Test formulas
version: 1
kind: journal
settings:
  a1: {type: number, default: 1}
scales:
  pick: {type: ordinal, choices: [Low, High], direction: neutral}
entities:
  session:
    label: Session
    tab: Sessions
    key: [date, kind]
    fields:
      date: {type: date}
      kind: {type: choice, choices: [Hangs, Curls]}
      kg: {type: number}
    derived:
      cell_name: "kg * settings.a1"
      back_two: "prev(kg, 2)"
      by_choice: "prev(kg)"
      notes: "count(children(set).note)"
      labels: "count(children(set).tag)"
      mixed: "max(children(set).kg, kg)"
      filled: "max(children(set).kg, missing_as=0)"
      plugin_entry: {plugin: test.rule}
      reads_plugin: "plugin_entry"
  set:
    label: Set
    tab: Sets
    key: [date, set_no]
    parent: {entity: session, key: [date], fixed: {kind: Hangs}}
    fields:
      date: {type: date}
      set_no: {type: integer}
      kg: {type: number}
      note: {type: text}
    derived:
      before: "prev(kg)"
      tag: "concat(note, '!')"
  fall:
    label: Fall
    tab: Falls
    id_prefix: fall
    fields:
      id: {type: text}
      date: {type: date}
      height: {type: number}
    derived:
      higher: "height > prev(height)"
"""


def test_entries_without_a_translation_are_app_only(load: LoadYaml) -> None:
    _, app_only = formula_columns(load(APP_ONLY))
    reasons = {f"{a.entity}.{a.key}": a.reason for a in app_only}
    assert reasons == {
        "session.cell_name": "setting 'a1' looks like a cell, not a name",
        "session.back_two": "prev() further back than one record",
        "session.by_choice": "prev() with a choice in the key (the app orders it by name)",
        "session.mixed": "children(...) mixed with other values",
        "session.filled": "missing_as with children(...)",
        "session.plugin_entry": "a plugin",
        "session.reads_plugin": "needs program, reference tables or another app-only value",
        "set.before": "prev() on a child entity (its key column is its parent's)",
        "fall.higher": "rows have no natural key to be matched on",
    }


def test_odd_keys_get_no_key_column(load: LoadYaml) -> None:
    module = load(
        """\
        module: test_formulas
        name: Test formulas
        version: 1
        kind: journal
        entities:
          a:
            label: A
            tab: A
            key: [date, x, y]
            fields:
              date: {type: date}
              x: {type: integer}
              y: {type: integer}
            derived:
              p: "prev(x)"
          b:
            label: B
            tab: B
            key: [date, t]
            fields:
              date: {type: date}
              t: {type: text}
            derived:
              p: "prev(date)"
          c:
            label: C
            tab: C
            key: [date, n]
            fields:
              date: {type: date}
              n: {type: choice, choices: [a, b, c, d, e, f, g, h, i, j]}
            derived:
              p: "prev(date)"
        """
    )
    placed, app_only = formula_columns(module)
    assert [c.key for c in placed] == []
    assert [a.reason for a in app_only] == [
        "a key of more than a date and one other part",
        "the second key part is not a whole number or a closed choice",
        "the key's choice has more than 9 values",
    ]


def test_a_child_with_a_non_integer_fixed_number(load: LoadYaml) -> None:
    module = load(
        """\
        module: test_formulas
        name: Test formulas
        version: 1
        kind: journal
        entities:
          session:
            label: Session
            tab: Sessions
            key: [date, slot]
            fields:
              date: {type: date}
              slot: {type: integer}
            derived:
              n: "count(children(set))"
          set:
            label: Set
            tab: Sets
            key: [date, k]
            parent: {entity: session, key: [date], fixed: {slot: 2}}
            fields:
              date: {type: date}
              k: {type: integer}
        """
    )
    f = formulas(module)
    assert f["Sets!auto:_key"] == '=IF(A3="","",INT(A3)*10+2)'
    assert f["Sessions!auto:n"].startswith('=IF(A3="","",COUNTIFS(\'Sets\'!')


# ---- The CLI ----


def test_module_validate_lists_app_only_entries(write: object, tmp_path: Path) -> None:
    file = tmp_path / "m.yaml"
    file.write_text(APP_ONLY, encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["module", "validate", str(file)])
    assert result.exit_code == 0
    assert result.output.splitlines()[:2] == [
        f"{file}: ok",
        "  note: session.cell_name: app only (setting 'a1' looks like a cell, not a name)",
    ]


def test_counting_children_values_by_type(load: LoadYaml) -> None:
    f = formulas(load(APP_ONLY))
    assert f["Sessions!auto:notes"].endswith("'Sets'!$D:$D,\"<>\"))")  # stored text: not empty
    assert f["Sessions!auto:labels"].endswith(',"?*"))')  # a text formula: some text


def test_small_cases(load: LoadYaml) -> None:
    module = load(
        """\
        module: test_formulas
        name: Test formulas
        version: 1
        kind: journal
        scales:
          size: {type: ordinal, choices: [Small, Big], direction: neutral}
        entities:
          day:
            label: Day
            tab: Days
            key: [date]
            fields:
              date: {type: date}
              n: {type: integer, default: 1}
              x: {type: number}
            derived:
              gap: "days_between(prev(date), date)"
              six: "2 * 3"
              same: "n == 1"
              known: "notnull(n == 1)"
              ratio: "x / n"
          sized:
            label: Sized
            tab: Sized
            key: [date, size]
            fields:
              date: {type: date}
              size: {type: choice, scale: size}
            derived:
              before: "prev(date)"
          big:
            label: Big
            tab: Big
            key: [date, a, b]
            fields:
              date: {type: date}
              a: {type: integer}
              b: {type: integer}
            derived:
              parts: "count(children(part))"
          part:
            label: Part
            tab: Parts
            key: [date, a, b]
            parent: {entity: big, key: [date, a, b]}
            fields:
              date: {type: date}
              a: {type: integer}
              b: {type: integer}
          slot:
            label: Slot
            tab: Slots
            key: [date, s]
            fields:
              date: {type: date}
              s: {type: integer}
          slot_item:
            label: Slot item
            tab: Slot items
            key: [date, k]
            parent: {entity: slot, key: [date], fixed: {s: two}}
            fields:
              date: {type: date}
              k: {type: integer}
        """
    )
    f = formulas(module)
    assert f["Days!auto:_key"] == '=IF(A3="","",INT(A3)*10)'  # a date-only key
    assert f["Days!auto:six"] == '=IF(A3="","",2*3)'
    assert f["Days!auto:same"] == '=IF(A3="","",IF(B3="",1,B3)=1)'
    assert f["Days!auto:known"] == '=IF(A3="","",TRUE)'
    assert f["Days!auto:ratio"] == (
        '=IF(A3="","",IF(OR(C3="",IF(B3="",1,B3)=0),"",C3/IF(B3="",1,B3)))'
    )
    _, app_only = formula_columns(module)
    assert [str(a) for a in app_only] == [
        "sized.before: app only (prev() with a choice in the key (the app orders it by name))",
        "big.parts: app only (a key of more than a date and one other part)",
    ]
    placed = {f"{c.tab}!{c.key}" for c in formula_columns(module)[0]}
    assert "Slot items!auto:_key" not in placed  # its fixed key part is no whole number
