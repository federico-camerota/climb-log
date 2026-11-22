# SPDX-License-Identifier: GPL-3.0-or-later
"""What the legacy importers share (04-storage.md §8, D-061, D-116): opening a legacy workbook,
checking its layout against an explicit table of header labels, reading cells as the new module
reads them, refusing a workbook that already holds data, and the parity report.

A value that can't be read is left out and reported by its place, never its content.
"""

import datetime as dt
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import column_index_from_string
from openpyxl.utils.datetime import to_excel
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.worksheet import Worksheet

from climblog.expr import Value
from climblog.modules import Module
from climblog.modules.schema import BaseField
from climblog.storage import CellError, Repository, StorageError, load_data, parse_cell
from climblog.storage.drift import same

RawValue = Any  # a cell as the legacy sheet holds it
Column = tuple[str, str, str]  # (column letter, its header label, the module's field)


class LegacyLayoutError(StorageError):
    """The workbook doesn't have the legacy layout."""


class ImportRefused(StorageError):
    """The target workbook already holds data: an import never mixes with it."""


@dataclass
class LegacyRecord:
    entity: str
    values: dict[str, Value]
    rows: dict[str, int]  # legacy tab → its row
    computed: dict[str, RawValue] = field(default_factory=dict)  # derived field → legacy value


@dataclass
class ParityColumn:
    entity: str
    field: str
    compared: int  # records where the legacy sheet had a computed value
    mismatches: list[tuple[dt.date, RawValue, Value]]  # (date, legacy, app)
    known: str | None = None  # a difference that is on purpose

    @property
    def matching(self) -> int:
        return self.compared - len(self.mismatches)


def has_computed(records: Sequence[LegacyRecord]) -> bool:
    """Whether the workbook holds the values its formulas computed. A file written by a program
    that doesn't compute formulas has none until opened and saved in a spreadsheet."""
    return any(v not in (None, "") for r in records for v in r.computed.values())


def open_legacy(path: Path) -> Any:
    """The workbook with the values its formulas last computed."""
    try:
        return openpyxl.load_workbook(path, data_only=True, read_only=False)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, InvalidFileException) as error:
        raise StorageError(f"cannot read {path.name}: {error}") from None


def sheet(book: Any, name: str, what: str) -> Worksheet:
    if name not in book.sheetnames:
        raise LegacyLayoutError(f"no tab '{name}': not a legacy {what}")
    found = book[name]
    assert isinstance(found, Worksheet)
    return found


def check_layout(found: Worksheet, columns: Sequence[Column], what: str, row: int = 4) -> None:
    """Each column's header label in `row` must be the legacy one (spaces ignored)."""
    for column, label, _ in columns:
        value = found.cell(row, column_index_from_string(column)).value
        if _label(value) != _label(label):
            raise LegacyLayoutError(
                f"{found.title}!{column}{row} is {value!r}, expected {label!r}: "
                f"the layout differs from the legacy {what}"
            )


def _label(value: object) -> str:
    return " ".join(str(value or "").split())


def as_day(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else None


def read_cell(module: Module, column: Any, raw: object, place: str, unread: list[str]) -> Value:
    """A legacy cell as the module reads it; an unreadable one is left out and reported."""
    assert isinstance(column, BaseField)
    try:
        return parse_cell(module, column, raw)  # type: ignore[arg-type]
    except CellError:
        unread.append(f"{place}: not a valid value for this column, left out")
        return None


def refuse_if_held(module: Module, repo: Repository, what: str) -> None:
    """An import goes into a new or empty workbook only: no records, no reference rows."""
    if not repo.exists():
        return
    found = load_data(module, repo)
    held = sum(len(e.records) for e in found.entities.values())
    held += sum(len(rows.rows) for rows in found.reference.values())  # reference rows count
    if held:
        raise ImportRefused(
            f"the {what} workbook already holds {held} records: import into a new one"
        )


def compare(
    records: Sequence[LegacyRecord],
    derived: Mapping[str, Sequence[Mapping[str, Value]]],
    known: Callable[[str, str], str | None],
) -> list[ParityColumn]:
    """The legacy computed values against the app's, per derived field. `derived[entity]`
    holds the app's values of that entity's records, in the order of `records`."""
    columns: dict[tuple[str, str], ParityColumn] = {}
    position: dict[str, int] = {}
    for record in records:
        i = position.get(record.entity, 0)
        position[record.entity] = i + 1
        app = derived[record.entity][i]
        day = record.values["date"]
        assert isinstance(day, dt.date)
        for name, sheet_value in record.computed.items():
            column = columns.setdefault(
                (record.entity, name),
                ParityColumn(record.entity, name, 0, [], known(record.entity, name)),
            )
            if sheet_value in (None, "") and app.get(name) is None:
                continue
            column.compared += 1
            sheet_value = as_number(sheet_value, app.get(name))
            if not same(app.get(name), sheet_value):
                column.mismatches.append((day, sheet_value, app.get(name)))
    return list(columns.values())


def as_number(found: RawValue, app: Value) -> RawValue:
    """A number the legacy sheet shows in a date or duration format (days since, …) as the
    number it is, when the app's value is a number."""
    if not isinstance(app, int | float) or isinstance(app, bool):
        return found
    if isinstance(found, dt.timedelta):
        return found.total_seconds() / 86400
    if isinstance(found, dt.datetime | dt.date | dt.time):
        return to_excel(found)  # type: ignore[no-untyped-call]
    return found


def with_defaults(module: Module, values: Mapping[str, Value]) -> dict[str, Value]:
    defaults: dict[str, Value] = {k: s.default for k, s in module.settings.items()}
    return defaults | dict(values)
