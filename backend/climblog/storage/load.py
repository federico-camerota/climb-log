# SPDX-License-Identifier: GPL-3.0-or-later
"""Load a module's records from its workbook, with data issues (04-storage.md §1, §4, D-048).

Every entity's tabs are read through a `Repository`, cells are parsed by field type, and rows
become records: rows without a key are ignored when empty and reported when not, the first of
duplicate keys wins, and the section tabs of a split entity join the anchor tab on the key.
Whatever doesn't fit is a data issue; the rest still loads. Derived values are computed
afterwards (`modules/compute.py`).
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field

from climblog.expr import Value
from climblog.modules.schema import (
    BaseField,
    BoolField,
    DateField,
    Module,
    NumberField,
    Setting,
    TextField,
)
from climblog.storage.base import Repository, SheetRow, Table, TableNotFound
from climblog.storage.cells import CellError, DataIssue, RawCell, RowParser, parse_cell

SETTINGS_TAB = "_settings"
DELETED = "deleted"  # soft delete: a non-blank cell hides the row (04 §1)

# How a setting's cell is read: as a field of the same type.
_SETTING_FIELDS: dict[str, BaseField] = {
    "number": NumberField(type="number"),
    "integer": NumberField(type="integer"),
    "date": DateField(type="date"),
    "text": TextField(type="text"),
    "bool": BoolField(type="bool"),
}

Key = tuple[Value, ...]


@dataclass
class EntityData:
    """An entity's records, in sheet order, and where each one is (tab → sheet row)."""

    records: list[dict[str, Value]] = field(default_factory=list)
    places: list[dict[str, int]] = field(default_factory=list)


@dataclass
class ModuleData:
    settings: dict[str, Value]
    entities: dict[str, EntityData]
    issues: list[DataIssue]


def load_data(module: Module, repo: Repository) -> ModuleData:
    """Settings and stored records of every entity (template-expanded module)."""
    issues: list[DataIssue] = []
    settings = _settings(module, repo, issues)
    entities = {name: _Loader(module, name, repo, issues).load() for name in module.entities}
    _report_orphan_children(module, entities, issues)
    return ModuleData(settings, entities, issues)


def _settings(module: Module, repo: Repository, issues: list[DataIssue]) -> dict[str, Value]:
    """Each setting from `_settings`, or its default when missing, blank or bad."""
    try:
        cells = repo.read_kv(SETTINGS_TAB)
    except TableNotFound:
        cells = {}  # schema sync creates the tab (#17)
    values: dict[str, Value] = {}
    for key, setting in module.settings.items():
        values[key] = _setting(module, setting, key, cells.get(key), issues)
    return values


def _setting(
    module: Module, setting: Setting, key: str, raw: RawCell, issues: list[DataIssue]
) -> Value:
    try:
        value = parse_cell(module, _SETTING_FIELDS[setting.type], raw)
    except CellError as error:
        issues.append(DataIssue(SETTINGS_TAB, None, key, f"{error.message}; using the default"))
        value = None
    if value is None:
        default: Value = setting.default  # checked against the type at load
        return default
    return value


class _Loader:
    """One entity: its tabs read in order, anchor tab first."""

    def __init__(self, module: Module, name: str, repo: Repository, issues: list[DataIssue]):
        self.entity = module.entities[name]
        self.repo = repo
        self.issues = issues
        self.parser = RowParser(module, name)
        self.key = self.entity.key or []
        tabs = self.entity.tab_fields()
        anchor = self.entity.main_tab
        self.tabs = {anchor: tabs[anchor], **{t: f for t, f in tabs.items() if t != anchor}}
        self.data = EntityData()
        self.by_key: dict[Key, int] = {}  # anchor rows: key → record index

    def load(self) -> EntityData:
        for tab, fields in self.tabs.items():
            table = self._read(tab)
            if table is None:
                continue
            present = [f for f in fields if f in table.columns]
            for missing in (f for f in fields if f not in table.columns):
                self.issues.append(DataIssue(tab, None, missing, "the column is missing"))
            first_row: dict[Key, int] = {}
            for row in table.rows:
                self._row(tab, present, row, first_row)
        self._check_required()
        return self.data

    def _read(self, tab: str) -> Table | None:
        try:
            return self.repo.read_table(tab)
        except TableNotFound:
            self.issues.append(DataIssue(tab, None, None, "the tab is missing"))
            return None

    def _row(self, tab: str, fields: list[str], row: SheetRow, first_row: dict[Key, int]) -> None:
        if not _blank(row.cells.get(DELETED)):
            return
        values, issues = self.parser.parse(
            row.cells, tab=tab, row=row.number, fields=fields, required=False
        )
        has_data = any(not _blank(row.cells.get(f)) for f in fields if f not in self.key)
        if not self.key:
            if has_data:
                self.issues.extend(issues)
                self._add(tab, row.number, values)
            return

        key = tuple(values.get(part) for part in self.key)
        blank = [part for part in self.key if values.get(part) is None]
        if blank:
            bad = {issue.field for issue in issues}
            if has_data and not bad & set(blank):
                issues.append(
                    DataIssue(tab, row.number, blank[0], f"no {blank[0]}: the row is left out")
                )
            self.issues.extend(issues)
            return
        if key in first_row:
            issues.append(
                DataIssue(
                    tab,
                    row.number,
                    None,
                    f"same {', '.join(self.key)} as row {first_row[key]}: the row is left out",
                )
            )
            self.issues.extend(issues)
            return
        first_row[key] = row.number
        self.issues.extend(issues)

        if tab == self.entity.main_tab:
            self.by_key[key] = len(self.data.records)
            self._add(tab, row.number, values)
            return
        index = self.by_key.get(key)
        if index is None:
            what = _describe(self.key, key)
            self.issues.append(
                DataIssue(tab, row.number, None, f"no {self.entity.main_tab} row for {what}")
            )
            return
        self.data.records[index].update(values)
        self.data.places[index][tab] = row.number

    def _add(self, tab: str, number: int, values: dict[str, Value]) -> None:
        self.data.records.append(values)
        self.data.places.append({tab: number})

    def _check_required(self) -> None:
        """Required fields, per tab row the record has, once the tabs are joined."""
        reported = {(i.tab, i.row, i.field) for i in self.issues}
        for values, places in zip(self.data.records, self.data.places, strict=True):
            for tab, number in places.items():
                skip = {f for t, r, f in reported if t == tab and r == number}
                fields = [f for f in self.tabs[tab] if f in values]
                self.issues += self.parser.missing(
                    values, tab=tab, row=number, fields=fields, skip=skip
                )


def _report_orphan_children(
    module: Module, entities: Mapping[str, EntityData], issues: list[DataIssue]
) -> None:
    """A child row whose parent row is missing (03 §2.1b): reported; the record still loads."""
    for name, entity in module.entities.items():
        link = entity.parent
        if link is None:
            continue
        parent = module.entities[link.entity]
        keys = {
            tuple(record.get(part) for part in link.key)
            for record in entities[link.entity].records
            if all(record.get(f) == v for f, v in link.fixed.items())
        }
        data = entities[name]
        for record, places in zip(data.records, data.places, strict=True):
            key = tuple(record.get(part) for part in link.key)
            if key not in keys:
                tab = entity.main_tab
                what = _describe(link.key, key)
                issues.append(
                    DataIssue(tab, places[tab], None, f"no {parent.main_tab} row for {what}")
                )


def _describe(parts: list[str], key: Key) -> str:
    """`date 2026-11-03, session_no 1`."""
    return ", ".join(f"{part} {_text(value)}" for part, value in zip(parts, key, strict=True))


def _text(value: Value) -> str:
    return value.isoformat() if isinstance(value, dt.date | dt.time) else str(value)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
