# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001, RUF002, RUF003  (the legacy labels use en dashes and the × sign)
"""A fictional legacy shoulder tracker for the tests (D-034, D-116): every value is invented.

The layout of the legacy `Shoulder_Program_Tracker_Fixed.xlsx` (00-current-state.md §3): the
tabs the importer reads, header rows 1-4, and the formulas of the computed columns copied down
(their structure read from the real workbook, no data). The plan's exercises are made up; the
data rows come from a seed, with the cases hand entry produces: a Monday (a legacy week starts
on the start date's weekday), a red flag, rising next-morning pain, a session of week 3 done in
week 4, a row with data but no date, an unreadable value, a decimal comma, Italian notes and gym
grades, retests at Start and end of week 4 only. `out_of_order` swaps two Check-in rows.

`python tests/fictional_shoulder.py FOLDER` (`make fixtures`) writes one, to open it.
"""

import datetime as dt
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

START = dt.date(2026, 9, 8)  # a Tuesday, as the real program's: Mondays end a legacy week
FIRST = 5
START_CELL = "'Start Here'!$C$6"
CHECKIN_LAST = 60  # formula rows on Check-in (the real one has 140)
QUALITY = ["Clean", "Some shrug/compensation", "Stopped early", "Skipped"]
ACTIVITIES = [
    "Climbing indoor",
    "Climbing outdoor",
    "Hangboard",
    "Session A",
    "Session B",
    "Rest day",
]
REASONS = [
    "Upper traps",
    "Front-shoulder pain",
    "Fingers",
    "Skin or tweak",
    "Other",
    "Did not stop",
]
NOTES = [
    "[ESEMPIO] Spalla un po' rigida",
    "[ESEMPIO] Tutto bene, perché no?",
    "'po' di fastidio davanti",  # starts with an apostrophe: kept as typed (04 §3b)
    None,
    None,
]
GRADES = ["6a", "6b+", "6", "5", None]  # French and gym numbers, as typed in the legacy sheet

PLAN_HEADER = [
    "ID",
    "Exercise",
    "Session",
    *(f"W{n}{'*' if n % 4 == 0 else ''}" for n in range(1, 13)),
    "Load rule",
]
LOG_HEADER = [
    "Week", "Session", "ID", "Exercise", "Prescribed", "Date", "Actual sets × reps", "Load (kg)",
    "RPE (1–10)", "Movement quality", "Pain during (0–10)", "Notes",
]  # fmt: skip
CHECKIN_HEADER = [
    "Date", "Week", "Activity", "Primer done?", "Upper-trap fatigue (0-10)",
    "Front-shoulder pain during (0-10)", "Front-shoulder pain next morning (0-10)",
    "Pec fatigue (0-10)", "Shrug / elbow flare", "Red-flag symptom?", "Hardest grade attempted",
    "Attempts before I stopped", "Main reason I stopped", "Status", "Action", "Notes",
    "Future-session review flag",
]  # fmt: skip
RETESTS_HEADER = [
    "Measure",
    "Start",
    "End week 4",
    "End week 8",
    "End week 12",
    "Change (W12 - start)",
    "What to look for",
]
# Each measure's validation, as on the real Retests rows 5-18.
MEASURES = [
    ("[ESEMPIO] Hang time (s)", "decimal"),
    ("[ESEMPIO] Pain on test?", "Yes,No"),
    ("[ESEMPIO] Clicking?", "Yes,No"),
    ("[ESEMPIO] Reach (cm)", "decimal"),
    ("[ESEMPIO] Reps to fatigue", "decimal"),
    ("[ESEMPIO] Main limiter", ",".join(REASONS)),
    ("[ESEMPIO] Hold time (s)", "decimal"),
    ("[ESEMPIO] Range (deg)", "decimal"),
    ("[ESEMPIO] Shrug on test", "Rarely,Sometimes,Often"),
    ("[ESEMPIO] Pull-ups", "decimal"),
    ("[ESEMPIO] Row load (kg)", "decimal"),
    ("[ESEMPIO] Press load (kg)", "decimal"),
    ("[ESEMPIO] Carry (m)", "decimal"),
    ("[ESEMPIO] Confident on overhang?", "Yes,No"),
]


def _status(r: int) -> str:
    return (
        f'=IF(A{r}="","",IF(J{r}="Yes","RED",IF(AND(F{r}="",G{r}=""),"",'
        f'IF(MAX(F{r},G{r})>=5,"RED",IF(MAX(F{r},G{r})>=3,"YELLOW","GREEN")))))'
    )


def _action(r: int) -> str:
    return (
        f'=IF(A{r}="","",IF(N{r}="RED","Do not progress; stop aggravating work and seek clinical '
        f'advice if persistent/severe",IF(N{r}="YELLOW","Hold/reduce load; review next-morning '
        f'response",IF(N{r}="GREEN","Progress only if movement quality is good and trend remains '
        f'stable",""))))'
    )


def _review(r: int) -> str:
    p, q = r - 1, r - 2
    return (
        f'=IF(A{r}="","",IF(J{r}="Yes","REVIEW NOW — red-flag symptom",'
        f'IF(OR(F{r}>=5,G{r}>=5),"REVIEW NOW — pain ≥5/10",'
        f'IF(OR(F{r}>=3,G{r}>=3),"REVIEW — pain ≥3/10",'
        f"IF(AND(ROW()>5,ISNUMBER(G{r}),ISNUMBER(G{p}),G{r}>G{p},G{r}>=2),"
        f'"REVIEW — next-morning pain rising",'
        f"IF(AND(ROW()>6,ISNUMBER(G{r}),ISNUMBER(G{p}),ISNUMBER(G{q}),G{r}>=G{p},G{p}>=G{q},G{r}>=2),"
        f'"REVIEW — repeated upward pain trend","OK — monitor"))))))'
    )


@dataclass
class LegacyShoulder:
    path: Path
    checkins: int  # rows with a date
    exercise_rows: int  # Session Log rows with a date
    retests: int  # filled checkpoint cells
    skipped: int  # rows with data but no date
    unread: int  # cells that can't be read


def legacy_shoulder(path: Path, seed: int, out_of_order: bool = False) -> LegacyShoulder:
    rng = random.Random(seed)
    book = openpyxl.Workbook()
    start_here = book.active
    assert isinstance(start_here, Worksheet)
    start_here.title = "Start Here"
    start_here["A1"] = "Shoulder training tracker"
    start_here["A4"] = "1. Enter your start date"
    start_here["A6"] = "Program start date (first training day)"
    start_here["C6"] = START
    plan = _plan(book.create_sheet("Plan"))
    exercise_rows, skipped, unread = _session_log(book.create_sheet("Session Log"), plan, rng)
    checkins, more_skipped, more_unread = _checkins(
        book.create_sheet("Check-in"), rng, out_of_order
    )
    retests = _retests(book.create_sheet("Retests"), rng)
    book.save(path)
    return LegacyShoulder(
        path, checkins, exercise_rows, retests, skipped + more_skipped, unread + more_unread
    )


def _headers(sheet: Worksheet, title: str, header: list[str]) -> None:
    sheet["A1"] = title
    sheet["A2"] = "[ESEMPIO] fictional tracker for the tests"
    for column, label in enumerate(header, start=1):
        sheet.cell(4, column, label)


def _plan(sheet: Worksheet) -> list[tuple[str, str]]:
    """17 made-up exercises: P1-P3 primer, A1-A7, B1-B7; (id, session) of each."""
    _headers(sheet, "12-week shoulder capacity plan", PLAN_HEADER)
    ids = [("P", "Primer", 3), ("A", "A", 7), ("B", "B", 7)]
    rows: list[tuple[str, str]] = []
    for prefix, session, count in ids:
        for n in range(1, count + 1):
            rows.append((f"{prefix}{n}", session))
    for i, (code, session) in enumerate(rows):
        r = FIRST + i
        sheet.cell(r, 1, code)
        sheet.cell(r, 2, f"[ESEMPIO] Exercise {code}")
        sheet.cell(r, 3, session)
        for week in range(1, 13):
            if code == "A7" and week < 5:
                text = "—"  # not started yet
            elif code == "B7" and week == 4:
                text = "Skip"
            else:
                text = f"{2 if week % 4 == 0 else 3}×{6 + week // 2}"
            sheet.cell(r, 3 + week, text)
        sheet.cell(r, 16, "[ESEMPIO] +1 kg when clean")
    return rows


def _session_log(
    sheet: Worksheet, plan: list[tuple[str, str]], rng: random.Random
) -> tuple[int, int, int]:
    """The 204 pre-generated rows (week × exercise), weeks 1-4 logged; week 3's B session done
    in week 4; week 5's A1 typed without a date; one unreadable pain value."""
    _headers(sheet, "Session log", LOG_HEADER)
    dated = skipped = unread = 0
    r = FIRST
    for week in range(1, 13):
        for code, session in plan:
            sheet.cell(r, 1, week)
            sheet.cell(r, 2, session)
            sheet.cell(r, 3, code)
            sheet.cell(r, 4, f"=INDEX(Plan!$B$5:$B$21,MATCH(C{r},Plan!$A$5:$A$21,0))")
            sheet.cell(r, 5, f"=INDEX(Plan!$D$5:$O$21,MATCH(C{r},Plan!$A$5:$A$21,0),A{r})")
            monday = START + dt.timedelta(days=7 * (week - 1))
            day: dt.date | None = None
            if week <= 4:
                day = monday + dt.timedelta(days=3 if session == "B" else 0)
                if week == 3 and session == "B":
                    day = monday + dt.timedelta(days=8)  # done late, in week 4 (a Wednesday)
            if day is not None:
                sheet.cell(r, 6, day)
                sheet.cell(r, 7, f"3×{rng.randint(6, 10)}")
                load: Any = rng.choice([0, 2.5, 5, "7,5"])  # "7,5": a decimal comma typed as text
                sheet.cell(r, 8, load)
                sheet.cell(r, 9, rng.randint(4, 8))
                sheet.cell(r, 10, rng.choice(QUALITY))
                sheet.cell(r, 11, rng.choice([0, 0, 1, 2, 3]))
                sheet.cell(r, 12, rng.choice(NOTES))
                dated += 1
            if week == 4 and code == "A2":
                sheet.cell(r, 11, "molto")  # not a number: left out and reported
                unread += 1
            if week == 5 and code == "A1":
                sheet.cell(r, 7, "3×8")  # done, but the date was never typed
                skipped += 1
            r += 1
    sheet.data_validations.append(
        DataValidation(type="list", formula1=f'"{",".join(QUALITY)}"', sqref=f"J5:J{r - 1}")
    )
    return dated, skipped, unread


def _checkins(sheet: Worksheet, rng: random.Random, out_of_order: bool) -> tuple[int, int, int]:
    """About 22 check-ins over five weeks (Mondays included), then a row with data but no date."""
    _headers(sheet, "How I feel: check-in", CHECKIN_HEADER)
    offsets = sorted({6, 13, 1, *rng.sample(range(35), 20)})  # 6, 13: Mondays
    rows: list[list[Any]] = []
    for offset in offsets:
        day = START + dt.timedelta(days=offset)
        rest = rng.random() < 0.15
        pains = [0, 1, 1, 2, 2, 3, 4, 5, None]
        rows.append(
            [
                day,
                None,  # Week: a formula
                "Rest day" if rest else rng.choice(ACTIVITIES[:5]),
                rng.choice(["Yes", "No", None]),
                None if rest else rng.choice(pains),
                None if rest else rng.choice(pains),
                rng.choice(pains),
                rng.choice(pains),
                rng.choice(["Rarely", "Sometimes", "Often", None]),
                "Yes" if rng.random() < 0.06 else rng.choice(["No", None]),
                None if rest else rng.choice(GRADES),
                rng.choice([0, 1, 2, 3, None]),
                rng.choice([*REASONS, None]),
                None,
                None,
                rng.choice(NOTES),
            ]
        )
    rows[3][9] = "Yes"  # a red flag, whatever the pain
    rows[4][4:8] = [1, 1, 1, 1]  # then rising next-morning pain: 1, 2, 2 (YELLOW only from 3)
    rows[5][4:8] = [1, 1, 2, 1]
    rows[6][4:8] = [1, 1, 2, 1]
    for row in rows[4:7]:
        row[9] = "No"
    if out_of_order:
        rows[8], rows[9] = rows[9], rows[8]
    for i, values in enumerate(rows):
        r = FIRST + i
        for column, value in enumerate(values, start=1):
            if value is not None:
                sheet.cell(r, column, value)
    sheet.cell(FIRST + 2, 5, "tanto")  # not a number: left out and reported
    blank = FIRST + len(rows)
    sheet.cell(blank, 6, 2)  # pain typed, no date
    for r in range(FIRST, CHECKIN_LAST + 1):
        sheet.cell(
            r,
            2,
            f'=IF(OR(A{r}="",{START_CELL}=""),"",MAX(0,INT((A{r}-{START_CELL})/7)+1))',
        )
        sheet.cell(r, 14, _status(r))
        sheet.cell(r, 15, _action(r))
        sheet.cell(r, 17, _review(r))
    return len(rows), 1, 1


def _retests(sheet: Worksheet, rng: random.Random) -> int:
    """The 14 measures, measured at Start and at the end of week 4."""
    _headers(sheet, "Retests & outcome measures", RETESTS_HEADER)
    filled = 0
    for i, (label, kind) in enumerate(MEASURES):
        r = FIRST + i
        sheet.cell(r, 1, label)
        sheet.cell(r, 6, f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(E{r})),E{r}-B{r},"")')
        sheet.cell(r, 7, "[ESEMPIO] steadier than before")
        if kind == "decimal":
            rule = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0")
            values: list[Any] = [rng.randint(5, 40), rng.randint(5, 40)]
        else:
            rule = DataValidation(type="list", formula1=f'"{kind}"')
            values = [rng.choice(kind.split(",")) for _ in range(2)]
        rule.add(f"B{r}:E{r}")
        sheet.data_validations.append(rule)
        for column, value in enumerate(values, start=2):
            sheet.cell(r, column, value)
            filled += 1
    return filled


def main(argv: list[str]) -> None:
    folder = Path(argv[1] if len(argv) > 1 else "tests/fixtures")
    folder.mkdir(parents=True, exist_ok=True)
    legacy_shoulder(folder / "legacy-shoulder.xlsx", seed=1)
    print(f"wrote {folder}/legacy-shoulder.xlsx (fictional)")


if __name__ == "__main__":
    main(sys.argv)
