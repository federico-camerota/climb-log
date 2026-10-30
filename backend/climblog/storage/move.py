# SPDX-License-Identifier: GPL-3.0-or-later
"""Moving a module from a local workbook to a new Google Sheet (04-storage.md §3, §7, D-067).

The local workbook is only read, and must check clean first (`climblog check --apply` brings it
in step: then both are read the same way). A new sheet is made by schema sync (headers, rules,
formulas), then every row of the module's tabs is copied as it is, raw cells and all: values
the app would call data issues, soft-deleted rows, `updated_at`. Only the module's columns go
over (and the system columns); others, retired fields included, are reported as not copied.
Then the copy is checked: each tab holds as many rows; the records, settings and data issues the
app reads from Google are those it reads from the workbook; the schema checks clean; and every
formula Google computes gives the app's value. On a
difference the sheet is kept for a look, and the module stays local.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from climblog.modules import Module
from climblog.storage.base import AUTO, Append, Repository, TableNotFound
from climblog.storage.cells import RawCell
from climblog.storage.check import check_schema
from climblog.storage.drift import drift_differences, find_drift
from climblog.storage.gsheets import GSheetsBackend
from climblog.storage.layout import SETTINGS_TAB, workbook_layout
from climblog.storage.load import ModuleData, load_data
from climblog.storage.sync import SyncRefused, sync_module


@dataclass
class MoveReport:
    spreadsheet_id: str
    copied: dict[str, int] = field(default_factory=dict)  # tab → rows
    not_copied: list[str] = field(default_factory=list)  # columns with data outside the module
    differences: list[str] = field(default_factory=list)  # what the check found; [] = moved


def move_to_google(module: Module, local: Repository, google: GSheetsBackend) -> MoveReport:
    """Copy the module from `local` into the new sheet `google` (a backend without an ID, made
    here by schema sync), then check the copy."""
    pending = [d for d in check_schema(module, local) if d.level != "info"]
    if pending:
        lines = "; ".join(str(d) for d in pending)
        raise SyncRefused(
            f"not moved: the workbook is not in step with the module (`climblog check "
            f"{module.module} --apply` syncs it; errors need a person): {lines}"
        )
    before = load_data(module, local)
    sync_module(module, google)
    assert google.spreadsheet_id is not None
    report = MoveReport(google.spreadsheet_id)
    edits: list[Append] = []
    for tab in workbook_layout(module).tabs:
        try:
            table = local.read_table(tab.name)
        except TableNotFound:
            continue  # nothing to copy: sync made it empty
        keys = {spec.key for spec in tab.columns if not spec.formula and not spec.retired}
        for key in table.columns:
            holds_data = any(key in row.cells for row in table.rows)
            if key not in keys and not key.startswith(AUTO) and holds_data:
                report.not_copied.append(f"{tab.name}: column '{key}'")
        rows = 0
        for row in table.rows:
            cells: dict[str, RawCell] = {k: v for k, v in row.cells.items() if k in keys}
            if cells:
                edits.append(Append(tab.name, cells))
                rows += 1
        report.copied[tab.name] = rows
    google.apply(edits)
    try:
        settings = local.read_kv(SETTINGS_TAB)
    except TableNotFound:
        settings = {}
    if settings:
        google.write_kv(SETTINGS_TAB, settings)
    for name, rows in report.copied.items():  # deleted rows too, which the app doesn't load
        on_google = sum(
            any(not k.startswith(AUTO) for k in row.cells) for row in google.read_table(name).rows
        )
        if on_google != rows:
            report.differences.append(f"{name}: {rows} rows copied, {on_google} on Google")
    after = load_data(module, google)
    report.differences += _compare(module, before, after)
    report.differences += [str(d) for d in check_schema(module, google) if d.level != "info"]
    report.differences += [str(d) for d in drift_differences(find_drift(module, google))]
    return report


def _compare(module: Module, before: ModuleData, after: ModuleData) -> list[str]:
    """What the app reads differently from the copy (records in order, settings, data issues;
    row numbers aside, since the copy has no blank rows between records). Retired fields are
    not copied (they are listed as such) and not compared."""
    found = []
    if before.settings != after.settings:
        found.append("the settings differ")
    for name, entity in before.entities.items():
        retired = {
            k for k, f in module.entities[name].fields.items() if getattr(f, "retired", False)
        }
        records = [{k: v for k, v in r.items() if k not in retired} for r in entity.records]
        copied = [
            {k: v for k, v in r.items() if k not in retired} for r in after.entities[name].records
        ]
        if len(copied) != len(records):
            found.append(f"{name}: {len(records)} records, {len(copied)} on Google")
        elif copied != records:
            differ = sum(a != b for a, b in zip(records, copied, strict=True))
            found.append(f"{name}: {differ} records read differently on Google")
    issues_before, issues_after = Counter(_issues(before)), Counter(_issues(after))
    if issues_before != issues_after:
        lost = sum((issues_before - issues_after).values())
        new = sum((issues_after - issues_before).values())
        found.append(f"data issues differ: {lost} only in the workbook, {new} only on Google")
    return found


def _issues(data: ModuleData) -> list[tuple[str, str | None, str]]:
    return [(i.tab, i.field, re.sub(r"\brows? \d+", "row", i.message)) for i in data.issues]
