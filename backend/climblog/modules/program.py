# SPDX-License-Identifier: GPL-3.0-or-later
"""Program runs and weeks (03-module-framework.md §2.4, D-109).

A program module's runs start on ISO weeks typed in the workbook's Runs tab (`2026-W42`): week 1
of a run starts on that week's Monday. A record belongs to the latest run that started on or
before its date; its program week counts whole weeks from that Monday and goes on after the
program's last week (13, 14…, with no phase). Before the first run there is no run and no week.
The sheet's formulas compute the same (`modules/formulas.py`).
"""

import bisect
import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass

from climblog.modules.schema import Module, Program

RUNS_TAB = "Runs"
PROGRAM_NAMES = ("run", "week", "phase", "is_light_week")
"""The values `program.<name>` gives a record."""
AUTO_COLUMNS = ("run", "week")
"""Derived values every dated entity of a program module gets: `program.run`, `program.week`."""

_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def parse_week(text: str) -> dt.date:
    """The Monday of an ISO week written `2026-W42`. Raises ValueError with a message for the
    user."""
    found = _WEEK.match(text.strip())
    if found is None:
        raise ValueError(f"'{text}' is not a week like 2026-W42")
    year, week = int(found[1]), int(found[2])
    try:
        return dt.date.fromisocalendar(year, week, 1)
    except ValueError:
        weeks = dt.date(year, 12, 28).isocalendar().week  # 28 Dec is always in the last week
        raise ValueError(f"{year} has weeks 1 to {weeks}, not {week}") from None


def week_text(day: dt.date) -> str:
    """The ISO week of a day, written as in the Runs tab (`2026-W42`)."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


@dataclass(frozen=True)
class Run:
    number: int
    start_week: str  # as typed, `2026-W42`
    start: dt.date  # its Monday


@dataclass(frozen=True)
class Position:
    run: int
    week: int


class Runs:
    """The runs of a program, by start (`load_data` reports the rows it can't use)."""

    def __init__(self, runs: Sequence[Run] = ()) -> None:
        self.runs = sorted(runs, key=lambda r: r.start)
        self._starts = [r.start for r in self.runs]

    def at(self, day: dt.date | None) -> Position | None:
        """The run and week of a day: the latest run started on or before it."""
        if day is None:
            return None
        if isinstance(day, dt.datetime):
            day = day.date()
        i = bisect.bisect_right(self._starts, day) - 1
        if i < 0:
            return None
        run = self.runs[i]
        return Position(run.number, (day - run.start).days // 7 + 1)

    def value(self, program: Program, name: str, day: dt.date | None) -> int | str | bool | None:
        """`program.<name>` for a record dated `day`."""
        found = self.at(day)
        week = found.week if found else None
        match name:
            case "run":
                return found.run if found else None
            case "week":
                return week
            case "phase":
                return program.phase(week)
            case _:
                return program.is_light_week(week)

    def next_number(self) -> int:
        return max((r.number for r in self.runs), default=0) + 1


NO_RUNS = Runs()


def with_program_columns(module: Module) -> Module:
    """A program module's entities with `run` and `week` derived first (`program.run`,
    `program.week`), so every row shows them in the sheet and the app. A field already called
    so is left alone (`cross_check` reports it)."""
    if module.program is None:
        return module
    entities = {}
    for name, entity in module.entities.items():
        auto = {
            key: f"program.{key}"
            for key in AUTO_COLUMNS
            if key not in entity.fields and key not in entity.derived
        }
        entities[name] = entity.model_copy(update={"derived": {**auto, **entity.derived}})
    return module.model_copy(update={"entities": entities})
