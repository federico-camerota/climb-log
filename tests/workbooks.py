# SPDX-License-Identifier: GPL-3.0-or-later
"""Build small fictional workbooks for the storage tests (D-034: fictional data only)."""

import datetime as dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import openpyxl

Rows = Sequence[Sequence[Any]]


def tab(keys: Sequence[str | None], *rows: Sequence[Any]) -> list[Sequence[Any]]:
    """A data tab: labels in row 1 (here the keys, upper-cased), keys in row 2, then the rows."""
    labels = [key.upper() if key else None for key in keys]
    return [labels, list(keys), *rows]


def write_workbook(path: Path, tabs: Mapping[str, Rows]) -> Path:
    """Write the tabs, in order, to a new .xlsx file."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, rows in tabs.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(list(row))
    workbook.save(path)
    return path


# A fictional module: a session split over two tabs, with a renamed and a retired field.
SYNC_MODULE = """\
module: test_sync
name: Test sync
version: 2
kind: journal
settings:
  low_max: {type: number, default: 4, label: LOW at or below}
  start: {type: date, default: 2026-10-01}
  strict: {type: bool, default: true}
  motto: {type: text, default: "=keep going"}
scales:
  s10_down: {min: 1, max: 10, direction: lower_better}
  s10: {min: 1, max: 10, direction: higher_better}
entities:
  session:
    label: Session
    key: [date]
    anchor_tab: Pre
    sections:
      pre: {label: Before, tab: Pre, phase: pre}
      post: {label: After, tab: Post, phase: post}
    fields:
      date: {type: date, required: true, section: "*"}
      pain: {type: scale, scale: s10_down, section: pre}
      kind: {type: choice, choices: [Climb, Board], section: pre}
      mood: {type: scale, scale: s10, section: post, renamed_from: feel}
      note: {type: text, section: post}
      old_note: {type: text, section: post, retired: true}
"""


D20 = dt.datetime(2026, 10, 20)
PRE = ["date", "pain", "auto:status", "weather"]
POST = ["date", "feel", "note", "old_note", "updated_at", "deleted"]


def existing_tabs() -> dict[str, Rows]:
    """Hand-made tabs for `SYNC_MODULE`: Pre without `kind` and system columns, Post still
    with `feel`."""
    return {
        "Pre": [
            ["Day", "Pain", "Status", "Weather"],
            PRE,
            [D20, 3, '=IF(B3="","",B3*2)', "sunny"],
        ],
        "Post": [
            ["Date", "feel", "Note", "Old note", "updated_at", "deleted"],
            POST,
            [D20, 7, "Bene", "vecchia"],
        ],
        "_settings": [["key", "value"], ["start", dt.datetime(2026, 9, 1)], ["low_max", 3]],
        "_meta": [["key", "value"], ["module", "test_sync"], ["module_version", 1]],
    }
