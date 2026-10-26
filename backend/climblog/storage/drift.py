# SPDX-License-Identifier: GPL-3.0-or-later
"""Drift check: `auto:` cells that no longer show what the app computes (03 §2.2b, D-018, D-054).

Two kinds, both reported as data issues:
- a **changed formula**: the cell's formula is not the compiled one (typed over by hand, or
  deleted in a row with data). `climblog check --apply` writes it again.
- a **different value**: the formula is right, but the value the sheet last computed differs from
  the app's. Only where the sheet has a computed value: after the app writes, a workbook has none
  until it is opened and saved in Excel or LibreOffice.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from climblog.expr import Value
from climblog.modules import Module
from climblog.modules.compute import compute_module
from climblog.modules.formulas import (
    XLSX,
    Dialect,
    FormulaColumn,
    compile_formulas,
    formula_columns,
    normalize,
)
from climblog.storage.base import AUTO, Repository, StorageError, Table
from climblog.storage.cells import RawCell
from climblog.storage.check import Difference
from climblog.storage.load import load_data


@dataclass(frozen=True)
class Drift:
    kind: Literal["formula", "value"]
    tab: str
    row: int
    column: str  # `auto:<field>`
    sheet: RawCell  # the formula found (kind "formula") or the value shown (kind "value")
    app: Value | str  # the compiled formula, or the app's value

    def __str__(self) -> str:
        if self.kind == "formula":
            return f"{self.tab}, row {self.row}, {self.column}: the formula was changed"
        return (
            f"{self.tab}, row {self.row}, {self.column}: the sheet shows {self.sheet!r}, "
            f"the app computes {self.app!r}"
        )


def find_drift(module: Module, repo: Repository, dialect: Dialect = XLSX) -> list[Drift]:
    """Every drifted `auto:` cell, tab by tab (tabs that can't be read are left out)."""
    placed, _ = formula_columns(module)
    tabs = list(dict.fromkeys(c.tab for c in placed))
    formulas: dict[str, Table] = {}
    values: dict[str, Table] = {}
    for tab in tabs:
        try:
            formulas[tab], values[tab] = repo.read_formulas(tab), repo.read_table(tab)
        except StorageError:
            continue  # a missing tab: `check` reports it
    columns = {tab: table.numbers for tab, table in formulas.items()}
    templates = compile_formulas(module, columns, dialect)
    found = []
    changed: set[tuple[str, int, str]] = set()
    for tab, table in formulas.items():
        data_rows = _data_rows(values[tab])
        for row in table.rows:
            for (t, key), template in templates.items():
                if t != tab:
                    continue
                cell = row.cells.get(key)
                expected = template.at(row.number)
                if cell is None and row.number not in data_rows:
                    continue  # an empty buffer row
                if isinstance(cell, str) and normalize(cell) == normalize(expected):
                    continue  # the same formula, maybe rewritten by the spreadsheet on save
                found.append(Drift("formula", tab, row.number, key, cell, expected))
                changed.add((tab, row.number, key))
    found += _value_drift(module, repo, placed, changed, values)
    return found


def _data_rows(table: Table) -> set[int]:
    return {row.number for row in table.rows if any(not k.startswith(AUTO) for k in row.cells)}


def _value_drift(
    module: Module,
    repo: Repository,
    placed: list[FormulaColumn],
    changed: set[tuple[str, int, str]],
    values: Mapping[str, Table],
) -> list[Drift]:
    data = load_data(module, repo)
    tables = {name: e.records for name, e in data.entities.items()}
    derived = compute_module(module, tables, data.settings)
    shown = {(tab, row.number): row.cells for tab, table in values.items() for row in table.rows}
    found = []
    for name, entity in data.entities.items():
        for column in placed:
            key = column.key.removeprefix(AUTO)
            if column.hand_written or key not in module.entities[name].derived:
                continue
            for place, computed in zip(entity.places, derived[name], strict=True):
                row = place.get(column.tab)
                if row is None or (column.tab, row, column.key) in changed:
                    continue
                cell = shown.get((column.tab, row), {}).get(column.key)
                if cell is None:
                    continue  # not computed by the sheet yet (or blank): nothing to compare
                want = computed.get(key)
                if not same(want, cell):
                    found.append(Drift("value", column.tab, row, column.key, cell, want))
    return found


def same(app: Value, sheet: object) -> bool:
    """Whether a value the sheet computed is the app's: blanks, Yes/No, days, small float noise."""
    if app is None or app == "":
        return sheet is None or sheet == ""
    if isinstance(app, bool) or isinstance(sheet, bool):
        return isinstance(sheet, bool) and bool(app) == sheet
    if isinstance(app, int | float) and isinstance(sheet, int | float):
        return abs(app - sheet) < 1e-9
    if isinstance(app, dt.date) and isinstance(sheet, dt.datetime):  # a day is its midnight
        return dt.datetime.combine(app, dt.time()) == sheet
    if isinstance(app, dt.time) and isinstance(sheet, dt.datetime):
        return app == sheet.time()
    return bool(app == sheet)


def drift_differences(drifts: list[Drift]) -> list[Difference]:
    """The drift as `check` lines, one per column and kind: changed formulas are put back by
    sync (`sync`), different values are worth a look (`info`)."""
    groups: dict[tuple[str, str, str], list[Drift]] = {}
    for drift in drifts:
        groups.setdefault((drift.kind, drift.tab, drift.column), []).append(drift)
    lines = []
    for (kind, tab, column), items in groups.items():
        rows = ", ".join(str(d.row) for d in items[:5]) + (", …" if len(items) > 5 else "")
        if kind == "formula":
            lines.append(
                Difference("sync", tab, column, f"'{column}': formula changed in rows {rows}")
            )
        else:
            first = items[0]
            lines.append(
                Difference(
                    "info",
                    tab,
                    column,
                    f"'{column}': the sheet shows other values than the app in rows {rows} "
                    f"(row {first.row}: {first.sheet!r}, app {first.app!r})",
                )
            )
    return lines
