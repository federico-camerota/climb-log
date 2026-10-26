# SPDX-License-Identifier: GPL-3.0-or-later
"""Local snapshot of each module's data (04-storage.md §6, D-020, D-055).

The last data read from a module's workbook, kept on disk so the app starts at once and can
still read when the source is out of reach (Google, M2). It holds the rows as the backend gave
them, so loading works the same on a snapshot (`load_data` takes any `Repository`), plus when the
source last changed and when it was read. It is a cache: a missing, damaged or older-format
snapshot is ignored, and deleting it is always safe.

Format: gzipped JSON, `<module>.json.gz`. Dates and times are tagged (`{"d": "2026-10-20"}`),
the other cells are JSON values. The file holds personal data: it is written for the owner only
(0600) and never committed (`.gitignore`: `/snapshots/`).
"""

import datetime as dt
import gzip
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from climblog.storage.base import (
    Edit,
    Repository,
    SheetRow,
    StorageError,
    Table,
    TableNotFound,
)
from climblog.storage.cells import RawCell
from climblog.storage.layout import META_TAB, SETTINGS_TAB, WorkbookLayout

FORMAT = 1  # bump when the layout changes: older files are then ignored
KV_TABS = (SETTINGS_TAB, META_TAB)  # key/value tabs: read with `read_kv`


class SnapshotReadOnly(StorageError):
    """A write while the source can't be reached: only the snapshot is there."""


@dataclass(frozen=True)
class Snapshot:
    """The data of one workbook as last read."""

    module: str
    source_modified: dt.datetime  # when the workbook last changed, as read
    read_at: dt.datetime  # when it was read
    tables: Mapping[str, Table]
    kv: Mapping[str, Mapping[str, RawCell]]

    @property
    def tab_names(self) -> list[str]:
        return list(dict.fromkeys([*self.tables, *self.kv]))


def take(
    module: str, repo: Repository, clock: Callable[[], dt.datetime] = dt.datetime.now
) -> Snapshot:
    """Read every tab of the workbook (a tab that can't be read is left out)."""
    modified = repo.last_modified()
    tables: dict[str, Table] = {}
    kv: dict[str, dict[str, RawCell]] = {}
    for name in repo.list_tables():
        try:
            if name in KV_TABS:
                kv[name] = repo.read_kv(name)
            else:
                tables[name] = repo.read_table(name)
        except StorageError:
            continue  # a broken header row: `climblog check` reports it
    return Snapshot(module, modified, clock(), tables, kv)


class SnapshotRepository:
    """A read-only `Repository` on a snapshot."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot

    def list_tables(self) -> list[str]:
        return self.snapshot.tab_names

    def read_table(self, name: str) -> Table:
        if name not in self.snapshot.tables:
            raise TableNotFound(f"no tab '{name}' in the snapshot")
        return self.snapshot.tables[name]

    def read_kv(self, name: str) -> dict[str, RawCell]:
        if name not in self.snapshot.kv:
            raise TableNotFound(f"no tab '{name}' in the snapshot")
        return dict(self.snapshot.kv[name])

    def last_modified(self) -> dt.datetime:
        return self.snapshot.source_modified

    def apply(self, edits: Sequence[Edit]) -> list[int]:
        raise SnapshotReadOnly("the workbook can't be reached: changes can't be saved now")

    def write_kv(self, name: str, values: Mapping[str, RawCell]) -> None:
        raise SnapshotReadOnly("the workbook can't be reached: changes can't be saved now")

    def exists(self) -> bool:
        return True

    def sync_schema(self, layout: WorkbookLayout, meta: Mapping[str, RawCell]) -> list[str]:
        raise SnapshotReadOnly("the workbook can't be reached: it can't be synced now")


class Snapshots:
    """The snapshot files, one per module, in one folder."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, module: str) -> Path:
        return self.folder / f"{module}.json.gz"

    def load(self, module: str) -> Snapshot | None:
        """The module's snapshot, or None (missing, damaged, older format, another module)."""
        try:
            with gzip.open(self.path(module), "rt", encoding="utf-8") as file:
                doc = json.load(file)
            if doc.get("format") != FORMAT or doc.get("module") != module:
                return None
            return _decode(doc)
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            return None

    def save(self, snapshot: Snapshot) -> Path:
        """Write the snapshot atomically, readable by the owner only."""
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.path(snapshot.module)
        handle, temp = tempfile.mkstemp(dir=self.folder, prefix=f".{snapshot.module}-")
        try:
            with os.fdopen(handle, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as file:
                file.write(json.dumps(_encode(snapshot), ensure_ascii=False).encode("utf-8"))
            os.replace(temp, path)  # mkstemp made it 0600
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        return path

    def delete(self, module: str) -> None:
        self.path(module).unlink(missing_ok=True)


class CachedRepository:
    """A module's workbook through its snapshot (D-020).

    Reads come from the snapshot while the workbook hasn't changed since it was taken; when it
    has, the workbook is read again and a new snapshot saved. When the workbook can't be
    reached, the snapshot is used, read-only (`offline`). Writes go to the workbook; the next
    read takes a new snapshot.
    """

    def __init__(self, module: str, source: Repository, snapshots: Snapshots) -> None:
        self.module = module
        self.source = source
        self.snapshots = snapshots
        self.offline = False
        self._current: Snapshot | None = None

    @property
    def as_of(self) -> dt.datetime | None:
        """When the data in use was read ("data as of HH:MM")."""
        return self._current.read_at if self._current is not None else None

    def refresh(self) -> Snapshot:
        """The current data: from the snapshot if still fresh, else read and saved again."""
        cached = self._current or self.snapshots.load(self.module)
        try:
            modified = self.source.last_modified()
        except StorageError:
            if cached is None:
                raise
            self.offline, self._current = True, cached
            return cached
        self.offline = False
        if cached is None or cached.source_modified != modified:
            cached = take(self.module, self.source)
            self.snapshots.save(cached)
        self._current = cached
        return cached

    # ---- Repository ----

    def list_tables(self) -> list[str]:
        return SnapshotRepository(self.refresh()).list_tables()

    def read_table(self, name: str) -> Table:
        return SnapshotRepository(self.refresh()).read_table(name)

    def read_kv(self, name: str) -> dict[str, RawCell]:
        return SnapshotRepository(self.refresh()).read_kv(name)

    def last_modified(self) -> dt.datetime:
        return self.refresh().source_modified

    def apply(self, edits: Sequence[Edit]) -> list[int]:
        if self.offline:
            raise SnapshotReadOnly("the workbook can't be reached: changes can't be saved now")
        rows = self.source.apply(edits)
        self._current = None  # the workbook changed: read again
        return rows

    def write_kv(self, name: str, values: Mapping[str, RawCell]) -> None:
        if self.offline:
            raise SnapshotReadOnly("the workbook can't be reached: changes can't be saved now")
        self.source.write_kv(name, values)
        self._current = None

    def exists(self) -> bool:
        return self.source.exists()

    def sync_schema(self, layout: WorkbookLayout, meta: Mapping[str, RawCell]) -> list[str]:
        done = self.source.sync_schema(layout, meta)
        self._current = None
        return done


# ---- JSON ----


def _encode(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "module": snapshot.module,
        "source_modified": snapshot.source_modified.isoformat(),
        "read_at": snapshot.read_at.isoformat(),
        "tables": {
            name: {
                "columns": list(table.columns),
                "rows": [
                    [row.number, {k: _cell(v) for k, v in row.cells.items()}] for row in table.rows
                ],
            }
            for name, table in snapshot.tables.items()
        },
        "kv": {
            name: {k: _cell(v) for k, v in pairs.items()} for name, pairs in snapshot.kv.items()
        },
    }


def _decode(doc: Mapping[str, Any]) -> Snapshot:
    tables = {
        name: Table(
            name,
            tuple(table["columns"]),
            tuple(
                SheetRow(int(number), {k: _value(v) for k, v in cells.items()})
                for number, cells in table["rows"]
            ),
        )
        for name, table in doc["tables"].items()
    }
    kv = {name: {k: _value(v) for k, v in pairs.items()} for name, pairs in doc["kv"].items()}
    return Snapshot(
        doc["module"],
        dt.datetime.fromisoformat(doc["source_modified"]),
        dt.datetime.fromisoformat(doc["read_at"]),
        tables,
        kv,
    )


def _cell(value: RawCell) -> Any:
    """A cell as JSON: dates and times tagged, the rest as they are."""
    if isinstance(value, dt.datetime):
        return {"dt": value.isoformat()}
    if isinstance(value, dt.date):
        return {"d": value.isoformat()}
    if isinstance(value, dt.time):
        return {"t": value.isoformat()}
    if isinstance(value, dt.timedelta):
        return {"td": value.total_seconds()}
    return value


def _value(value: Any) -> RawCell:
    if isinstance(value, dict):
        ((tag, text),) = value.items()
        match tag:
            case "dt":
                return dt.datetime.fromisoformat(text)
            case "d":
                return dt.date.fromisoformat(text)
            case "t":
                return dt.time.fromisoformat(text)
            case "td":
                return dt.timedelta(seconds=text)
        raise ValueError(f"unknown cell tag {tag!r}")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError(f"not a cell: {value!r}")
