# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a workbook and its module YAML disagree (03-module-framework.md §3, D-051).

Read-only: this only lists differences. Schema sync (#17) applies the ones marked `sync`
(missing tabs and columns, pending renames, `_meta`); `info` is worth knowing but needs no
change (a column the YAML doesn't know keeps its data); an `error` needs a person (a workbook of
another module, a header row the app can't read). Formula columns are checked with #19.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from climblog.modules import Module
from climblog.modules.schema import BaseField, Entity, ReferenceTemplateUse
from climblog.storage.base import AUTO, Repository, StorageError
from climblog.storage.cells import RawCell
from climblog.storage.load import DELETED, SETTINGS_TAB
from climblog.storage.write import UPDATED_AT

META_TAB = "_meta"
SYSTEM_COLUMNS = (UPDATED_AT, DELETED)  # hand-optional, at the right of every data tab (04 §1)

Level = Literal["error", "sync", "info"]


@dataclass(frozen=True)
class Difference:
    level: Level
    tab: str | None  # None: the whole workbook
    column: str | None
    message: str

    def __str__(self) -> str:
        return f"{self.tab}: {self.message}" if self.tab else self.message


def check_schema(module: Module, repo: Repository) -> list[Difference]:
    """Differences between the module and the workbook: `_meta`, data tabs, `_settings`.

    Raises `StorageError` only when the workbook can't be opened at all.
    """
    tables = set(repo.list_tables())
    differences = list(_meta(module, repo, tables))
    for entity in module.entities.values():
        differences += _entity(entity, repo, tables)
    differences += _settings(module, repo, tables)
    return differences


def _meta(module: Module, repo: Repository, tables: set[str]) -> Iterator[Difference]:
    if META_TAB not in tables:
        yield Difference("sync", META_TAB, None, "the tab is missing: never synced")
        return
    try:
        meta = repo.read_kv(META_TAB)
    except StorageError as error:
        yield Difference("error", META_TAB, None, str(error))
        return
    name = meta.get("module")
    if _blank(name):
        yield Difference("sync", META_TAB, None, "no 'module' value")
    elif str(name).strip() != module.module:
        yield Difference(
            "error", META_TAB, None, f"this workbook is for module '{name}', not '{module.module}'"
        )
    version = _version(meta.get("module_version"))
    if version is None:
        yield Difference("sync", META_TAB, None, "no 'module_version' value")
    elif isinstance(version, str):
        yield Difference("error", META_TAB, None, f"'module_version' is not a number: {version}")
    elif version < module.version:
        yield Difference(
            "sync", META_TAB, None, f"synced with v{version}, the YAML is v{module.version}"
        )
    elif version > module.version:
        yield Difference(
            "error",
            META_TAB,
            None,
            f"synced with v{version}, newer than the YAML (v{module.version}): an old YAML file?",
        )


def _entity(entity: Entity, repo: Repository, tables: set[str]) -> Iterator[Difference]:
    fields = {k: f for k, f in entity.fields.items() if isinstance(f, BaseField)}
    # q1..q20 come from a reference table (M5): their columns can't be told from unknown ones yet.
    unknown_ok = any(isinstance(f, ReferenceTemplateUse) for f in entity.fields.values())
    for tab, keys in entity.tab_fields().items():
        if tab not in tables:
            yield Difference("sync", tab, None, "the tab is missing")
            continue
        try:
            columns = set(repo.read_table(tab).columns)
        except StorageError as error:
            yield Difference("error", tab, None, str(error))
            continue
        known = set(SYSTEM_COLUMNS)
        for key in keys:
            if key not in fields:
                continue  # a reference template use
            field = fields[key]
            old = field.renamed_from
            known |= {key} if old is None else {key, old}
            if key in columns:
                if old is not None and old in columns:
                    yield Difference(
                        "error", tab, key, f"columns '{old}' and '{key}' (renamed): keep one"
                    )
            elif old is not None and old in columns:
                yield Difference("sync", tab, key, f"column '{old}' is to be renamed '{key}'")
            elif not field.retired:  # a retired field needs no column
                yield Difference("sync", tab, key, f"column '{key}' is missing")
        for key in SYSTEM_COLUMNS:
            if key not in columns:
                yield Difference("sync", tab, key, f"column '{key}' is missing")
        if not unknown_ok:
            for key in sorted(columns - known):
                if not key.startswith(AUTO):
                    yield Difference("info", tab, key, f"column '{key}' is not in the module")


def _settings(module: Module, repo: Repository, tables: set[str]) -> Iterator[Difference]:
    if SETTINGS_TAB not in tables:
        yield Difference("sync", SETTINGS_TAB, None, "the tab is missing")
        return
    try:
        values = repo.read_kv(SETTINGS_TAB)
    except StorageError as error:
        yield Difference("error", SETTINGS_TAB, None, str(error))
        return
    for key in module.settings:
        if key not in values:
            yield Difference("info", SETTINGS_TAB, key, f"no row for '{key}': the default is used")


def _version(cell: RawCell) -> int | str | None:
    """The `module_version` cell as a number; its text when it isn't one."""
    if _blank(cell):
        return None
    if isinstance(cell, int | float) and not isinstance(cell, bool) and cell == int(cell):
        return int(cell)
    text = str(cell).strip()
    return int(text) if text.isdigit() else text


def _blank(cell: object) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())
