# SPDX-License-Identifier: GPL-3.0-or-later
"""The Summary tab's formulas against the app (D-085): a fictional journal made by schema sync,
random rows typed in, the tab's day (B3, TODAY() in use) set to a fixed day; every value and
every side-by-side cell the spreadsheet computes must be the app's (`summarize`). On LibreOffice
locally, and on Google with `CLIMBLOG_GOOGLE_LIVE=1` (fictional sheets on your account, then
trashed). Never in CI: CI has neither."""

import datetime as dt
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from backends import LIVE, GSheets
from parity import generate, generate_google, recalculate, soffice, work_dir

from climblog.config import config_path, load_config
from climblog.modules import load_module
from climblog.modules.compute import compute_module
from climblog.modules.formulas import XLSX
from climblog.modules.summary import Summarized, summarize
from climblog.storage import Repository, XlsxBackend, load_data
from climblog.storage.drift import same
from climblog.storage.google_client import RestSheetsClient
from climblog.storage.gsheets import grid_rows
from climblog.storage.layout import ReportCell, workbook_layout

JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
REQUIRED = bool(os.environ.get("CLIMBLOG_REQUIRE_SOFFICE"))
needs_soffice = pytest.mark.skipif(
    soffice() is None and not REQUIRED, reason="no working LibreOffice"
)
live = pytest.mark.skipif(not LIVE, reason="set CLIMBLOG_GOOGLE_LIVE=1 to run on Google")


def app_summary(repo: Repository, day: dt.date) -> Summarized:
    data = load_data(JOURNAL, repo)
    tables = {name: e.records for name, e in data.entities.items()}
    derived = compute_module(JOURNAL, tables, data.settings)
    full = {
        name: [{**row, **values} for row, values in zip(rows, derived[name], strict=True)]
        for name, rows in tables.items()
    }
    return summarize(JOURNAL, full, data.settings, day)


def named_cells(repo: Repository) -> list[ReportCell]:
    layout = workbook_layout(JOURNAL)
    assert layout.report is not None
    columns = {tab.name: dict(repo.read_formulas(tab.name).numbers) for tab in layout.tabs}
    return [c for c in layout.report.cells(columns, XLSX) if c.name is not None]


def mismatches(
    cells: Sequence[ReportCell], shown: Mapping[tuple[int, int], Any], app: Summarized
) -> list[str]:
    wrong = []
    for cell in cells:
        assert cell.name is not None
        field, _, n = cell.name.partition("#")
        want = app.sessions[int(n) - 1].get(field) if n else app.values.get(field)
        got = shown.get((cell.row, cell.column))
        if not same(want, got):
            wrong.append(f"{cell.name}: the sheet shows {got!r}, the app computes {want!r}")
    return wrong


def days_to_check(repo: Repository) -> list[dt.date]:
    """The last session's day, three days after, a day in the middle, and before the first."""
    data = load_data(JOURNAL, repo)
    dates: list[dt.date] = sorted(
        d for r in data.entities["session"].records if isinstance(d := r.get("date"), dt.date)
    )
    assert dates, "the generated journal has no session"
    middle = dates[len(dates) // 2]
    return [dates[-1], dates[-1] + dt.timedelta(days=3), middle, dates[0] - dt.timedelta(days=1)]


@needs_soffice
@pytest.mark.parametrize("seed", [1, 2])
def test_the_summary_on_libreoffice_is_the_apps(seed: int) -> None:
    command = soffice()
    assert command is not None, "CLIMBLOG_REQUIRE_SOFFICE is set but no LibreOffice works"
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        made = generate(JOURNAL, Path(folder), seed)
        repo = XlsxBackend(made.path)
        cells = named_cells(repo)
        wrong = []
        for day in days_to_check(repo):
            book = openpyxl.load_workbook(made.path)
            book["Summary"]["B3"] = dt.datetime.combine(day, dt.time())
            book.save(made.path)
            rows = recalculate(command, made.path)["Summary"]
            shown = {
                (r, c): value
                for r, line in enumerate(rows, start=1)
                for c, value in enumerate(line, start=1)
            }
            wrong += [f"{day}: {w}" for w in mismatches(cells, shown, app_summary(repo, day))]
    assert wrong == []


@pytest.fixture
def harness() -> Iterator[GSheets]:  # pragma: no cover - live only
    config = load_config(config_path())
    made = GSheets(RestSheetsClient(config.google_session), live=True)
    yield made
    made.close()  # the fictional sheets go to the trash


@live
def test_the_summary_on_google_is_the_apps(harness: GSheets) -> None:  # pragma: no cover
    repo = harness.new()
    generate_google(JOURNAL, repo, 1)
    cells = named_cells(repo)
    wrong = []
    for day in days_to_check(repo):
        harness.edit(repo, "Summary", "B3", dt.datetime.combine(day, dt.time()))
        assert repo.spreadsheet_id is not None
        book = harness.client.get_grid(repo.spreadsheet_id)
        [sheet] = [s for s in book["sheets"] if s["properties"]["title"] == "Summary"]
        shown = {
            (r, c): value
            for r, line in enumerate(grid_rows(sheet), start=1)
            for c, value in enumerate(line, start=1)
        }
        wrong += [f"{day}: {w}" for w in mismatches(cells, shown, app_summary(repo, day))]
    assert wrong == []
