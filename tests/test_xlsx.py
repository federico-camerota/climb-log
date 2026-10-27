# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a local workbook: what is particular to .xlsx and openpyxl (04 §2, D-048).

What every backend must do is in `test_backend_read.py`.
"""

import datetime as dt
from pathlib import Path

import pytest
from workbooks import tab, write_workbook

from climblog.storage import SheetRow, StorageError, XlsxBackend


def test_a_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.xlsx"
    path.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(StorageError, match=r"cannot read broken\.xlsx"):
        XlsxBackend(path).list_tables()


def test_formulas_read_as_the_sheet_shows_them(tmp_path: Path) -> None:
    """data_only: a formula cell gives its last computed value (none in a file openpyxl wrote)."""
    path = write_workbook(tmp_path / "w.xlsx", {"T": tab(["a", "auto:b"], [2, "=A3*2"])})
    assert XlsxBackend(path).read_table("T").rows == (SheetRow(3, {"a": 2}),)


def test_rare_openpyxl_values_become_raw_cells() -> None:
    from decimal import Decimal

    from openpyxl.cell.rich_text import CellRichText

    from climblog.storage.xlsx import _raw

    assert _raw(Decimal("7.5")) == 7.5
    assert _raw(CellRichText(["Più ", "riposo"])) == "Più riposo"
    assert _raw(dt.time(9, 30)) == dt.time(9, 30)
