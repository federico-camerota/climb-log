# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001, RUF002, RUF003  (the legacy labels use en dashes and the × sign)
"""Import the legacy `Shoulder_Program_Tracker_Fixed.xlsx` into the shoulder module
(00-current-state.md §3, 04-storage.md §8, D-116).

The legacy workbook is only read. Its layout is checked first (the row-4 labels of every column
read, and the start-date label on `Start Here`), then:
- the start date (`Start Here!C6`) gives run 1, starting the ISO week of that date;
- `Plan` → the `exercises` reference table, with the prescription of each week;
- `Session Log` → `exercise_log`: each row with a date (the pre-generated rows without one are
  not records), its typed week kept as `plan_week`, so it keeps its prescription;
- `Check-in` → `checkin`, one per date;
- `Retests` → the `retest_measures` table (ids M1, M2…, the value type from the row's data
  validation) and a `retest` row per filled checkpoint, dated from the program weeks: Start
  on the start date, End week n on its last day (start + 7n − 1).

Cells are read as the module reads them (`parse_cell`); a value that can't be read is left out
and listed (its place, never its content), and a row with data but no date is skipped and
listed. A date twice on `Check-in`, or a date and exercise twice on `Session Log`, refuses the
import: one check-in a day, one row per exercise a day. The parity report compares what the
legacy sheets computed (week, status, action, review flag, prescribed) with the app's.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from climblog.expr import Value
from climblog.importers.legacy import (
    Column,
    LegacyLayoutError,
    LegacyRecord,
    ParityColumn,
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
from climblog.modules.program import Run, Runs, parse_week, week_text
from climblog.modules.reference import reference_columns
from climblog.storage import RecordWriter, Repository, StorageError, sync_module

WHAT = "shoulder tracker"
FIRST_ROW = 5  # legacy data rows start under four header rows
START_TAB, START_LABEL, START_CELL = "Start Here", "Program start date (first training day)", "C6"
WEEKS = 12

PLAN_TAB = "Plan"
PLAN: list[Column] = [
    ("A", "ID", "id"),
    ("B", "Exercise", "name"),
    ("C", "Session", "session"),
    *(
        (column, f"W{n}{'*' if n % 4 == 0 else ''}", f"w{n}")
        for n, column in enumerate("DEFGHIJKLMNO", start=1)
    ),
    ("P", "Load rule", "load_rule"),
]
LOG_TAB = "Session Log"
LOG: list[Column] = [
    ("A", "Week", "plan_week"),
    ("C", "ID", "exercise_id"),
    ("F", "Date", "date"),
    ("G", "Actual sets × reps", "actual"),
    ("H", "Load (kg)", "load_kg"),
    ("I", "RPE (1–10)", "rpe"),
    ("J", "Movement quality", "quality"),
    ("K", "Pain during (0–10)", "pain_during"),
    ("L", "Notes", "notes"),
]
LOG_COMPUTED: list[Column] = [("E", "Prescribed", "prescribed")]
CHECKIN_TAB = "Check-in"
CHECKIN: list[Column] = [
    ("A", "Date", "date"),
    ("C", "Activity", "activity"),
    ("D", "Primer done?", "primer_done"),
    ("E", "Upper-trap fatigue (0-10)", "trap_fatigue"),
    ("F", "Front-shoulder pain during (0-10)", "pain_during"),
    ("G", "Front-shoulder pain next morning (0-10)", "pain_next_am"),
    ("H", "Pec fatigue (0-10)", "pec_fatigue"),
    ("I", "Shrug / elbow flare", "shrug_flare"),
    ("J", "Red-flag symptom?", "red_flag"),
    ("K", "Hardest grade attempted", "hardest_grade"),
    ("L", "Attempts before I stopped", "attempts_before_stop"),
    ("M", "Main reason I stopped", "stop_reason"),
    ("P", "Notes", "notes"),
]
CHECKIN_COMPUTED: list[Column] = [
    ("B", "Week", "week"),
    ("N", "Status", "status"),
    ("O", "Action", "action"),
    ("Q", "Future-session review flag", "review_flag"),
]
RETESTS_TAB = "Retests"
RETESTS: list[Column] = [
    ("A", "Measure", "label"),
    ("B", "Start", "Start"),
    ("C", "End week 4", "End W4"),
    ("D", "End week 8", "End W8"),
    ("E", "End week 12", "End W12"),
    ("G", "What to look for", "guidance"),
]
CHECKPOINT_WEEK = {"Start": 0, "End W4": 4, "End W8": 8, "End W12": 12}

WEEK_KNOWN = (
    "the legacy weeks start on the start date's weekday, the app's on Monday (D-109), so a "
    "day before that weekday counts one week less in the app"
)
ORDER_KNOWN = (
    "the legacy sheet compares with the rows above, the app with the earlier dates: they "
    "differ where Check-in rows are not in date order"
)


class LegacyDataError(StorageError):
    """Legacy rows the module can't hold as they are (a date twice): fix them, then import."""


@dataclass
class LegacyShoulder:
    start: dt.date  # the program start date (Start Here)
    records: list[LegacyRecord]
    reference: dict[str, list[dict[str, Value]]]
    skipped: list[str]  # rows left out, by place
    unread: list[str]  # values that couldn't be read, by place (never their content)
    in_date_order: bool = True  # Check-in rows
    notes: list[str] = field(default_factory=list)  # what the import decided, for the report

    @property
    def start_week(self) -> str:
        return week_text(self.start)

    def count(self, entity: str) -> int:
        return sum(1 for r in self.records if r.entity == entity)

    @property
    def computed(self) -> bool:
        return has_computed(self.records)


def read_legacy_shoulder(path: Path, module: Module) -> LegacyShoulder:
    """Every record and reference row of a legacy shoulder workbook, and what it computed."""
    book = open_legacy(path)
    start_here = sheet(book, START_TAB, WHAT)
    sheets = {name: sheet(book, name, WHAT) for name in (PLAN_TAB, LOG_TAB, CHECKIN_TAB)}
    sheets[RETESTS_TAB] = sheet(book, RETESTS_TAB, WHAT)
    check_layout(start_here, [("A", START_LABEL, "")], WHAT, row=6)
    check_layout(sheets[PLAN_TAB], PLAN, WHAT)
    check_layout(sheets[LOG_TAB], [*LOG, *LOG_COMPUTED], WHAT)
    check_layout(sheets[CHECKIN_TAB], [*CHECKIN, *CHECKIN_COMPUTED], WHAT)
    check_layout(sheets[RETESTS_TAB], RETESTS, WHAT)
    start = as_day(start_here[START_CELL].value)
    if start is None:
        raise LegacyLayoutError(
            f"{START_TAB}!{START_CELL} holds no start date: the program's run needs one"
        )
    data = LegacyShoulder(start, [], {}, [], [])
    data.reference["exercises"] = _plan(sheets[PLAN_TAB], module, data)
    _session_log(sheets[LOG_TAB], module, data)
    _checkins(sheets[CHECKIN_TAB], module, data)
    _retests(sheets[RETESTS_TAB], module, data)
    return data


@dataclass
class ShoulderImportReport:
    start_week: str
    counts: dict[str, int]  # entity or reference table → rows written
    skipped: list[str]
    unread: list[str]
    notes: list[str]


def import_legacy_shoulder(path: Path, module: Module, repo: Repository) -> ShoulderImportReport:
    """Write a legacy shoulder tracker into an empty (or new) shoulder workbook, in one save:
    run 1, the reference rows and the records."""
    refuse_if_held(module, repo, "shoulder")
    legacy = read_legacy_shoulder(path, module)
    sync_module(module, repo)
    RecordWriter(module, repo).add_many(
        [(r.entity, r.values) for r in legacy.records],
        runs=[legacy.start_week],
        reference=legacy.reference,
    )
    counts = {name: len(rows) for name, rows in legacy.reference.items()}
    counts |= {name: legacy.count(name) for name in ("checkin", "exercise_log", "retest")}
    return ShoulderImportReport(
        legacy.start_week, counts, legacy.skipped, legacy.unread, legacy.notes
    )


def parity_shoulder(legacy: LegacyShoulder, module: Module) -> list[ParityColumn]:
    """The legacy computed values against the app's, per derived field."""
    tables: dict[str, list[dict[str, Value]]] = {}
    for record in legacy.records:
        tables.setdefault(record.entity, []).append(record.values)
    runs = Runs([Run(1, legacy.start_week, parse_week(legacy.start_week))])
    derived = compute_module(module, tables, with_defaults(module, {}), runs, legacy.reference)

    def known(entity: str, name: str) -> str | None:
        if (entity, name) == ("checkin", "week"):
            return WEEK_KNOWN
        if (entity, name) == ("checkin", "review_flag") and not legacy.in_date_order:
            return ORDER_KNOWN
        return None

    columns = compare(legacy.records, derived, known)
    for column in columns:
        if column.known == WEEK_KNOWN and not all(
            _legacy_week(legacy.start, day) == sheet_value
            for day, sheet_value, _ in column.mismatches
        ):
            column.known = None  # a difference the week rules don't explain
    return columns


def _legacy_week(start: dt.date, day: dt.date) -> int:
    """The legacy Check-in week: whole weeks from the start date, plus one (0 before it)."""
    return max(0, (day - start).days // 7 + 1)


# ---- Tabs ----


def _plan(tab: Worksheet, module: Module, data: LegacyShoulder) -> list[dict[str, Value]]:
    """The exercises, one per row with an ID."""
    columns = reference_columns(module, "exercises")
    rows: list[dict[str, Value]] = []
    for row in range(FIRST_ROW, tab.max_row + 1):
        if tab[f"A{row}"].value in (None, ""):
            continue
        values: dict[str, Value] = {}
        for column, _, name in PLAN:
            raw = tab[f"{column}{row}"].value
            if name == "session" and isinstance(raw, str):
                raw = raw.strip().removeprefix("Session ").strip()  # "Session A" → "A"
            value = read_cell(module, columns[name], raw, f"{PLAN_TAB}!{column}{row}", data.unread)
            if value is not None:
                values[name] = value
        rows.append(values)
    return rows


def _session_log(tab: Worksheet, module: Module, data: LegacyShoulder) -> None:
    fields = module.entities["exercise_log"].fields
    seen: dict[tuple[dt.date, str], int] = {}
    for row in range(FIRST_ROW, tab.max_row + 1):
        day = as_day(tab[f"F{row}"].value)
        actual = [c for c, _, name in LOG if name not in ("plan_week", "exercise_id", "date")]
        has_data = any(tab[f"{c}{row}"].value not in (None, "") for c in actual)
        if day is None:
            if has_data:
                data.skipped.append(f"{LOG_TAB} row {row}: data but no date")
            continue
        values = _values(tab, row, LOG, fields, module, data, LOG_TAB)
        exercise = values.get("exercise_id")
        if not isinstance(exercise, str):
            data.skipped.append(f"{LOG_TAB} row {row}: a date but no exercise ID")
            continue
        twice = seen.setdefault((day, exercise.casefold()), row)
        if twice != row:
            raise LegacyDataError(
                f"{LOG_TAB} rows {twice} and {row} have the same date and exercise: one row per "
                "exercise a day; merge them in the legacy file, then import"
            )
        record = LegacyRecord("exercise_log", {"date": day, **values}, {LOG_TAB: row})
        for column, _, name in LOG_COMPUTED:
            record.computed[name] = tab[f"{column}{row}"].value
        data.records.append(record)


def _checkins(tab: Worksheet, module: Module, data: LegacyShoulder) -> None:
    fields = module.entities["checkin"].fields
    seen: dict[dt.date, int] = {}
    last: dt.date | None = None
    for row in range(FIRST_ROW, tab.max_row + 1):
        day = as_day(tab[f"A{row}"].value)
        values = _values(tab, row, CHECKIN, fields, module, data, CHECKIN_TAB)
        if day is None:
            if values or any(tab[f"{c}{row}"].value not in (None, "") for c, _, _ in CHECKIN):
                data.skipped.append(f"{CHECKIN_TAB} row {row}: data but no date")
            continue
        twice = seen.setdefault(day, row)
        if twice != row:
            raise LegacyDataError(
                f"{CHECKIN_TAB} rows {twice} and {row} have the same date: one check-in a day; "
                "merge them in the legacy file, then import"
            )
        if last is not None and day < last:
            data.in_date_order = False
        last = day
        record = LegacyRecord("checkin", {"date": day, **values}, {CHECKIN_TAB: row})
        for column, _, name in CHECKIN_COMPUTED:
            record.computed[name] = tab[f"{column}{row}"].value
        data.records.append(record)


def _retests(tab: Worksheet, module: Module, data: LegacyShoulder) -> None:
    """The measures (ids M1, M2… in row order) and a retest row per filled checkpoint."""
    columns = reference_columns(module, "retest_measures")
    value_field = module.entities["retest"].fields["value"]
    measures: list[dict[str, Value]] = []
    for row in range(FIRST_ROW, tab.max_row + 1):
        label = tab[f"A{row}"].value
        if label in (None, ""):
            continue
        key = f"M{len(measures) + 1}"
        measure: dict[str, Value] = {"id": key}
        for column, name in (("A", "label"), ("G", "guidance")):
            raw = tab[f"{column}{row}"].value
            place = f"{RETESTS_TAB}!{column}{row}"
            value = read_cell(module, columns[name], raw, place, data.unread)
            if value is not None:
                measure[name] = value
        measure |= _value_type(tab, row)
        measures.append(measure)
        for column, _, checkpoint in RETESTS[1:5]:
            place = f"{RETESTS_TAB}!{column}{row}"
            raw = tab[f"{column}{row}"].value
            value = read_cell(module, value_field, raw, place, data.unread)
            if value is None:
                continue
            day = data.start + dt.timedelta(days=max(0, 7 * CHECKPOINT_WEEK[checkpoint] - 1))
            values: dict[str, Value] = {
                "date": day,
                "checkpoint": checkpoint,
                "measure_id": key,
                "value": value,
            }
            data.records.append(LegacyRecord("retest", values, {RETESTS_TAB: row}))
    data.reference["retest_measures"] = measures
    if any(r.entity == "retest" for r in data.records):
        data.notes.append(
            "retests dated from the program weeks: Start on the start date, End week n on "
            "its last day (D-116); change a date in the sheet if it was another day"
        )


def _value_type(tab: Worksheet, row: int) -> dict[str, Value]:
    """A measure's value type from the data validation of its Start cell: a decimal is a
    number, Yes/No a bool, another list a choice (with its values)."""
    cell = f"B{row}"
    for rule in tab.data_validations.dataValidation:
        if cell not in rule.sqref:
            continue
        if rule.type in ("decimal", "whole"):
            return {"value_type": "number"}
        if rule.type == "list" and rule.formula1:
            choices = [c.strip() for c in rule.formula1.strip('"').split(",")]
            if sorted(c.casefold() for c in choices) == ["no", "yes"]:
                return {"value_type": "bool"}
            return {"value_type": "choice", "choices": ", ".join(choices)}
    return {}


def _values(
    tab: Worksheet,
    row: int,
    columns: Sequence[Column],
    fields: dict[str, Any],
    module: Module,
    data: LegacyShoulder,
    name: str,
) -> dict[str, Value]:
    values: dict[str, Value] = {}
    for column, _, key in columns:
        if key == "date":
            continue
        place = f"{name}!{column}{row}"
        value = read_cell(module, fields[key], tab[f"{column}{row}"].value, place, data.unread)
        if value is not None:
            values[key] = value
    return values
