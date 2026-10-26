# SPDX-License-Identifier: GPL-3.0-or-later
"""The sheet formulas give what the app computes, recalculated by LibreOffice (03 §2.2b, D-053).

Fictional workbooks with random rows (blanks included) from fixed seeds; skipped when no working
LibreOffice is found (see `parity.py`).
"""

import os
import tempfile
from pathlib import Path

import pytest
from conftest import LoadYaml
from formula_module import MODULE
from parity import generate, mismatches, soffice, work_dir

from climblog.modules import Module, load_module

DRAFTS = Path(__file__).parent.parent / "design" / "modules"

# CI sets CLIMBLOG_REQUIRE_SOFFICE, so a broken LibreOffice there fails instead of skipping.
REQUIRED = bool(os.environ.get("CLIMBLOG_REQUIRE_SOFFICE"))
pytestmark = pytest.mark.skipif(soffice() is None and not REQUIRED, reason="no working LibreOffice")


def check(module: Module, seed: int) -> list[str]:
    command = soffice()
    assert command is not None, "CLIMBLOG_REQUIRE_SOFFICE is set but no LibreOffice works"
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        return mismatches(module, generate(module, Path(folder), seed), command)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_construct_matches_the_app(load: LoadYaml, seed: int) -> None:
    assert check(load(MODULE), seed) == []


@pytest.mark.parametrize("draft", ["finger-strength", "journal"])
@pytest.mark.parametrize("seed", [1, 2])
def test_drafts_match_the_app(draft: str, seed: int) -> None:
    assert check(load_module(DRAFTS / f"{draft}.yaml"), seed) == []
