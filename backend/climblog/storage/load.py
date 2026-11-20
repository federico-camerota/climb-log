# SPDX-License-Identifier: GPL-3.0-or-later
"""Load a module's records from its workbook, with data issues (04-storage.md §1, §4, D-048).

Every entity's tabs are read through a `Repository`, cells are parsed by field type, and rows
become records: rows without a key are ignored when empty and reported when not, a blank
`default: next` key part is numbered in sheet order (D-050), the first of duplicate keys wins,
and the section tabs of a split entity join the anchor tab on the key.
Whatever doesn't fit is a data issue; the rest still loads. Derived values are computed
afterwards (`modules/compute.py`).
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field

from climblog.expr import Value
from climblog.modules.program import NO_RUNS, RUNS_TAB, Run, Runs, parse_week
from climblog.modules.reference import RETIRED, clean_key, reference_columns
from climblog.modules.schema import (
    NEXT,
    BaseField,
    BoolField,
    DateField,
    Entity,
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
class ReferenceRows:
    """A reference table's rows (D-112), in sheet order, and the sheet row of each."""

    key: str  # the key field
    rows: list[dict[str, Value]] = field(default_factory=list)
    places: list[int] = field(default_factory=list)

    def find(self, key: Value) -> int | None:
        """The index of the row with this key."""
        return next((i for i, row in enumerate(self.rows) if row.get(self.key) == key), None)


@dataclass
class ModuleData:
    settings: dict[str, Value]
    entities: dict[str, EntityData]
    issues: list[DataIssue]
    runs: Runs = NO_RUNS  # a program module's runs (D-109)
    reference: dict[str, ReferenceRows] = field(default_factory=dict)  # D-112


def load_data(module: Module, repo: Repository) -> ModuleData:
    """Settings and stored records of every entity (template-expanded module), and the runs
    of a program module."""
    issues: list[DataIssue] = []
    settings = _settings(module, repo, issues)
    runs = read_runs(repo, issues) if module.program is not None else NO_RUNS
    entities = {name: _Loader(module, name, repo, issues).load() for name in module.entities}
    _report_orphan_children(module, entities, issues)
    if module.program is not None:
        _report_before_runs(module, entities, runs, issues)
    reference = {
        name: read_reference(module, name, repo, issues) for name in module.reference or {}
    }
    return ModuleData(settings, entities, issues, runs, reference)


def read_reference(
    module: Module, name: str, repo: Repository, issues: list[DataIssue]
) -> ReferenceRows:
    """A reference table's rows (D-112): every column read by its type; a row without a key, or
    with the key of a row above, is left out (a data issue); `retired` blank reads No."""
    table_def = (module.reference or {})[name]
    columns = reference_columns(module, name)
    found = ReferenceRows(table_def.key)
    try:
        table = repo.read_table(table_def.tab)
    except TableNotFound:
        issues.append(DataIssue(table_def.tab, None, None, "the tab is missing", "tab"))
        return found
    for missing in (c for c in columns if c not in table.columns):
        if missing != RETIRED and not columns[missing].retired:
            issues.append(
                DataIssue(table_def.tab, None, missing, "the column is missing", "column")
            )
    key = table_def.key
    first_row: dict[Value, int] = {}
    for row in table.rows:
        if not _blank(row.cells.get(DELETED)):
            continue
        values: dict[str, Value] = {}
        row_issues: list[DataIssue] = []
        for name_, column in columns.items():
            raw = row.cells.get(name_)
            try:
                value = parse_cell(module, column, raw)
            except CellError as error:
                row_issues.append(
                    DataIssue(table_def.tab, row.number, name_, error.message, "value", raw)
                )
                value = None
            values[name_] = value
        values[RETIRED] = values[RETIRED] is True
        values[key] = clean_key(values[key])
        if values[key] is None:
            if not any(i.field == key for i in row_issues):
                message = f"no {key}: the row is left out"
                row_issues.append(DataIssue(table_def.tab, row.number, key, message, "left_out"))
            issues.extend(row_issues)
            continue
        if values[key] in first_row:
            message = f"same {key} as row {first_row[values[key]]}: the row is left out"
            row_issues.append(DataIssue(table_def.tab, row.number, None, message, "left_out"))
            issues.extend(row_issues)
            continue
        first_row[values[key]] = row.number
        bad = {i.field for i in row_issues}
        row_issues += [
            DataIssue(table_def.tab, row.number, f, "required, but empty", "required")
            for f, column in columns.items()
            if column.required and values.get(f) is None and f not in bad
        ]
        issues.extend(row_issues)
        found.rows.append(values)
        found.places.append(row.number)
    return found


def read_runs(repo: Repository, issues: list[DataIssue]) -> Runs:
    """The Runs tab (D-109): one run per row with a run number and a start week; a row that
    isn't one is reported and left out, and so is a second run starting the same week (the
    sheet's formulas take the first)."""
    try:
        table = repo.read_table(RUNS_TAB)
    except TableNotFound:
        return NO_RUNS  # schema sync creates it
    runs: list[Run] = []
    starts: dict[dt.date, int] = {}
    numbers: dict[int, int] = {}
    for row in table.rows:
        cells = row.cells
        if not _blank(cells.get(DELETED)):
            continue
        number, week = cells.get("run"), cells.get("start_week")
        if _blank(number) and _blank(week):
            continue
        if isinstance(number, float) and number.is_integer():
            number = int(number)
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            issues.append(_run_issue(row, "run", "a run needs its number (1, 2, …)", number))
            continue
        try:
            start = parse_week(str(week).strip()) if not _blank(week) else None
        except ValueError as error:
            issues.append(_run_issue(row, "start_week", str(error), week))
            continue
        if start is None:
            issues.append(_run_issue(row, "start_week", "a run needs its start week", week))
            continue
        if start in starts:
            message = f"run {starts[start]} already starts that week; this row is left out"
            issues.append(DataIssue(RUNS_TAB, row.number, "start_week", message, "left_out"))
            continue
        if number in numbers:
            message = f"run {number} is also in row {numbers[number]}"
            issues.append(DataIssue(RUNS_TAB, row.number, "run", message))
        starts[start], numbers[number] = number, row.number
        runs.append(Run(number, str(week).strip(), start))
    ordered = sorted(runs, key=lambda r: r.start)
    if [r.number for r in ordered] != sorted(r.number for r in ordered):
        issues.append(
            DataIssue(RUNS_TAB, None, "run", "the runs are not numbered in the order they start")
        )
    return Runs(runs)


def _run_issue(row: SheetRow, field: str, message: str, value: RawCell) -> DataIssue:
    return DataIssue(RUNS_TAB, row.number, field, message, "value", value)


def _report_before_runs(
    module: Module, entities: Mapping[str, EntityData], runs: Runs, issues: list[DataIssue]
) -> None:
    """Records with no run: dated before the first run started (or no run at all)."""
    if not runs.runs:
        if any(data.records for data in entities.values()):
            message = "no run has started: type the first one's start week here (2026-W42)"
            issues.append(DataIssue(RUNS_TAB, None, None, message, "run"))
        return
    first = runs.runs[0].start_week
    for name, data in entities.items():
        entity = module.entities[name]
        if entity.parent is not None:
            continue  # its parent is reported
        tab = entity.main_tab
        for record, place in zip(data.records, data.places, strict=True):
            day = record.get(entity.date_field)
            if isinstance(day, dt.date) and runs.at(day) is None:
                message = f"dated before the first run ({first}): no run or week"
                issues.append(DataIssue(tab, place.get(tab), entity.date_field, message, "run"))


def read_settings(module: Module, repo: Repository) -> dict[str, Value]:
    """The module's settings alone (its `_settings` tab, defaults where missing or bad)."""
    return _settings(module, repo, [])


def _settings(module: Module, repo: Repository, issues: list[DataIssue]) -> dict[str, Value]:
    """Each setting from `_settings`, or its default when missing, blank or bad."""
    try:
        cells = repo.read_kv(SETTINGS_TAB)
    except TableNotFound:
        cells = {}  # schema sync creates the tab (D-052)
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
        issues.append(
            DataIssue(SETTINGS_TAB, None, key, f"{error.message}; using the default", "setting")
        )
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
        fields = self.entity.fields
        self.next = next(  # a key part numbered when blank (D-050)
            (k for k in self.key if isinstance(f := fields[k], BaseField) and f.default == NEXT),
            None,
        )
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
                if not _retired(self.entity, missing):  # a retired field needs no column (03 §3)
                    self.issues.append(
                        DataIssue(tab, None, missing, "the column is missing", "column")
                    )
            first_row: dict[Key, int] = {}
            counts: dict[Key, int] = {}
            for row in table.rows:
                self._row(tab, present, row, first_row, counts)
        self._check_required()
        return self.data

    def _read(self, tab: str) -> Table | None:
        try:
            return self.repo.read_table(tab)
        except TableNotFound:
            self.issues.append(DataIssue(tab, None, None, "the tab is missing", "tab"))
            return None

    def _row(
        self,
        tab: str,
        fields: list[str],
        row: SheetRow,
        first_row: dict[Key, int],
        counts: dict[Key, int],
    ) -> None:
        if not _blank(row.cells.get(DELETED)):
            return
        values, issues = self.parser.parse(
            row.cells, tab=tab, row=row.number, fields=fields, required=False
        )
        if self.next is not None:
            self._number(values, issues, counts)
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
                    DataIssue(
                        tab, row.number, blank[0], f"no {blank[0]}: the row is left out", "left_out"
                    )
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
                    "left_out",
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
            what = describe_key(self.key, key)
            self.issues.append(
                DataIssue(
                    tab, row.number, None, f"no {self.entity.main_tab} row for {what}", "orphan"
                )
            )
            return
        self.data.records[index].update(values)
        self.data.places[index][tab] = row.number

    def _number(
        self, values: dict[str, Value], issues: list[DataIssue], counts: dict[Key, int]
    ) -> None:
        """Count the row among those with the same other key parts; a blank `next` part is
        that position (as the sheet's `COUNTIFS` formula; a bad cell stays bad)."""
        assert self.next is not None
        others = tuple(values.get(part) for part in self.key if part != self.next)
        if None in others:
            return
        counts[others] = counts.get(others, 0) + 1
        bad = any(issue.field == self.next for issue in issues)
        if values.get(self.next) is None and not bad:
            values[self.next] = counts[others]

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
                what = describe_key(link.key, key)
                issues.append(
                    DataIssue(
                        tab,
                        places[tab],
                        None,
                        f"no {parent.main_tab} row for {what}",
                        "orphan_child",
                    )
                )


def describe_key(parts: list[str], key: Key) -> str:
    """`date 2026-11-03, session_no 1`."""
    return ", ".join(f"{part} {_text(value)}" for part, value in zip(parts, key, strict=True))


def _text(value: Value) -> str:
    return value.isoformat() if isinstance(value, dt.date | dt.time) else str(value)


def _retired(entity: Entity, name: str) -> bool:
    field = entity.fields[name]
    return isinstance(field, BaseField) and field.retired


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
