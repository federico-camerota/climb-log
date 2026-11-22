# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001  (the legacy header labels use en dashes, as in "Mood (1-10)")
"""Import the legacy `Climbing_Journal.xlsx` into the journal module (00-current-state.md §1,
04-storage.md §5, D-061).

The legacy workbook is only read. Its layout is checked first (the header labels in row 4 of
every column read), then each `Session` row with a date becomes a session, with the values of
the same row in the other session tabs (they are linked to it by row), and each `Rest Days` row
a rest day. A second session on the same day gets `session_no` 2, and so on. The settings come
from the named ranges on `Start Here`.

Cells are read as the new module reads them (`parse_cell`); a value that can't be read is left
out and listed in the report (its place, never its content), and a row with data but no date
is skipped and listed. The parity report compares the values the legacy sheets computed with the
app's, column by column.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from climblog.expr import Value
from climblog.importers.legacy import (
    Column,
    ImportRefused,
    LegacyLayoutError,
    LegacyRecord,
    ParityColumn,
    RawValue,
    as_day,
    check_layout,
    compare,
    has_computed,
    open_legacy,
    read_cell,
    refuse_if_held,
    sheet,
    with_defaults,
)
from climblog.modules import Module
from climblog.modules.compute import compute_module
from climblog.storage import RecordWriter, Repository, sync_module
from climblog.storage.load import SETTINGS_TAB

__all__ = [
    "ImportRefused",
    "LegacyData",
    "LegacyLayoutError",
    "LegacyRecord",
    "ParityColumn",
    "RawValue",
    "import_legacy",
    "parity",
    "read_legacy",
]

WHAT = "climbing journal"
FIRST_ROW = 5  # legacy data rows start under four header rows

# Inputs: tab → (column, its row-4 label, the journal field). Labels as in the legacy file.
PARTS = ("fingers", "forearms", "shoulders", "wrists", "skin")
_SORE = [f"{p.capitalize()} (1–10 ↓)" for p in PARTS]
INPUTS: dict[str, list[Column]] = {
    "Session": [
        ("A", "Date", "date"),
        ("B", "Venue", "venue"),
        ("C", "Indoor / outdoor", "setting"),
        ("D", "Session type", "session_type"),
        ("E", "Partners", "partners"),
        ("F", "Duration (min)", "duration_min"),
        ("G", "Hardest grade tried", "hardest_grade"),
        ("H", "Notes", "notes"),
    ],
    "Wellbeing": [
        ("B", "Sleep (hours)", "wb_sleep_hours"),
        ("C", "Sleep quality (1–10)", "wb_sleep_quality"),
        ("D", "Mood (1–10)", "wb_mood_pre"),
        ("E", "Energy (1–10)", "wb_energy_pre"),
        ("F", "Pre-session note", "wb_note_pre"),
        ("G", "Post fatigue (1–10 ↓)", "wb_fatigue_post"),
        ("H", "Post mood (1–10)", "wb_mood_post"),
        ("I", "Recovery feel (1–10)", "wb_recovery_feel"),
        ("J", "Post-session note", "wb_note_post"),
    ],
    "Physical": [
        *((c, label, f"ph_pre_{p}") for c, label, p in zip("BCDEF", _SORE, PARTS, strict=True)),
        ("G", "Pre-session note", "ph_note_pre"),
        *((c, label, f"ph_post_{p}") for c, label, p in zip("HIJKL", _SORE, PARTS, strict=True)),
        ("M", "Post-session note", "ph_note_post"),
    ],
    "Mental": [
        ("B", "Life stress (1–10 ↓)", "mn_life_stress"),
        ("C", "Confidence (1–10)", "mn_confidence"),
        ("D", "Motivation (1–10)", "mn_motivation"),
        ("E", "Anxiety (1–10 ↓)", "mn_anxiety"),
        ("F", "Pre-session note", "mn_note_pre"),
        ("G", "Focus during (1–10)", "mn_focus"),
        ("H", "Commitment to falls (1–10)", "mn_fall_commitment"),
        ("I", "Fear response (1–10 ↓)", "mn_fear_response"),
        ("J", "Confidence on routes (1–10)", "mn_route_confidence"),
        ("K", "Approach mindset (1–10)", "mn_approach"),
        ("L", "Post-session note", "mn_note_post"),
    ],
    "Session Feel": [
        ("B", "Session outcome", "feel_outcome"),
        ("C", "Stuck to plan?", "feel_plan"),
        ("D", "Enjoyment (1–10)", "feel_enjoyment"),
        ("E", "Satisfaction (1–10)", "feel_satisfaction"),
        ("F", "Effort / energy used (1–10)", "feel_effort"),
        ("G", "Session note", "feel_note"),
    ],
    "Wins & Reflect": [
        ("B", "1 · What felt good", "rf_good"),
        ("C", "Score (1–10)", "rf_good_score"),
        ("D", "2 · What felt off", "rf_off"),
        ("E", "Severity (1–10 ↓)", "rf_off_severity"),
        ("F", "3 · What surprised you", "rf_surprise"),
        ("G", "Impact (1–10)", "rf_surprise_impact"),
        ("H", "4 · What would you change next time", "rf_change"),
        ("I", "Priority (1–10)", "rf_change_priority"),
        ("J", "Overall session score (1–10)", "rf_session_score"),
        ("K", "Win size", "rf_win_size"),
        ("L", "Win to bank", "rf_win"),
    ],
}
REST_TAB = "Rest Days"
REST_INPUTS: list[Column] = [
    ("A", "Date", "date"),
    ("B", "Rest type", "rest_type"),
    ("C", "Activity", "activity"),
    ("D", "Sleep (hours)", "sleep_hours"),
    ("E", "Sleep quality (1–10)", "sleep_quality"),
    ("F", "Mood (1–10)", "mood"),
    ("G", "Energy (1–10)", "energy"),
    ("H", "Motivation to climb (1–10)", "motivation"),
    ("I", "Life stress (1–10 ↓)", "life_stress"),
    *((c, label, f"body_{p}") for c, label, p in zip("JKLMN", _SORE, PARTS, strict=True)),
    ("O", "Note", "note"),
]
# What the legacy sheets computed: tab → (column, label, the journal's derived field).
COMPUTED: dict[str, list[Column]] = {
    "Session": [
        ("I", "Overall status (all tabs)", "overall_status"),
        ("J", "Log check", "log_check"),
        ("K", "Weekday", "weekday"),
        ("L", "Month", "month"),
        ("M", "Days since previous", "days_since_prev"),
    ],
    "Wellbeing": [
        ("K", "Pre status", "wb_pre_status"),
        ("L", "Post status", "wb_post_status"),
        ("M", "Wellbeing score", "wb_score"),
        ("N", "Wellbeing status", "wb_status"),
    ],
    "Physical": [
        ("N", "Pre-session readiness", "ph_readiness"),
        ("O", "Physical status", "ph_status"),
    ],
    "Mental": [("M", "Mental score", "mn_score"), ("N", "Mental status", "mn_status")],
    "Session Feel": [
        ("H", "Feel score", "feel_score"),
        ("I", "Feel status", "feel_status"),
        ("J", "Overall score", "overall_score"),
        ("K", "Overall status (all tabs)", "overall_status"),
    ],
    "Wins & Reflect": [("M", "Reflection status", "reflect_status")],
}
REST_COMPUTED: list[Column] = [
    ("P", "Wellbeing score", "wellbeing_score"),
    ("Q", "Body readiness", "body_readiness"),
    ("R", "Wellbeing status", "wellbeing_status"),
    ("S", "Body status", "body_status"),
    ("T", "Rest-day status", "status"),
    ("U", "Weekday", "weekday"),
    ("V", "Days since last climb", "days_since_climb"),
]
SETTINGS = {
    "LowMax": "low_max",
    "WatchMax": "watch_max",
    "AttnMin": "attn_min",
    "NoteMin": "note_min",
    "TrendDelta": "trend_delta",
}
# Legacy rules that differ on purpose: shown in the parity report, not counted as mismatches.
KNOWN = {
    ("rest_day", "days_since_climb"): "the legacy sheet counts a session on the same day, "
    "the app only earlier days (D-045)",
    ("session", "days_since_prev"): "the legacy sheet looks at the rows above, the app at "
    "earlier dates: they differ where rows are not in date order",
}


@dataclass
class LegacyData:
    records: list[LegacyRecord]
    settings: dict[str, Value]
    skipped: list[str]  # rows left out, by place
    unread: list[str]  # values that couldn't be read, by place (never their content)

    def count(self, entity: str) -> int:
        return sum(1 for r in self.records if r.entity == entity)

    @property
    def computed(self) -> bool:
        """Whether the workbook holds the values its formulas computed (`has_computed`)."""
        return has_computed(self.records)


def read_legacy(path: Path, module: Module) -> LegacyData:
    """Every record of a legacy journal workbook, and the values its sheets computed."""
    book = open_legacy(path)
    sheets = {name: sheet(book, name, WHAT) for name in [*INPUTS, REST_TAB]}
    for name, columns in [*INPUTS.items(), (REST_TAB, REST_INPUTS)]:
        check_layout(sheets[name], [*columns, *COMPUTED.get(name, []), *_rest_computed(name)], WHAT)
    data = LegacyData([], _settings(book, module), [], [])
    sessions = module.entities["session"]
    counts: dict[dt.date, int] = {}
    last = max(sheet.max_row for name, sheet in sheets.items() if name != REST_TAB)
    for row in range(FIRST_ROW, last + 1):
        day = as_day(sheets["Session"].cell(row, 1).value)
        values: dict[str, Value] = {}
        has_data = False
        for tab, columns in INPUTS.items():
            for column, _, name in columns:
                if name == "date":
                    continue
                raw = sheets[tab][f"{column}{row}"].value
                has_data = has_data or raw not in (None, "")
                value = _read(module, sessions.fields[name], raw, f"{tab}!{column}{row}", data)
                if value is not None:
                    values[name] = value
        if day is None:
            if has_data:
                data.skipped.append(f"Session row {row}: data in the session tabs but no date")
            continue
        counts[day] = counts.get(day, 0) + 1
        record = LegacyRecord(
            "session",
            {"date": day, "session_no": counts[day], **values},
            dict.fromkeys(INPUTS, row),
        )
        for tab, columns in COMPUTED.items():
            for column, _, name in columns:
                record.computed[name] = sheets[tab][f"{column}{row}"].value
        data.records.append(record)
    rest = sheets[REST_TAB]
    rest_days = module.entities["rest_day"]
    for row in range(FIRST_ROW, rest.max_row + 1):
        day = as_day(rest.cell(row, 1).value)
        values = {}
        has_data = False
        for column, _, name in REST_INPUTS[1:]:
            raw = rest[f"{column}{row}"].value
            has_data = has_data or raw not in (None, "")
            value = _read(module, rest_days.fields[name], raw, f"{REST_TAB}!{column}{row}", data)
            if value is not None:
                values[name] = value
        if day is None:
            if has_data:
                data.skipped.append(f"Rest Days row {row}: data but no date")
            continue
        record = LegacyRecord("rest_day", {"date": day, **values}, {REST_TAB: row})
        for column, _, name in REST_COMPUTED:
            record.computed[name] = rest[f"{column}{row}"].value
        data.records.append(record)
    return data


@dataclass
class ImportReport:
    counts: dict[str, int]
    settings: dict[str, Value]
    skipped: list[str]
    unread: list[str]


def import_legacy(path: Path, module: Module, repo: Repository) -> ImportReport:
    """Write a legacy journal into an empty (or new) journal workbook, in one save."""
    refuse_if_held(module, repo, "journal")
    legacy = read_legacy(path, module)
    sync_module(module, repo)
    RecordWriter(module, repo).add_many([(r.entity, r.values) for r in legacy.records])
    repo.write_kv(SETTINGS_TAB, legacy.settings)
    return ImportReport(
        {name: legacy.count(name) for name in ("session", "rest_day")},
        legacy.settings,
        legacy.skipped,
        legacy.unread,
    )


def parity(legacy: LegacyData, module: Module) -> list[ParityColumn]:
    """The legacy computed values against the app's, per derived field."""
    tables: dict[str, list[Mapping[str, Value]]] = {}
    for record in legacy.records:
        tables.setdefault(record.entity, []).append(record.values)
    derived = compute_module(module, tables, with_defaults(module, legacy.settings))
    return compare(legacy.records, derived, lambda entity, name: KNOWN.get((entity, name)))


# ---- Reading cells ----


def _rest_computed(name: str) -> list[Column]:
    return REST_COMPUTED if name == REST_TAB else []


def _read(module: Module, field: Any, raw: object, place: str, data: LegacyData) -> Value:
    return read_cell(module, field, raw, place, data.unread)


def _settings(book: Any, module: Module) -> dict[str, Value]:
    """The named settings' values; a missing or unreadable one keeps the module default."""
    values: dict[str, Value] = {}
    for legacy, key in SETTINGS.items():
        defined = book.defined_names.get(legacy)
        if defined is None:
            continue
        for title, cell in defined.destinations:
            value = book[title][cell.replace("$", "")].value
            if isinstance(value, int | float) and not isinstance(value, bool):
                values[key] = value
    return values
