# SPDX-License-Identifier: GPL-3.0-or-later
"""The dashboard's status board against the legacy `Summary - Trends` formulas (D-083), on
LibreOffice. Fictional sessions are written into a workbook shaped as the legacy journal (its
columns only), with the legacy status-board and chart-data formulas as they were (read once from
the owner's legacy workbook with permission: formulas only); the app must show the same numbers.
One session a day: the legacy MATCH by date reads a day's first session for both (D-076)."""

import datetime as dt
import os
import random
import tempfile
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from openpyxl.worksheet.formula import ArrayFormula
from parity import recalculate, soffice, work_dir

from climblog.analytics import compute_view
from climblog.expr import Value
from climblog.modules import load_module
from climblog.modules.schema import MonthlyWidget, StatusBoardWidget

JOURNAL = load_module(Path(__file__).parent.parent / "modules" / "journal.yaml")
REQUIRED = bool(os.environ.get("CLIMBLOG_REQUIRE_SOFFICE"))
pytestmark = pytest.mark.skipif(soffice() is None and not REQUIRED, reason="no working LibreOffice")

# Legacy columns (00-current-state §1): data from row 5, the date in column A of every tab.
SOURCES = {  # chart-data column → (tab, column)
    "D": ("Wellbeing", "M"),  # wellbeing score
    "E": ("Physical", "N"),  # readiness
    "F": ("Mental", "M"),
    "G": ("Session Feel", "H"),  # feel score
    "H": ("Session Feel", "J"),  # overall score
    "I": ("Wellbeing", "N"),  # statuses
    "J": ("Physical", "O"),
    "K": ("Mental", "N"),
    "L": ("Session Feel", "I"),
    "M": ("Session Feel", "K"),
}
CLASSES = [  # status-board row → (score column, status column) in the chart data, app fields
    ("D", "I", "wb_score", "wb_status"),
    ("E", "J", "ph_readiness", "ph_status"),
    ("F", "K", "mn_score", "mn_status"),
    ("G", "L", "feel_score", "feel_status"),
    ("H", "M", "overall_score", "overall_status"),
]

# The legacy formulas, as they were; `TrendDelta` (a named range) is the cell $Z$1.
B72 = "=COUNT(Session!$A$5:$A$304)"
B73 = "=MIN(12,B72)"
B_DATE = '=IF(MAX(0,$B$72-12)+A{r}>$B$72,"",SMALL(Session!$A$5:$A$304,MAX(0,$B$72-12)+A{r}))'
LOOKUP = (
    '=IF($B{r}="","",IFERROR(IF(INDEX({src},MATCH($B{r},{dates},0))="","",'
    'INDEX({src},MATCH($B{r},{dates},0))),""))'
)
STATUS = '=IF($B$73=0,"",INDEX({st}$76:{st}$87,$B$73))'
SCORE = '=IF($B$73=0,"",INDEX({sc}$76:{sc}$87,$B$73))'
LAST = (
    '=IF($B$73=0,"",IFERROR(ROUND(AVERAGE(INDEX({sc}$76:{sc}$87,MAX(1,$B$73-3)):'
    'INDEX({sc}$76:{sc}$87,$B$73)),1),""))'
)
PREVIOUS = (
    '=IF($B$73<5,"",IFERROR(ROUND(AVERAGE(INDEX({sc}$76:{sc}$87,MAX(1,$B$73-7)):'
    'INDEX({sc}$76:{sc}$87,$B$73-4)),1),""))'
)
CHANGE = '=IF(OR(D{r}="",E{r}=""),"",ROUND(D{r}-E{r},1))'
DIRECTION = (
    '=IF(F{r}="","\u2013",IF(F{r}>=$Z$1,"▲ Improving",IF(F{r}<=-$Z$1,"▼ Declining","► Stable")))'
)
LOWS = '=COUNTIF({st}$76:{st}$87,"LOW")'
ARROWS = {"up": "▲ Improving", "down": "▼ Declining", "flat": "► Stable", None: "\u2013"}


def _sessions(rng: random.Random) -> list[dict[str, Value]]:
    start = dt.date(2026, 6, 1)
    days = sorted(rng.sample(range(120), rng.randint(0, 20)))
    rows: list[dict[str, Value]] = []
    for d in days:
        row: dict[str, Value] = {"date": start + dt.timedelta(days=d), "session_no": 1}
        for _, _, score, status in CLASSES:
            row[score] = rng.choice([None, *(round(rng.uniform(1, 10), 1) for _ in range(4))])
            row[status] = rng.choice([None, "GOOD", "WATCH", "LOW", "LOW"])
        rows.append(row)
    return rows


def _legacy(rows: list[dict[str, Value]], delta: float, folder: Path) -> list[tuple[Any, ...]]:
    """The legacy summary's status board (rows 5-9, columns B-H) for these sessions."""
    book = openpyxl.Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    tabs = {
        name: book.create_sheet(name) for name in ("Session", "Wellbeing", "Physical", "Mental")
    }
    tabs["Session Feel"] = book.create_sheet("Session Feel")
    summary = book.create_sheet("Summary")
    fields = {col: (tab, letter) for col, (tab, letter) in SOURCES.items()}
    by_column = {c[0]: c[2] for c in CLASSES} | {c[1]: c[3] for c in CLASSES}
    for r, row in enumerate(rows, start=5):
        for sheet in tabs.values():
            sheet.cell(r, 1).value = row["date"]
        for col, (tab, letter) in fields.items():
            tabs[tab][f"{letter}{r}"] = row[by_column[col]]
    summary["Z1"] = delta
    summary["B72"] = B72
    summary["B73"] = B73
    for i, r in enumerate(range(76, 88), start=1):
        summary[f"A{r}"] = i
        summary[f"B{r}"] = B_DATE.format(r=r)
        for col, (tab, letter) in fields.items():
            sheet = f"'{tab}'" if " " in tab else tab
            src, dates = f"{sheet}!${letter}$5:${letter}$304", f"{sheet}!$A$5:$A$304"
            cell = f"{col}{r}"
            summary[cell] = ArrayFormula(cell, LOOKUP.format(r=r, src=src, dates=dates))
    for r, (sc, st, _, _) in enumerate(CLASSES, start=5):
        for col, text in [
            ("B", STATUS.format(st=st)),
            ("C", SCORE.format(sc=sc)),
            ("D", LAST.format(sc=sc)),
            ("E", PREVIOUS.format(sc=sc)),
        ]:
            summary[f"{col}{r}"] = ArrayFormula(f"{col}{r}", text)
        summary[f"F{r}"] = CHANGE.format(r=r)
        summary[f"G{r}"] = DIRECTION.format(r=r)
        summary[f"H{r}"] = LOWS.format(st=st)
    path = folder / "legacy.xlsx"
    book.save(path)
    command = soffice()
    assert command is not None, "CLIMBLOG_REQUIRE_SOFFICE is set but no LibreOffice works"
    return [row[1:8] for row in recalculate(command, path)["Summary"][4:9]]


def _blank(value: Any) -> Any:
    return None if value == "" else value


@pytest.mark.parametrize("seed", range(6))
def test_the_status_board_is_the_legacy_one(seed: int) -> None:
    rng = random.Random(seed)
    rows = _sessions(rng)
    delta = rng.choice([0.5, 0.3, 1.0])
    [board] = [w for w in JOURNAL.views["overview"] if isinstance(w, StatusBoardWidget)]  # type: ignore[index]
    day = dt.date(2026, 12, 31)
    [data] = compute_view(JOURNAL, [board], {"session": rows}, {"trend_delta": delta}, day)
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        legacy = _legacy(rows, delta, Path(folder))
    for app, sheet in zip(data["rows"], legacy, strict=True):
        status, score, last, previous, change, arrow, lows = (_blank(v) for v in sheet)
        assert app["status"] == status, (app["label"], sheet)
        assert app["score"] == pytest.approx(score), (app["label"], sheet)
        assert app["average_last"] == pytest.approx(last), (app["label"], sheet)
        assert app["average_previous"] == pytest.approx(previous), (app["label"], sheet)
        assert app["change"] == pytest.approx(change), (app["label"], sheet)
        assert ARROWS[app["direction"]] == arrow, (app["label"], sheet)
        assert app["low"] == lows, (app["label"], sheet)


# ---- The monthly table (Summary - Trends rows 14-19), as the legacy formulas ----

MONTH_SOURCES = {  # legacy tab → {column letter: app field}
    "Session": {},
    "Wellbeing": {"M": "wb_score"},
    "Physical": {"N": "ph_readiness"},
    "Mental": {"M": "mn_score"},
    "Session Feel": {"H": "feel_score", "K": "overall_status"},
}
DASH = chr(0x2013)  # the legacy "no value" cell
IN_MONTH = '{dates},">="&$A{r},{dates},"<"&EDATE($A{r},1)'
MONTH_COUNT = "=COUNTIFS(" + IN_MONTH + ")"
MONTH_AVERAGE = (
    '=IF($B{r}=0,"{dash}",IFERROR(ROUND(AVERAGEIFS({values},' + IN_MONTH + '),1),"{dash}"))'
)
MONTH_OVERALL = '=IF(COUNT(C{r}:F{r})=0,"{dash}",ROUND(AVERAGE(C{r}:F{r}),1))'
MONTH_LOW = '=IF($B{r}=0,"{dash}",COUNTIFS({values},"LOW",' + IN_MONTH + "))"
REST_AVERAGE = (
    '=IF($I{r}=0,"{dash}",IFERROR(ROUND(AVERAGEIFS({values},' + IN_MONTH + '),1),"{dash}"))'
)


def _ref(tab: str, column: str, last: int = 304) -> str:
    sheet = f"'{tab}'" if " " in tab else tab
    return f"{sheet}!${column}$5:${column}${last}"


def _monthly_rows(rng: random.Random) -> tuple[list[dict[str, Value]], list[dict[str, Value]]]:
    start = dt.date(2026, 3, 1)  # 2026-03 to 2026-10, before the six months too
    sessions: list[dict[str, Value]] = []
    for d in sorted(rng.sample(range(240), rng.randint(0, 40))):
        row: dict[str, Value] = {"date": start + dt.timedelta(days=d), "session_no": 1}
        for name in ("wb_score", "ph_readiness", "mn_score", "feel_score"):
            row[name] = rng.choice([None, *(round(rng.uniform(1, 10), 1) for _ in range(3))])
        row["overall_status"] = rng.choice([None, "GOOD", "WATCH", "LOW"])
        sessions.append(row)
    rests: list[dict[str, Value]] = [
        {"date": start + dt.timedelta(days=d), "wellbeing_score": rng.choice([None, 4.5, 6.2, 8.0])}
        for d in sorted(rng.sample(range(240), rng.randint(0, 20)))
    ]
    return sessions, rests


@pytest.mark.parametrize("seed", range(4))
def test_the_monthly_table_is_the_legacy_one(seed: int) -> None:
    rng = random.Random(seed)
    sessions, rests = _monthly_rows(rng)
    day = dt.date(2026, 10, 31)
    months = [dt.date(2026, m, 1) for m in range(5, 11)]  # the legacy six, up to October

    book = openpyxl.Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    tabs = {name: book.create_sheet(name) for name in MONTH_SOURCES}
    rest_tab = book.create_sheet("Rest Days")
    summary = book.create_sheet("Summary")
    for r, row in enumerate(sessions, start=5):
        for tab, columns in MONTH_SOURCES.items():
            tabs[tab].cell(r, 1).value = row["date"]
            for letter, name in columns.items():
                tabs[tab][f"{letter}{r}"] = row[name]
    for r, row in enumerate(rests, start=5):
        rest_tab.cell(r, 1).value = row["date"]
        rest_tab[f"P{r}"] = row["wellbeing_score"]
    for r, month in enumerate(months, start=14):
        summary[f"A{r}"] = month
        summary[f"B{r}"] = MONTH_COUNT.format(r=r, dates=_ref("Session", "A"))
        for col, (tab, letter) in zip(
            "CDEF",
            [("Wellbeing", "M"), ("Physical", "N"), ("Mental", "M"), ("Session Feel", "H")],
            strict=True,
        ):
            summary[f"{col}{r}"] = MONTH_AVERAGE.format(
                dash=DASH, r=r, values=_ref(tab, letter), dates=_ref(tab, "A")
            )
        summary[f"G{r}"] = MONTH_OVERALL.format(dash=DASH, r=r)
        summary[f"H{r}"] = MONTH_LOW.format(
            dash=DASH, r=r, values=_ref("Session Feel", "K"), dates=_ref("Session Feel", "A")
        )
        rest_dates = _ref("Rest Days", "A", 1000)
        summary[f"I{r}"] = MONTH_COUNT.format(r=r, dates=rest_dates)
        summary[f"J{r}"] = REST_AVERAGE.format(
            dash=DASH, r=r, values=_ref("Rest Days", "P", 1000), dates=rest_dates
        )
    with tempfile.TemporaryDirectory(dir=work_dir()) as folder:
        path = Path(folder) / "legacy.xlsx"
        book.save(path)
        command = soffice()
        assert command is not None, "CLIMBLOG_REQUIRE_SOFFICE is set but no LibreOffice works"
        legacy = [row[1:10] for row in recalculate(command, path)["Summary"][13:19]]

    [monthly] = [w for w in JOURNAL.views["overview"] if isinstance(w, MonthlyWidget)]  # type: ignore[index]
    [data] = compute_view(JOURNAL, [monthly], {"session": sessions, "rest_day": rests}, {}, day)
    by_month = {row["month"]: row for row in data["rows"]}
    dash = DASH
    for month, sheet in zip(months, legacy, strict=True):
        app = by_month.get(month.isoformat()[:7])
        count, *classes, overall, low, rest_count, rest_mean = sheet
        if app is None:  # before the first record: the legacy shows zeros and dashes
            assert count == 0 and rest_count == 0, (month, sheet)
            continue
        expected = [None if v == dash else v for v in (*classes, overall, low, rest_mean)]
        actual = [*app["classes"], app["overall"], app["low"], app["extra"][1]]
        assert app["count"] == count, (month, sheet)
        assert app["extra"][0] == rest_count, (month, sheet)
        assert actual == pytest.approx(expected), (month, sheet)
