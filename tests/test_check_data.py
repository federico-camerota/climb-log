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
        "snapshots/journal.json.gz",  # an app snapshot: the journal's records
        "build/demo/snapshots/journal.json.gz",
        "client_secret_123.apps.googleusercontent.com.json",  # secrets: anywhere
        "tests/fixtures/google-token.json",
        ".env",
        "frontend/.env.local",
    ],
)
def test_personal_data_outside_allowed_dirs_is_rejected(path: str) -> None:
    assert check_data.is_forbidden(path)


@pytest.mark.parametrize(
    "path",
    [
        "design/mockups/mockup-climbing-journal.xlsx",
        "tests/fixtures/legacy/journal.xlsx",
        "tests/fixtures/sessions.csv",
        "tests/fixtures/snapshot.json.gz",  # a fictional snapshot fixture
        "frontend/src/api/schema.json",
        "package.json",
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
