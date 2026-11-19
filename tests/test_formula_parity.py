# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet formulas give what the app computes, recalculated by LibreOffice (03 §2.2b, D-053).

Fictional workbooks with random rows (blanks included) from fixed seeds; skipped when no working
LibreOffice is found (see `parity.py`).
"""

import datetime as dt
import os
import tempfile
from pathlib import Path

import pytest
from conftest import LoadYaml
from formula_module import (
    MODULE,
    PROGRAM_MODULE,
    WEEK_MODULE,
    WEEK_PROGRAM_MODULE,
    WINDOW_MODULE,
)
from parity import START, generate, mismatches, soffice, work_dir

from climblog.modules import Module, load_module

ROOT = Path(__file__).parent.parent
DRAFTS = ROOT / "design" / "modules"

# CLIMBLOG_REQUIRE_SOFFICE makes a missing or broken LibreOffice a failure instead of a skip.
REQUIRED = bool(os.environ.get("CLIMBLOG_REQUIRE_SOFFICE"))
pytestmark = pytest.mark.skipif(soffice() is None and not REQUIRED, reason="no working LibreOffice")


def check(module: Module, seed: int, start: dt.date | None = None) -> list[str]:
    command = soffice()
    assert command is not None, "CLIMBLOG_REQUIRE_SOFFICE is set but no LibreOffice works"
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        generated = generate(module, Path(folder), seed, start=start or START)
        return mismatches(module, generated, command)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_construct_matches_the_app(load: LoadYaml, seed: int) -> None:
    assert check(load(MODULE), seed) == []


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_last_until_and_window_match_the_app(load: LoadYaml, seed: int) -> None:
    assert check(load(WINDOW_MODULE), seed) == []


@pytest.mark.parametrize("seed", [1, 2])
def test_program_weeks_match_the_app(load: LoadYaml, seed: int) -> None:
    assert check(load(PROGRAM_MODULE), seed) == []


@pytest.mark.parametrize("text", [WEEK_MODULE, WEEK_PROGRAM_MODULE], ids=["plain", "program"])
@pytest.mark.parametrize("seed", [1, 2])
def test_records_dated_by_a_week_match_the_app(load: LoadYaml, text: str, seed: int) -> None:
    assert check(load(text), seed) == []


@pytest.mark.parametrize(
    "file", [ROOT / "modules" / "finger-strength.yaml", ROOT / "modules" / "journal.yaml"], ids=str
)
@pytest.mark.parametrize("seed", [1, 2])
def test_modules_match_the_app(file: Path, seed: int) -> None:
    assert check(load_module(file), seed) == []


@pytest.mark.parametrize("seed", [1, 2])
def test_the_journal_matches_the_app_across_the_start_of_illness(seed: int) -> None:
    # 40 records from 1 Nov: some before 23 Nov (illness left out), most after (D-111)
    module = load_module(ROOT / "modules" / "journal.yaml")
    assert check(module, seed, start=dt.date(2026, 11, 1)) == []
