# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema sync on .xlsx: what is particular to the file (03 §3, 04 §1, D-052): styles,
dropdowns and colour rules, named settings, lock files, backups, the mock-up.

What every backend must do is in `test_backend_sync.py`.
"""

import datetime as dt
import shutil
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from conftest import LoadYaml
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet
from workbooks import SYNC_MODULE, existing_tabs, write_workbook

from climblog.modules import Module, load_module
from climblog.storage import (
    Backups,
    WorkbookLocked,
    XlsxBackend,
    check_schema,
    load_data,
    sync_module,
)

D20 = dt.datetime(2026, 10, 20)


@pytest.fixture
def module(load: LoadYaml) -> Module:
    return load(SYNC_MODULE)


def open_sheet(path: Path, name: str) -> Worksheet:
    sheet = openpyxl.load_workbook(path)[name]
    assert isinstance(sheet, Worksheet)
    return sheet


def validations(sheet: Worksheet) -> dict[str, tuple[Any, ...]]:
    return {
        str(v.sqref): (v.type, v.operator, v.formula1, v.formula2, v.errorStyle)
        for v in sheet.data_validations.dataValidation
    }


def formats(sheet: Worksheet) -> dict[str, list[str]]:
    return {str(f.sqref): [r.type for r in f.rules] for f in sheet.conditional_formatting}


# ---- A new workbook ----


@pytest.fixture
def created(module: Module, tmp_path: Path) -> Path:
    path = tmp_path / "data" / "test.xlsx"
    assert sync_module(module, XlsxBackend(path)) == [
        "created the workbook",
        "created tab 'Pre'",
        "created tab 'Post'",
        "created tab '_settings'",
        "created tab '_meta'",
    ]
    return path


def test_new_header_rows_are_styled(created: Path) -> None:
    pre = open_sheet(created, "Pre")
    assert [pre.cell(1, c).fill.fgColor.rgb for c in (1, 2, 4, 5)] == [
        *("00BDD7EE", "00C6E0B4", "00BFBFBF", "00E7E6E6"),  # key, pre, AUTOMATIC, system
    ]
    assert pre.column_dimensions["D"].hidden  # the key column
    assert pre.cell(2, 2).fill.fgColor.rgb == "00E2EFDA"
    assert pre.cell(1, 1).font.b
    assert (pre.cell(2, 1).font.name, pre.cell(2, 1).font.sz) == ("Roboto Mono", 9)
    assert pre.cell(2, 1).border.bottom.style == "medium"
    assert pre.freeze_panes == "C3"
    assert pre["A2"].comment is not None and "Do not edit" in pre["A2"].comment.text
    assert pre.column_dimensions["A"].width == 11
    post = open_sheet(created, "Post")
    assert post.cell(1, 2).fill.fgColor.rgb == "00F8CBAD"  # post amber


def test_new_tabs_have_validation_and_scale_colours(created: Path) -> None:
    pre = open_sheet(created, "Pre")
    ten = '"' + ",".join(str(n) for n in range(1, 11)) + '"'
    assert validations(pre) == {
        "A3:A1048576": ("date", "greaterThanOrEqual", "DATE(1990,1,1)", None, None),
        "B3:B1048576": ("list", None, ten, None, None),
        "C3:C1048576": ("list", None, '"Climb,Board"', None, None),
    }
    assert formats(pre) == {"B3:B1048576": ["colorScale"]}
    rule = next(iter(pre.conditional_formatting)).rules[0]
    assert [c.rgb for c in rule.colorScale.color] == ["0063BE7B", "00FFEB84", "00F8696B"]
    # Fixed ends on the scale's range: a single value is coloured by what it is (mock-up).
    assert [(v.type, v.val) for v in rule.colorScale.cfvo] == [
        ("num", 1),
        ("num", 5.5),
        ("num", 10),
    ]
    post = open_sheet(created, "Post")
    rule = next(iter(post.conditional_formatting)).rules[0]
    assert [c.rgb for c in rule.colorScale.color] == ["00F8696B", "00FFEB84", "0063BE7B"]
    assert post.column_dimensions["C"].number_format == "@"  # notes typed later stay text


def test_settings_are_named_and_text_stays_text(created: Path) -> None:
    workbook = openpyxl.load_workbook(created)
    assert workbook["_settings"]["B5"].data_type == "s"  # `=keep going`: text, not a formula
    names = {k: v.attr_text for k, v in workbook.defined_names.items()}
    assert names["low_max"] == "'_settings'!$B$2"
    assert names["motto"] == "'_settings'!$B$5"


def test_syncing_again_keeps_the_rules(module: Module, created: Path) -> None:
    before = openpyxl.load_workbook(created)
    sync_module(module, XlsxBackend(created))
    after = openpyxl.load_workbook(created)
    for name in ("Pre", "Post", "_settings"):
        assert validations(before[name]) == validations(after[name])
        assert formats(before[name]) == formats(after[name])


def test_a_new_workbook_is_refused_while_a_lock_file_exists(module: Module, tmp_path: Path) -> None:
    (tmp_path / ".~lock.test.xlsx#").touch()
    with pytest.raises(WorkbookLocked):
        sync_module(module, XlsxBackend(tmp_path / "test.xlsx"))
    assert not (tmp_path / "test.xlsx").exists()


# ---- An existing workbook ----


@pytest.fixture
def existing(tmp_path: Path) -> Path:
    """Hand-made tabs: Pre without `kind` and system columns, Post still with `feel`."""
    path = write_workbook(tmp_path / "test.xlsx", existing_tabs())
    workbook = openpyxl.load_workbook(path)
    pre = workbook["Pre"]
    stale = DataValidation("list", formula1='"0,1"')  # an old dropdown on `pain`
    stale.add("B3:B202")
    other = DataValidation("list", formula1='"sunny,rain"')  # one of mine on `weather`
    other.add("D3:D202")
    both = DataValidation("whole")  # spans `pain`, `auto:status` and `weather`
    both.add("B3:D10")
    for rule in (stale, other, both):
        pre.add_data_validation(rule)
    red = PatternFill("solid", fgColor="FF0000")
    low = CellIsRule(operator="equal", formula=['"LOW"'], fill=red)  # type: ignore[no-untyped-call]
    one = CellIsRule(operator="equal", formula=["1"], fill=red)  # type: ignore[no-untyped-call]
    pre.conditional_formatting.add("C3:C202", low)  # a status colour on a formula column
    pre.conditional_formatting.add("B3:B202", one)  # an old colour rule on `pain`
    workbook.save(path)
    return path


def test_validation_is_rewritten_on_module_columns_only(module: Module, existing: Path) -> None:
    sync_module(module, XlsxBackend(existing))
    pre = open_sheet(existing, "Pre")
    rules = validations(pre)
    assert rules["D3:D202"][2] == '"sunny,rain"'  # on an unknown column: kept
    assert "B3:B202" not in rules  # the stale dropdown on `pain` is gone
    assert rules["B3:B1048576"][0] == "list"
    assert rules["C3:C10 D3:D10"][0] == "whole"  # split: the part on `pain` is gone
    assert formats(pre) == {"C3:C202": ["cellIs"], "B3:B1048576": ["colorScale"]}


def test_existing_settings_get_their_names(module: Module, existing: Path) -> None:
    sync_module(module, XlsxBackend(existing))
    workbook = openpyxl.load_workbook(existing)
    names = {k: v.attr_text for k, v in workbook.defined_names.items()}
    assert names["low_max"] == "'_settings'!$B$3"


def test_a_backup_is_taken_first(module: Module, existing: Path, tmp_path: Path) -> None:
    before = existing.read_bytes()
    sync_module(module, XlsxBackend(existing, backups=Backups(tmp_path / "backups")))
    (copy,) = (tmp_path / "backups").iterdir()
    assert copy.read_bytes() == before


def test_the_finger_strength_mockup_keeps_its_data(tmp_path: Path) -> None:
    module = load_module(Path("modules/finger-strength.yaml"))
    path = Path(shutil.copy("design/mockups/mockup-finger-strength.xlsx", tmp_path))
    before = openpyxl.load_workbook(path)
    repo = XlsxBackend(path)
    records = load_data(module, repo).entities
    done = sync_module(module, repo)
    assert done[:2] == [
        "Sessions: added column 'auto:curl_volume'",
        "Curl sets: added column 'auto:lr_imbalance_pct'",
    ]
    # The mock-up's hand-made formulas are replaced by the compiled ones, all of a column.
    assert "Sessions: new formula in 'auto:readiness'" in done
    assert not any("changed cells" in line for line in done)
    after = openpyxl.load_workbook(path)
    for name in ("Sessions", "Hang sets", "Curl sets"):
        old, new = before[name], after[name]
        for column in range(1, old.max_column + 1):
            key = old.cell(2, column).value
            if isinstance(key, str) and not key.startswith("auto:"):
                assert [c.value for c in old[get_column_letter(column)]] == [
                    c.value for c in new[get_column_letter(column)]
                ][: old.max_row], key
    assert load_data(module, repo).entities == records
    assert check_schema(module, repo) == []
    assert sync_module(module, repo) == []  # a second sync has nothing to do


def _status_rules(sheet: Worksheet) -> list[str]:
    return [str(f.sqref) for f in sheet.conditional_formatting if f.rules[0].type == "cellIs"]


def test_validation_rules_for_other_field_kinds(load: LoadYaml, tmp_path: Path) -> None:
    long = [f"Choice number {n:02}" for n in range(20)]  # over Excel's 255 characters
    module = load(
        f"""\
        module: test_sync
        name: Test sync
        version: 1
        kind: journal
        entities:
          fall:
            label: Fall
            tab: Falls
            key: [date]
            fields:
              date: {{type: date}}
              at: {{type: time}}
              weight: {{type: number, max: 200}}
              grip: {{type: choice, choices: [Crimp, Open], allow_other: true}}
              many: {{type: choice, choices: {long}}}
              note: {{type: text}}
        """
    )
    path = write_workbook(tmp_path / "test.xlsx", {"Falls": [["Date"], ["date"], [D20]]})
    sync_module(module, XlsxBackend(path))
    falls = open_sheet(path, "Falls")
    assert validations(falls) == {
        "A3:A1048576": ("date", "greaterThanOrEqual", "DATE(1990,1,1)", None, None),
        "B3:B1048576": ("time", "between", "0", "0.999988", None),
        "C3:C1048576": ("decimal", "lessThanOrEqual", "200", None, None),
        "D3:D1048576": ("list", None, '"Crimp,Open"', None, "warning"),
    }
    assert falls["F3"].number_format == "@"  # a column added next to data rows: text there too
