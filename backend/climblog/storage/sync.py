# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema sync: make a module's workbook match its YAML, additively (03 §3, 04 §1, D-052).

The workbook is checked first; a module with an `error` difference (a workbook of another
module, an unreadable header row, …) is not synced, since those need a person.
"""

import datetime as dt

from climblog import __version__
from climblog.modules import Module
from climblog.storage.base import Repository, StorageError
from climblog.storage.cells import RawCell
from climblog.storage.check import check_schema
from climblog.storage.layout import workbook_layout


class SyncRefused(StorageError):
    """The workbook has problems sync must not guess about."""


def sync_module(module: Module, repo: Repository) -> list[str]:
    """Sync the workbook (created if missing); what was done, one line per change."""
    if repo.exists():
        errors = [d for d in check_schema(module, repo) if d.level == "error"]
        if errors:
            lines = "; ".join(str(d) for d in errors)
            raise SyncRefused(f"not synced, fix these first: {lines}")
    meta: dict[str, RawCell] = {
        "module": module.module,
        "module_version": module.version,
        "schema_synced_at": dt.datetime.now().isoformat(timespec="seconds"),
        "app_version": __version__,
    }
    return repo.sync_schema(workbook_layout(module), meta)
