# SPDX-License-Identifier: GPL-3.0-or-later
"""The modules the app serves: the app config, each module's YAML and its data (D-058).

Loaded on the first API request, not when the app is built, so the app starts (and its tests
run) without a config. A module whose YAML doesn't load is listed with its problems; reading its
records is refused. Data is read through each module's local snapshot (`CachedRepository`,
D-055), and its derived values are computed on every read. Writes to one module go one at a time
(`Entry.lock`).
"""

import datetime as dt
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from climblog.config import AppConfig, ConfigError, config_path, load_config
from climblog.expr import Value
from climblog.modules import Module, ModuleError
from climblog.modules.checks import recommendation_plan
from climblog.modules.compute import compute_module
from climblog.modules.recommend import Advice, recommend
from climblog.storage import CachedRepository, DataIssue, load_data


@dataclass(frozen=True)
class EntityRecords:
    records: list[dict[str, Value]]  # stored values
    derived: list[dict[str, Value]]  # derived values, in the same order
    rows: list[dict[str, int]]  # where each record is: tab → sheet row
    issues: list[DataIssue]  # of the entity's tabs
    as_of: dt.datetime | None
    offline: bool


@dataclass
class Entry:
    """One configured module: its definition (or why it didn't load) and its data."""

    name: str
    module: Module | None
    problems: list[str] = field(default_factory=list)
    repo: CachedRepository | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)  # one write at a time


class Catalog:
    def __init__(self, config: AppConfig, problems: list[str] | None = None) -> None:
        self.config = config
        self.problems = problems or []  # the config's own problems
        self.entries: dict[str, Entry] = {}
        for name in config.modules:
            try:
                module = config.module(name)
            except ModuleError as error:
                self.entries[name] = Entry(name, None, error.lines())
            except (ValueError, OSError) as error:
                self.entries[name] = Entry(name, None, [str(error)])
            else:
                self.entries[name] = Entry(name, module, [], config.cached(name))

    @classmethod
    def from_file(cls, file: Path | None = None) -> "Catalog":
        """From the app config (`config_path()`); a missing or broken one serves no modules."""
        path = config_path(file)
        try:
            return cls(load_config(path))
        except ConfigError as error:
            return cls(AppConfig(), error.lines())

    def records(self, entry: Entry, entity: str) -> EntityRecords:
        """The entity's records with their derived values. Raises `StorageError` when neither
        the workbook nor a snapshot can be read."""
        assert entry.module is not None and entry.repo is not None
        module = entry.module
        data = load_data(module, entry.repo.pinned())  # one look at the source
        tables = {name: e.records for name, e in data.entities.items()}
        derived = compute_module(module, tables, data.settings)
        tabs = set(module.entities[entity].tab_fields())
        found = data.entities[entity]
        return EntityRecords(
            found.records,
            derived[entity],
            found.places,
            [issue for issue in data.issues if issue.tab in tabs],
            entry.repo.as_of,
            entry.repo.offline,
        )

    def advice(self, entry: Entry, day: dt.date) -> Advice | None:
        """The module's recommendation for `day` (D-076), if it has one. Raises `StorageError`
        when neither the workbook nor a snapshot can be read."""
        assert entry.module is not None and entry.repo is not None
        module = entry.module
        plan = recommendation_plan(module)
        if plan is None:
            return None
        data = load_data(module, entry.repo.pinned())
        tables = {name: e.records for name, e in data.entities.items()}
        derived = compute_module(module, tables, data.settings)
        full = {
            name: [{**row, **values} for row, values in zip(rows, derived[name], strict=True)]
            for name, rows in tables.items()
        }
        return recommend(module, plan, full, data.settings, day)

    def record(
        self, entry: Entry, entity: str, key: Sequence[Value]
    ) -> tuple[EntityRecords, int] | None:
        """The entity's records and the index of the one with this key, if it is there."""
        assert entry.module is not None
        parts = entry.module.entities[entity].key or []
        found = self.records(entry, entity)
        for index, values in enumerate(found.records):
            if tuple(values.get(part) for part in parts) == tuple(key):
                return found, index
        return None


_LOADING = threading.Lock()


def served(state: Any) -> Catalog:
    """The app's catalog (`app.state.catalog`), loaded from the app config on first use; the
    API and the poller share it."""
    with _LOADING:
        if getattr(state, "catalog", None) is None:
            state.catalog = Catalog.from_file()
        found: Catalog = state.catalog
        return found
