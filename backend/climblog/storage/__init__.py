# SPDX-License-Identifier: GPL-3.0-or-later
"""Spreadsheet storage: the Repository, its backends, reading and writing records (04-storage)."""

from climblog.storage.backup import Backups
from climblog.storage.base import (
    Append,
    Edit,
    Repository,
    SheetRow,
    StorageError,
    Table,
    TableNotFound,
    Update,
    WorkbookLocked,
    WriteConflict,
)
from climblog.storage.cells import CellError, DataIssue, RawCell, RowParser, parse_cell
from climblog.storage.check import Difference, check_schema
from climblog.storage.drift import Drift, find_drift
from climblog.storage.layout import WorkbookLayout, workbook_layout
from climblog.storage.load import EntityData, ModuleData, load_data
from climblog.storage.sync import SyncRefused, sync_module
from climblog.storage.write import RecordNotFound, RecordWriter, WriteError
from climblog.storage.xlsx import XlsxBackend

__all__ = [
    "Append",
    "Backups",
    "CellError",
    "DataIssue",
    "Difference",
    "Drift",
    "Edit",
    "EntityData",
    "ModuleData",
    "RawCell",
    "RecordNotFound",
    "RecordWriter",
    "Repository",
    "RowParser",
    "SheetRow",
    "StorageError",
    "SyncRefused",
    "Table",
    "TableNotFound",
    "Update",
    "WorkbookLayout",
    "WorkbookLocked",
    "WriteConflict",
    "WriteError",
    "XlsxBackend",
    "check_schema",
    "find_drift",
    "load_data",
    "parse_cell",
    "sync_module",
    "workbook_layout",
]
