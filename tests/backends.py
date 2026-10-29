# SPDX-License-Identifier: GPL-3.0-or-later
"""The storage backends the contract tests run on (`test_backend_*.py`, 07-roadmap.md).

A contract test uses a backend only through the `Repository` protocol, plus this harness for
what the protocol doesn't offer: building a workbook from rows, reading a tab as stored
(formulas as text) and changing a cell by hand. Each backend has one harness here; the
`backend` fixture runs every contract test on each of them.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from workbooks import Rows, write_workbook

from climblog.storage import Repository, XlsxBackend

Cells = list[tuple[Any, ...]]


class Backend(Protocol):
    name: str

    def make(self, tabs: Mapping[str, Rows]) -> Repository:
        """A new workbook with these tabs, in order (row 1 first; formulas as `=…` text)."""
        ...

    def new(self) -> Repository:
        """A workbook that doesn't exist yet (schema sync creates it)."""
        ...

    def cells(self, repo: Repository, tab: str) -> Cells:
        """The tab as stored: formulas as text, rows up to the last one with a value, each as
        wide as the widest."""
        ...

    def edit(self, repo: Repository, tab: str, cell: str, value: Any) -> None:
        """Change a cell (`B4`) outside the app, as a hand edit would."""
        ...

    def label(self, repo: Repository) -> str:
        """How messages name the workbook."""
        ...


class Xlsx:
    name = "xlsx"

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.count = 0

    def _path(self) -> Path:
        self.count += 1
        return self.folder / f"book{self.count}.xlsx"

    def make(self, tabs: Mapping[str, Rows]) -> XlsxBackend:
        return XlsxBackend(write_workbook(self._path(), tabs))

    def new(self) -> XlsxBackend:
        return XlsxBackend(self._path())

    def cells(self, repo: Repository, tab: str) -> Cells:
        assert isinstance(repo, XlsxBackend)
        workbook = openpyxl.load_workbook(repo.path)
        try:
            sheet = workbook[tab]
            assert isinstance(sheet, Worksheet)
            rows = [tuple(c.value for c in row) for row in sheet.iter_rows()]
        finally:
            workbook.close()
        while rows and all(v is None for v in rows[-1]):
            rows.pop()
        return rows

    def edit(self, repo: Repository, tab: str, cell: str, value: Any) -> None:
        assert isinstance(repo, XlsxBackend)
        workbook = openpyxl.load_workbook(repo.path)
        workbook[tab][cell] = value
        workbook.save(repo.path)
        later = repo.path.stat().st_mtime + 5
        os.utime(repo.path, (later, later))  # a clearly newer mtime, whatever the clock resolution

    def label(self, repo: Repository) -> str:
        assert isinstance(repo, XlsxBackend)
        return repo.path.name


BACKENDS = ["xlsx"]


def harness(name: str, folder: Path) -> Backend:
    if name == "xlsx":
        return Xlsx(folder)
    raise ValueError(f"no harness for backend '{name}'")
