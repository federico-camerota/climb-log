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
from climblog.storage.load import EntityData, ModuleData, load_data
from climblog.storage.write import RecordNotFound, RecordWriter, WriteError
from climblog.storage.xlsx import XlsxBackend

__all__ = [
    "Append",
    "Backups",
    "CellError",
    "DataIssue",
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
    "Table",
    "TableNotFound",
    "Update",
    "WorkbookLocked",
    "WriteConflict",
    "WriteError",
    "XlsxBackend",
    "load_data",
    "parse_cell",
]
