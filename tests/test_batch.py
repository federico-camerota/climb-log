# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001, RUF003  (prescriptions are written with ×, as in "3×10")
"""Batch and repeated forms (D-115): `batch_over` and `keep_fields` checked, a batch's rows
(the table's rows in its filter still in use, each with its record of the day), the batch read
and its all-or-nothing save through the API, and Today counting a batch as one item. The demo
program's tables, with fictional rows."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import Problems
from fastapi.testclient import TestClient

from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import Module, load_module
from climblog.modules.batch import Batch, batch_rows, shared_fields
from climblog.modules.forms import due
from climblog.modules.program import RUNS_TAB
from climblog.storage import CachedRepository, Snapshots, XlsxBackend, sync_module
from climblog.storage.base import Append

DEMO = Path(__file__).parent.parent / "scripts" / "demo-program.yaml"
DAY = dt.date(2026, 9, 15)  # week 2 of the run started in 2026-W37

EXERCISES = [
    {"id": "W1", "name": "Arm circles", "session": "Warm-up", "w2": "1×20"},
    {"id": "A1", "name": "Wall slides", "session": "A", "w2": "3×10"},
    {"id": "A2", "name": "Band pulls", "session": "A", "retired": "Yes"},
    {"id": "A4", "name": "Gone", "session": "A", "deleted": "x"},
    {"id": "B1", "name": "Hip airplanes", "session": "B", "w2": "Skip"},
]
MEASURES = [{"id": "M1", "name": "Stand", "unit": "s"}, {"id": "M2", "name": "Reach"}]


@pytest.fixture
def program() -> Module:
    return load_module(DEMO)


def rows_of(module: Module, form: str, records: list[dict[str, Value]]) -> Batch:
    model = (module.forms or {})[form]
    table = EXERCISES if form.startswith("session") else MEASURES
    shown = [r | {"retired": r.get("retired") == "Yes"} for r in table if "deleted" not in r]
    return batch_rows(module, model, shown, records, {"date": DAY}, 2)


# ---- The module file ----


def demo_text() -> str:
    return DEMO.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("reference: exercises, where", "reference: exercise, where",
         "no reference table 'exercise'"),
        ("where: {session: [Warm-up, A]}}}\n  session_b",
         "where: {sesion: [Warm-up, A]}}}\n  session_b", "'exercises' has no field 'sesion'"),
        ("where: {session: [Warm-up, A]}}}\n  session_b",
         "where: {session: [Warmup, A]}}}\n  session_b", "'Warmup' is not one of session's"),
        ("retest: {entity: retest, batch_over: measures",
         "retest: {entity: retest, batch_over: drills", "needs one ref field to 'drills'"),
        ("    key: [date, measure]\n", "    key: [date]\n",
         "'measure' must be part of the key of 'retest'"),
        ("  session: {entity: session}\n", "  session: {entity: session, keep_fields: [notes]}\n",
         "keep_fields needs `repeat: true` or `batch_over`"),
        ("batch_over: measures, keep_fields", "batch_over: measures, repeat: true, keep_fields",
         "a batch form has no repeat"),
        ("drill_tries: {entity: drill_try, repeat: true",
         "drill_tries: {entity: drill_try, batch_over: drills",
         "numbered key part 'try_no'"),
    ],
)  # fmt: skip
def test_batch_forms_are_checked(problems: Problems, old: str, new: str, message: str) -> None:
    text = demo_text()
    assert old in text
    found = problems(text.replace(old, new))
    assert any(message in line for line in found), found


def test_a_child_entity_has_no_batch_form(problems: Problems) -> None:
    text = demo_text().replace(
        "    key: [date, exercise]\n",
        "    key: [date, exercise]\n    parent: {entity: session, key: [date]}\n",
    )
    assert any("is a child entity" in line for line in problems(text))


# ---- The rows ----


def test_the_rows_in_the_filter_still_in_use(program: Module) -> None:
    batch = rows_of(program, "session_a", [])
    assert batch.field == "exercise"
    assert batch.shared == ["date"]
    assert [(r.key, r.label, r.hint, r.record) for r in batch.rows] == [
        ("W1", "W1 · Arm circles", "Prescription W2: 1×20", None),
        ("A1", "A1 · Wall slides", "Prescription W2: 3×10", None),
    ]  # A2 retired, A4 deleted, B1 another session


def test_each_row_with_its_record(program: Module) -> None:
    records: list[dict[str, Value]] = [
        {"date": DAY, "exercise": "a1 ", "done": "3×10"},  # typed in the sheet, any case
        {"date": DAY, "exercise": "A2", "done": "1×5"},  # retired, but logged
        {"date": DAY, "exercise": "B1"},  # no row of session A
        {"date": DAY - dt.timedelta(days=7), "exercise": "W1"},  # another day
    ]
    batch = rows_of(program, "session_a", records)
    assert [(r.key, r.retired, r.record) for r in batch.rows] == [
        ("W1", False, None),
        ("A1", False, 0),
        ("A2", True, 1),
    ]
    assert batch.others == [2]


def test_keep_fields_are_typed_once(program: Module) -> None:
    assert shared_fields(program, (program.forms or {})["retest"]) == ["date", "checkpoint"]


# ---- The API ----


@pytest.fixture
def client(program: Module, tmp_path: Path) -> Iterator[TestClient]:
    repo = XlsxBackend(tmp_path / "program.xlsx")
    sync_module(program, repo)
    edits = [Append(RUNS_TAB, {"run": 1, "start_week": "2026-W37"})]
    edits += [Append("Exercises", row) for row in EXERCISES]
    edits += [Append("Measures", row) for row in MEASURES]
    edits += [Append("Exercise log", {"date": dt.datetime(2026, 9, 15), "exercise": "W1",
                                       "done": "1×20"})]  # fmt: skip
    repo.apply(edits)
    catalog = Catalog(AppConfig())
    cached = CachedRepository("program", repo, Snapshots(tmp_path / "snapshots"))
    catalog.entries["program"] = Entry("program", program, [], cached)
    yield TestClient(create_app(catalog=catalog))


def batch(client: TestClient, form: str, query: str = "date=2026-09-15") -> dict[str, Any]:
    response = client.get(f"/api/modules/program/forms/{form}/batch?{query}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_batch_read(client: TestClient) -> None:
    body = batch(client, "session_a")
    assert (body["entity"], body["field"], body["table"], body["shared"]) == (
        "exercise_log",
        "exercise",
        "exercises",
        ["date"],
    )
    rows = [
        (r["key"], r["hint"], r["record"] and r["record"]["values"]["done"]) for r in body["rows"]
    ]
    assert rows == [("W1", "Prescription W2: 1×20", "1×20"), ("A1", "Prescription W2: 3×10", None)]
    assert body["others"] == []


def test_not_a_batch_form(client: TestClient) -> None:
    assert client.get("/api/modules/program/forms/session/batch?date=2026-09-15").status_code == 404
    bad = client.get("/api/modules/program/forms/session_a/batch?date=someday")
    assert bad.status_code == 422


URL = "/api/modules/program/exercise_log/batch"


def test_a_batch_saved_together(client: TestClient) -> None:
    body = {
        "new": [{"date": "2026-09-15", "exercise": "A1", "done": "3×8"}],
        "changed": [
            {
                "key": {"date": "2026-09-15", "exercise": "W1"},
                "values": {"done": "1×15"},
                "expected": {"done": "1×20"},
            }
        ],
    }
    saved = client.post(URL, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["keys"] == [
        {"date": "2026-09-15", "exercise": "A1"},
        {"date": "2026-09-15", "exercise": "W1"},
    ]
    done = [r["record"]["values"]["done"] for r in batch(client, "session_a")["rows"]]
    assert done == ["1×15", "3×8"]


@pytest.mark.parametrize(
    ("body", "index", "status"),
    [
        ({"new": [{"date": "2026-09-15", "exercise": "A1"},
                  {"date": "2026-09-15", "exercise": "ZZ"}]}, 1, 422),
        ({"new": [{"date": "2026-09-15", "exercise": "A1"},
                  {"date": "2026-09-15", "exercise": "a1"}]}, 1, 409),
        ({"new": [{"date": "2026-09-15", "exercise": "A1"}],
          "changed": [{"key": {"date": "2026-09-15", "exercise": "W1"}, "values": {"done": "x"},
                       "expected": {"done": "changed meanwhile"}}]}, 1, 409),
    ],
)  # fmt: skip
def test_all_or_nothing(client: TestClient, body: dict[str, Any], index: int, status: int) -> None:
    refused = client.post(URL, json=body)
    assert refused.status_code == status, refused.text
    assert refused.json()["detail"]["index"] == index
    rows = batch(client, "session_a")["rows"]
    assert [r["record"] is not None for r in rows] == [True, False]  # A1 not written either


# ---- Today ----


def today(program: Module, rows: list[dict[str, Value]], day: dt.date = DAY) -> list[Any]:
    reference = {
        "exercises": [r | {"retired": r.get("retired") == "Yes"} for r in EXERCISES
                      if "deleted" not in r],
    }  # fmt: skip
    found = due(program, {"exercise_log": rows}, day, reference=reference)
    return [(i.form, i.label, i.status, i.missing) for i in found.items]


def log(*keys: str, done: str | None = "3×10") -> list[dict[str, Value]]:
    return [{"date": DAY, "exercise": k, "done": done} for k in keys]


def test_today_counts_a_batch_as_one_item(program: Module) -> None:
    assert today(program, log("A1")) == [("session_a", "Session a · 1 of 2", "partial", ["W1"])]
    assert today(program, log("A1", "W1")) == [("session_a", "Session a · 2 of 2", "done", [])]


def test_a_row_logged_but_blank_is_not_done(program: Module) -> None:
    rows = log("A1") + log("W1", done=None)
    assert today(program, rows) == [("session_a", "Session a · 2 of 2", "partial", [])]


def test_rows_two_batches_share(program: Module) -> None:
    # the warm-up alone: either session
    assert [i[0] for i in today(program, log("W1"))] == ["session_a", "session_b"]
    # with a row of session B: that one
    assert today(program, log("W1", "B1")) == [("session_b", "Session b · 2 of 2", "done", [])]
