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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from climblog.analytics.load import Other, training_load
from climblog.config import AppConfig, ConfigError, config_path, load_config
from climblog.expr import Value
from climblog.modules import Module, ModuleError
from climblog.modules.checks import recommendation_plan
from climblog.modules.compute import compute_module
from climblog.modules.forms import Day, due, hidden
from climblog.modules.recommend import Advice, Reason, recommend
from climblog.modules.schema import TrainingLoadWidget
from climblog.modules.summary import summarize, summary_plan
from climblog.storage import (
    CachedRepository,
    DataIssue,
    StorageError,
    load_data,
    read_settings,
)
from climblog.storage.cells import VALUE_ISSUES


@dataclass(frozen=True)
class EntityRecords:
    records: list[dict[str, Value]]  # stored values
    derived: list[dict[str, Value]]  # derived values, in the same order
    rows: list[dict[str, int]]  # where each record is: tab → sheet row
    issues: list[DataIssue]  # of the entity's tabs
    as_of: dt.datetime | None
    offline: bool


@dataclass(frozen=True)
class WeekLoad:
    """This week's training load on Today (06-ui, D-102): the module's first `training_load`
    widget, Monday to the day."""

    label: str  # the widget's, e.g. "Training load"
    load: float
    sessions: int
    without_load: int  # sessions missing duration or effort: counted as 0
    acwr: float | None  # the acute:chronic ratio on the day (None while building a baseline)
    zones: list[float]  # the widget's, for the ratio's wording
    others: list[tuple[str, float, int]]  # other modules' loads: (label, load, without a value)


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
        full, settings = self.full_tables(entry)
        advice = recommend(module, plan, full, settings, day)
        if summary_plan(module) is None:
            return advice
        # a reason may be a summary value (the weakest area): read with the summary's
        values = summarize(module, full, settings, day).values
        reasons = [Reason(r.name, r.label, values.get(r.name)) for r in advice.reasons]
        return replace(advice, reasons=reasons)

    def due(self, entry: Entry, day: dt.date) -> tuple[Day, WeekLoad | None]:
        """The module's forms on `day`: what is done and what is missing (D-080), and this
        week's load when the module has a `training_load` widget (D-102)."""
        assert entry.module is not None
        module = entry.module
        full, settings = self.full_tables(entry)
        widget = next(
            (
                w
                for view in (module.views or {}).values()
                for w in view
                if isinstance(w, TrainingLoadWidget)
            ),
            None,
        )
        week = None
        if widget is not None:
            found = training_load(module, widget, full, day, self.others(entry))
            if found["weeks"]:
                this = found["weeks"][-1]  # the week of the day
                week = WeekLoad(
                    widget.label or "Training load",
                    this["load"],
                    this["sessions"],
                    this["without_load"],
                    found["acwr_today"],
                    list(widget.zones),
                    [
                        (label, load, without)
                        for label, load, without in zip(
                            found["others"], this["others"], this["others_without"], strict=True
                        )
                    ],
                )
        return due(module, full, day, settings), week

    def others(self, entry: Entry) -> Other:
        """Another loaded module by its `module:` id, with its records (unreadable: none)."""

        def find(module_id: str) -> tuple[Module, Any] | None:
            for other in self.entries.values():
                if other.module is not None and other.module.module == module_id:
                    if other is entry or other.repo is None:
                        continue
                    try:
                        return other.module, self.full_tables(other)[0]
                    except StorageError:
                        return None
            return None

        return find

    def hidden(self, entry: Entry, entity: str, values: Mapping[str, Value]) -> list[str]:
        """The entity's fields a form hides for these values (`visible_if`, 03 §2.1b)."""
        assert entry.module is not None and entry.repo is not None
        settings = read_settings(entry.module, entry.repo.pinned())
        return hidden(entry.module, entity, values, settings)

    def full_tables(
        self, entry: Entry
    ) -> tuple[dict[str, list[dict[str, Value]]], dict[str, Value]]:
        """Every entity's records with their derived values (one look at the source), and the
        settings. A record with unreadable cells lists their fields under `VALUE_ISSUES`."""
        assert entry.module is not None and entry.repo is not None
        module = entry.module
        data = load_data(module, entry.repo.pinned())
        tables = {name: e.records for name, e in data.entities.items()}
        derived = compute_module(module, tables, data.settings)
        full = {
            name: [{**row, **values} for row, values in zip(rows, derived[name], strict=True)]
            for name, rows in tables.items()
        }
        unreadable: dict[tuple[str, int], list[str]] = {}
        for issue in data.issues:
            if issue.kind == "value" and issue.row is not None and issue.field is not None:
                unreadable.setdefault((issue.tab, issue.row), []).append(issue.field)
        if unreadable:
            for name, entity in data.entities.items():
                for row, places in zip(full[name], entity.places, strict=True):
                    fields = [f for place in places.items() for f in unreadable.get(place, [])]
                    if fields:
                        row[VALUE_ISSUES] = ",".join(fields)
        return full, data.settings

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
