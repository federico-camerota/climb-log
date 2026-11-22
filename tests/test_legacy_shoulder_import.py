# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001  (prescriptions use the multiplication sign)
"""Importing the legacy shoulder tracker, and its parity report, on fictional workbooks (D-116)."""

import datetime as dt
import re
import shutil
import tempfile
from pathlib import Path

import openpyxl
import pytest
from fictional_shoulder import START, LegacyShoulder, legacy_shoulder
from parity import recalculate, soffice, work_dir
from typer.testing import CliRunner

from climblog import cli
from climblog.importers.legacy import ImportRefused, LegacyLayoutError
from climblog.importers.legacy_shoulder import (
    ORDER_KNOWN,
    WEEK_KNOWN,
    LegacyDataError,
    import_legacy_shoulder,
    parity_shoulder,
    read_legacy_shoulder,
)
from climblog.modules import Module, load_module
from climblog.storage import XlsxBackend, load_data

SHOULDER = Path(__file__).parent.parent / "modules" / "shoulder.yaml"
runner = CliRunner()


@pytest.fixture(scope="module")
def module() -> Module:
    return load_module(SHOULDER)


@pytest.fixture
def legacy(tmp_path: Path) -> LegacyShoulder:
    return legacy_shoulder(tmp_path / "Shoulder_Program_Tracker_Fixed.xlsx", seed=1)


def edit(path: Path, tab: str, cell: str, value: str | dt.date | None) -> None:
    book = openpyxl.load_workbook(path)
    book[tab][cell] = value
    book.save(path)


# ---- Reading ----


def test_read_the_legacy_tracker(module: Module, legacy: LegacyShoulder) -> None:
    data = read_legacy_shoulder(legacy.path, module)
    assert (data.start, data.start_week) == (START, "2026-W37")
    assert (data.count("checkin"), data.count("exercise_log"), data.count("retest")) == (
        legacy.checkins,
        legacy.exercise_rows,
        legacy.retests,
    )
    assert [r["id"] for r in data.reference["exercises"]][:4] == ["P1", "P2", "P3", "A1"]
    assert data.reference["exercises"][3]["w4"] == "2×8"  # read from the "W4*" column
    assert len(data.skipped) == legacy.skipped and len(data.unread) == legacy.unread
    assert all("not a valid value" in line for line in data.unread)  # places, never content
    assert "Session Log row" in data.skipped[0] and "no date" in data.skipped[0]


def test_the_late_session_keeps_its_plan_week(module: Module, legacy: LegacyShoulder) -> None:
    data = read_legacy_shoulder(legacy.path, module)
    late = [
        r.values for r in data.records if r.entity == "exercise_log" and r.values["plan_week"] == 3
    ]
    assert {r["exercise_id"] for r in late} >= {"B1", "B7"}
    assert all(
        r["date"] >= START + dt.timedelta(days=21)  # type: ignore[operator]
        for r in late
        if str(r["exercise_id"]).startswith("B")
    )


def test_the_measures_and_retest_dates(module: Module, legacy: LegacyShoulder) -> None:
    data = read_legacy_shoulder(legacy.path, module)
    measures = data.reference["retest_measures"]
    assert [m["id"] for m in measures][:3] == ["M1", "M2", "M3"]
    assert [m.get("value_type") for m in measures[:3]] == ["number", "bool", "bool"]
    assert measures[5]["value_type"] == "choice" and "Did not stop" in str(measures[5]["choices"])
    dates = {
        (r.values["checkpoint"], r.values["date"]) for r in data.records if r.entity == "retest"
    }
    assert dates == {("Start", START), ("End W4", START + dt.timedelta(days=27))}
    assert data.notes  # the dates are said in the report


@pytest.mark.parametrize(
    ("tab", "cell", "value", "message"),
    [
        ("Check-in", "Q4", "Review", "Check-in!Q4 is 'Review'"),
        ("Plan", "G4", "W4", "Plan!G4 is 'W4', expected 'W4*'"),
        ("Start Here", "A6", "Start", "Start Here!A6 is 'Start'"),
    ],
)
def test_another_layout_is_refused(
    module: Module, legacy: LegacyShoulder, tab: str, cell: str, value: str, message: str
) -> None:
    edit(legacy.path, tab, cell, value)
    with pytest.raises(LegacyLayoutError, match=re.escape(message)):
        read_legacy_shoulder(legacy.path, module)


def test_a_missing_tab_or_start_date(module: Module, legacy: LegacyShoulder) -> None:
    edit(legacy.path, "Start Here", "C6", None)
    with pytest.raises(LegacyLayoutError, match="holds no start date"):
        read_legacy_shoulder(legacy.path, module)
    book = openpyxl.load_workbook(legacy.path)
    del book["Retests"]
    book.save(legacy.path)
    with pytest.raises(LegacyLayoutError, match="no tab 'Retests': not a legacy shoulder tracker"):
        read_legacy_shoulder(legacy.path, module)


def test_a_date_twice_refuses_the_import(module: Module, legacy: LegacyShoulder) -> None:
    edit(legacy.path, "Check-in", "A6", START + dt.timedelta(days=1))
    edit(legacy.path, "Check-in", "A7", START + dt.timedelta(days=1))
    with pytest.raises(LegacyDataError, match="rows 6 and 7 have the same date"):
        read_legacy_shoulder(legacy.path, module)


# ---- Importing ----


def test_import_into_a_new_workbook(module: Module, legacy: LegacyShoulder, tmp_path: Path) -> None:
    repo = XlsxBackend(tmp_path / "shoulder.xlsx")
    report = import_legacy_shoulder(legacy.path, module, repo)
    assert report.start_week == "2026-W37"
    assert report.counts == {
        "exercises": 17,
        "retest_measures": 14,
        "checkin": legacy.checkins,
        "exercise_log": legacy.exercise_rows,
        "retest": legacy.retests,
    }
    data = load_data(module, repo)
    assert data.issues == []
    assert [r.start_week for r in data.runs.runs] == ["2026-W37"]
    assert len(data.entities["checkin"].records) == legacy.checkins
    with pytest.raises(ImportRefused, match="already holds"):
        import_legacy_shoulder(legacy.path, module, repo)


def test_a_workbook_never_computed_has_no_parity(module: Module, legacy: LegacyShoulder) -> None:
    assert not read_legacy_shoulder(legacy.path, module).computed


@pytest.mark.skipif(soffice() is None, reason="no working LibreOffice")
@pytest.mark.parametrize("out_of_order", [False, True])
def test_parity_with_the_legacy_formulas(module: Module, out_of_order: bool) -> None:
    """The legacy formulas, computed by LibreOffice, against the app (only known differences)."""
    command = soffice()
    assert command is not None
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        written = legacy_shoulder(Path(folder) / "legacy.xlsx", seed=4, out_of_order=out_of_order)
        recalculate(command, written.path)
        data = read_legacy_shoulder(Path(folder) / "recalculated" / "legacy.xlsx", module)
    columns = {c.field: c for c in parity_shoulder(data, module)}
    assert data.computed
    assert {f: c.compared > 0 for f, c in columns.items()} == dict.fromkeys(
        ["prescribed", "week", "status", "action", "review_flag"], True
    )
    unexpected = [
        (c.field, c.mismatches[:2]) for c in columns.values() if c.mismatches and not c.known
    ]
    assert unexpected == []
    assert columns["week"].known == WEEK_KNOWN and columns["week"].mismatches  # the Mondays
    assert all(d.weekday() == 0 for d, _, _ in columns["week"].mismatches)
    assert (columns["review_flag"].known == ORDER_KNOWN) is out_of_order


# ---- The command ----


@pytest.fixture
def config(tmp_path: Path) -> Path:
    file = tmp_path / "config.toml"
    file.write_text(
        f'[modules.shoulder]\ndefinition = "{SHOULDER}"\nworkbook = "shoulder.xlsx"\n'
        '[backups]\nfolder = "backups"\n',
        encoding="utf-8",
    )
    return file


def test_import_legacy_command(legacy: LegacyShoulder, config: Path) -> None:
    args = ["import-legacy", "--shoulder", str(legacy.path), "--config", str(config)]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == f"imported into {config.parent / 'shoulder.xlsx'}"
    assert lines[1].startswith("  run 1 from 2026-W37; 17 exercises, 14 retest measures, ")
    assert "retests dated from the program weeks" in result.output
    assert "holds no computed values" in result.output
    again = runner.invoke(cli.app, args)
    assert again.exit_code == 1 and "already holds" in again.output


def test_dry_run_writes_nothing(legacy: LegacyShoulder, config: Path) -> None:
    args = ["import-legacy", "--shoulder", str(legacy.path), "--config", str(config), "--dry-run"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert result.output.startswith("read (nothing written):\n  run 1 from 2026-W37")
    assert not (config.parent / "shoulder.xlsx").exists()


def test_one_legacy_workbook_at_a_time(legacy: LegacyShoulder, config: Path) -> None:
    both = ["--journal", str(legacy.path), "--shoulder", str(legacy.path)]
    for args in ([], both):
        result = runner.invoke(cli.app, ["import-legacy", *args, "--config", str(config)])
        assert result.exit_code == 1 and "give one legacy workbook" in result.output


@pytest.mark.skipif(soffice() is None, reason="no working LibreOffice")
def test_a_difference_fails_the_command(config: Path) -> None:
    command = soffice()
    assert command is not None
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        written = legacy_shoulder(Path(folder) / "legacy.xlsx", seed=4)
        recalculate(command, written.path)
        computed = Path(folder) / "recalculated" / "legacy.xlsx"
        edit(computed, "Check-in", "N5", "PURPLE")  # a status the rules never give
        copy = config.parent / "legacy.xlsx"
        shutil.copy(computed, copy)
    args = ["import-legacy", "--shoulder", str(copy), "--config", str(config), "--dry-run"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 1
    assert "DIFFERS: checkin.status" in result.output
