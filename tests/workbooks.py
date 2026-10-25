# SPDX-License-Identifier: GPL-3.0-or-later
"""Build small fictional workbooks for the storage tests (D-034: fictional data only)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import openpyxl

Rows = Sequence[Sequence[Any]]


def tab(keys: Sequence[str | None], *rows: Sequence[Any]) -> list[Sequence[Any]]:
    """A data tab: labels in row 1 (here the keys, upper-cased), keys in row 2, then the rows."""
    labels = [key.upper() if key else None for key in keys]
    return [labels, list(keys), *rows]


def write_workbook(path: Path, tabs: Mapping[str, Rows]) -> Path:
    """Write the tabs, in order, to a new .xlsx file."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, rows in tabs.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    workbook.save(path)
    return path
