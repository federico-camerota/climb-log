# SPDX-License-Identifier: GPL-3.0-or-later
"""Spreadsheet storage: the Repository, the backends, reading cells and records (04-storage.md)."""

from climblog.storage.base import Repository, SheetRow, StorageError, Table, TableNotFound
from climblog.storage.cells import CellError, DataIssue, RawCell, RowParser, parse_cell
from climblog.storage.load import EntityData, ModuleData, load_data
from climblog.storage.xlsx import XlsxBackend

__all__ = [
    "CellError",
    "DataIssue",
    "EntityData",
    "ModuleData",
    "RawCell",
    "Repository",
    "RowParser",
    "SheetRow",
    "StorageError",
    "Table",
    "TableNotFound",
    "XlsxBackend",
    "load_data",
    "parse_cell",
]
