# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

import check_data


@pytest.mark.parametrize(
    "path",
    [
        "Climbing_Journal.xlsx",
        "data/export.csv",
        "tests/journal.xlsx",
        "design/journal.ods",
        "backend/climblog/old.XLSM",
        "design/mockups-old/real.xlsx",
        "tests/fixtures/../real.xlsx",
    ],
)
def test_spreadsheets_outside_allowed_dirs_are_rejected(path: str) -> None:
    assert check_data.is_forbidden(path)


@pytest.mark.parametrize(
    "path",
    [
        "design/mockups/mockup-climbing-journal.xlsx",
        "tests/fixtures/legacy/journal.xlsx",
        "tests/fixtures/sessions.csv",
        "backend/climblog/main.py",
        "README.md",
    ],
)
def test_allowed_paths_pass(path: str) -> None:
    assert not check_data.is_forbidden(path)


def test_main_reports_each_forbidden_path(capsys: pytest.CaptureFixture[str]) -> None:
    code = check_data.main(["a.xlsx", "design/mockups/ok.xlsx", "b.csv"])
    out = capsys.readouterr().out
    assert code == 1
    assert "a.xlsx:" in out
    assert "b.csv:" in out
    assert "ok.xlsx" not in out


def test_main_passes_when_nothing_is_forbidden() -> None:
    assert check_data.main(["README.md"]) == 0
