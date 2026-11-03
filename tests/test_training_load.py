# SPDX-License-Identifier: GPL-3.0-or-later
"""Training load (#99, D-092): weekly load, ACWR, monotony, strain, streaks. Fictional data,
expected values computed by hand (or step by step below)."""

import datetime as dt
import statistics
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import Problems
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from climblog.analytics import compute_view
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.modules.schema import Module, Widget
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
FINGERS = load_module(ROOT / "modules" / "finger-strength.yaml")
LOAD = next(w for w in (JOURNAL.views or {})["load"] if w.widget == "training_load")
MON = dt.date(2026, 10, 5)  # a Monday
WIDGET: TypeAdapter[Widget] = TypeAdapter(Widget)


def day(n: int) -> dt.date:
    return MON + dt.timedelta(days=n)


def session(n: int, load: float | None, no: int = 1, **values: Value) -> dict[str, Value]:
    base: dict[str, Value] = {"date": day(n), "session_no": no, "session_load": load}
    if load is not None:
        base |= {"duration_min": load / 5, "feel_effort": 5}
    return base | values


def compute(
    sessions: list[dict[str, Value]],
    on: dt.date,
    rests: list[dict[str, Value]] | None = None,
    fingers: list[dict[str, Value]] | None = None,
    widget: Any = LOAD,
) -> dict[str, Any]:
    tables = {"session": sessions, "rest_day": rests or []}

    def others(module_id: str) -> tuple[Module, Any] | None:
        if module_id == "finger_strength" and fingers is not None:
            return FINGERS, {"session": fingers}
        return None

    [found] = compute_view(JOURNAL, [widget], tables, {}, on, others)
    return found


def test_weekly_load_sessions_and_rest_days() -> None:
    sessions = [session(0, 300), session(0, 200, 2), session(2, 400), session(8, 250)]
    rests: list[dict[str, Value]] = [{"date": day(1)}, {"date": day(9)}]
    found = compute(sessions, day(10), rests)
    first, second = found["weeks"]
    assert (first["label"], first["start"], first["load"], first["sessions"]) == (
        "2026-W41",
        "2026-10-05",
        900,
        3,
    )
    assert (second["load"], second["sessions"], second["rest_days"]) == (250, 1, 1)
    assert first["rest_days"] == 1
    assert found["shown"] == 12


def test_a_session_without_duration_or_effort_counts_as_zero_and_is_flagged() -> None:
    sessions: list[dict[str, Value]] = [
        session(0, 300),
        {"date": day(1), "session_no": 1, "duration_min": 60},  # no effort, no load
        session(2, 200, feel_effort=None),  # a load but an input missing: flagged, kept
    ]
    [week] = compute(sessions, day(3))["weeks"]
    assert (week["load"], week["sessions"], week["without_load"]) == (500, 3, 2)


def test_the_ratio_follows_the_ewma_from_the_baseline() -> None:
    # every day 100 for 27 days, then 400 on day 27, the 28th day: the baseline's first day
    sessions = [session(n, 100) for n in range(27)] + [session(27, 400)]
    found = compute(sessions, day(27))
    la, lc = 2 / 8, 2 / 29
    a = c = 0.0
    for n in range(28):
        load = 400 if n == 27 else 100
        a, c = load * la + (1 - la) * a, load * lc + (1 - lc) * c
    assert found["acwr_today"] == round(a / c, 2)
    assert found["baseline_from"] == day(27).isoformat()
    weeks = found["weeks"]
    assert [w["acwr"] for w in weeks[:3]] == [None, None, None]  # before the baseline
    assert weeks[3]["acwr"] == round(a / c, 2)  # the current week: at the day asked
    assert found["zones"] == [0.8, 1.3, 1.5]


def test_before_the_baseline_there_is_no_ratio() -> None:
    found = compute([session(0, 300), session(10, 300)], day(12))
    assert found["acwr_today"] is None
    assert all(w["acwr"] is None for w in found["weeks"])


def test_monotony_and_strain() -> None:
    sessions = [session(0, 100), session(1, 300), session(3, 200)]
    [week] = compute(sessions, day(6))["weeks"]
    loads = [100, 300, 0, 200, 0, 0, 0]
    monotony = round(statistics.fmean(loads) / statistics.stdev(loads), 2)
    assert week["monotony"] == monotony
    assert week["strain"] == round(600 * monotony, 1)


def test_no_monotony_without_spread_or_days() -> None:
    same = [session(n, 100) for n in range(7)]
    assert compute(same, day(6))["weeks"][0]["monotony"] is None  # every day the same
    assert compute([session(0, 100)], day(0))["weeks"][0]["monotony"] is None  # one day so far


def test_streaks() -> None:
    days = [0, 1, 2, 5, 6, 9, 10, 11]
    found = compute([session(n, 100) for n in days], day(12))
    assert found["longest_streak"] == {
        "days": 3,
        "start": day(9).isoformat(),
        "end": day(11).isoformat(),
    }
    assert found["current_streak"] == 3  # ended yesterday
    assert compute([session(n, 100) for n in days], day(13))["current_streak"] == 0


def test_finger_training_is_stacked_not_in_the_ratio() -> None:
    fingers: list[dict[str, Value]] = [
        {"date": day(1), "session_type": "Max hangs", "set_load": 48},
        {"date": day(2), "session_type": "Finger curls", "set_load": 30},
    ]
    found = compute([session(0, 300)], day(3), fingers=fingers)
    [week] = found["weeks"]
    assert (found["others"], week["others"], week["load"]) == (
        ["Finger training (sets x effort)"],
        [78],
        300,
    )
    missing = compute([session(0, 300)], day(3))
    assert (missing["others"], missing["absent"]) == ([], ["Finger training (sets x effort)"])


def test_finger_set_load_is_sets_times_effort() -> None:
    from climblog.modules.compute import compute_module

    sessions: list[dict[str, Value]] = [
        {"date": day(1), "session_type": "Max hangs", "session_rpe": 8}
    ]
    sets: list[dict[str, Value]] = [{"date": day(1), "set_no": n} for n in (1, 2, 3)]
    derived = compute_module(FINGERS, {"session": sessions, "hang_set": sets, "curl_set": []}, {})
    assert derived["session"][0]["set_load"] == 24


def test_nothing_logged() -> None:
    found = compute([], day(3))
    assert (found["weeks"], found["longest_streak"], found["current_streak"]) == ([], None, 0)


def test_records_after_the_day_are_left_out() -> None:
    found = compute([session(0, 100), session(5, 900)], day(2))
    assert found["weeks"][0]["load"] == 100


def test_options_are_checked(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    bad = text.replace("      weeks: 12\n", "      weeks: 12\n      acute: 30\n", 1)
    assert any("acute window must be shorter" in p for p in problems(bad))
    bad = text.replace(
        "      inputs: [session.duration_min, session.feel_effort]", "      inputs: [rest_day.mood]"
    )
    assert any("'rest_day.mood' is not a field of 'session'" in p for p in problems(bad))
    bad = text.replace("      rest: rest_day\n", "      rest: rest\n")
    assert any("no entity 'rest'" in p for p in problems(bad))
    widget = WIDGET.validate_python({"widget": "training_load", "load": "session.session_load"})
    with pytest.raises(ValueError, match="zones go up"):
        WIDGET.validate_python({"widget": "training_load", "load": "x.y", "zones": [2, 1, 3]})
    assert compute([session(0, 100)], day(0), widget=widget)["others"] == []


# ---- through the API, with the finger module configured ----


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    journal, fingers = tmp_path / "journal.xlsx", tmp_path / "fingers.xlsx"
    sync_module(JOURNAL, XlsxBackend(journal))
    sync_module(FINGERS, XlsxBackend(fingers))
    RecordWriter(JOURNAL, XlsxBackend(journal)).add(
        "session", {"date": "2026-10-05", "duration_min": 90, "feel_effort": 6}
    )
    RecordWriter(FINGERS, XlsxBackend(fingers)).add(
        "session", {"date": "2026-10-06", "session_type": "Max hangs", "session_rpe": 7}
    )
    catalog = Catalog(AppConfig())
    snapshots = Snapshots(tmp_path / "snapshots")
    catalog.entries["journal"] = Entry(
        "journal", JOURNAL, [], CachedRepository("journal", XlsxBackend(journal), snapshots)
    )
    catalog.entries["fingers"] = Entry(
        "fingers", FINGERS, [], CachedRepository("fingers", XlsxBackend(fingers), snapshots)
    )
    yield TestClient(create_app(catalog=catalog))


def test_the_load_view(client: TestClient) -> None:
    body = client.get("/api/modules/journal/views/load", params={"date": "2026-10-11"}).json()
    load, weekbars = body["widgets"]
    [week] = load["weeks"]
    assert (week["load"], week["others"], load["absent"]) == (540, [0], [])  # no sets logged
    assert weekbars["widget"] == "weekbars"


def test_only_finger_training_or_a_wrong_entity() -> None:
    fingers: list[dict[str, Value]] = [
        {"date": day(1), "session_type": "Max hangs", "set_load": 40}
    ]
    found = compute([], day(3), fingers=fingers)
    [week] = found["weeks"]
    assert (week["load"], week["others"], found["acwr_today"], found["longest_streak"]) == (
        0,
        [40],
        None,
        None,
    )
    spec = LOAD.model_dump(by_alias=True) | {
        "others": [{"module": "finger_strength", "metric": "nope.x", "label": "F"}]
    }
    wrong = compute([session(0, 100)], day(1), fingers=fingers, widget=WIDGET.validate_python(spec))
    assert wrong["absent"] == ["F"]
