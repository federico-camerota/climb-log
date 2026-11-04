# SPDX-License-Identifier: GPL-3.0-or-later
"""The protein log (#129, D-107): meals with their grams, the day's total against the target on
Today and in the Summary tab, a new meal offered after the day's first ones, and the bars with
the target. A fictional workbook in a temp dir only."""

import datetime as dt
from pathlib import Path

import pytest
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient

from climblog.analytics import compute_view
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

ROOT = Path(__file__).parent.parent
PROTEIN = load_module(ROOT / "modules" / "protein.yaml")
DAY = dt.date(2026, 11, 9)


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    path = tmp_path / "protein.xlsx"
    sync_module(PROTEIN, XlsxBackend(path))
    return path


def client_for(path: Path, tmp_path: Path) -> TestClient:
    catalog = Catalog(AppConfig())
    cached = CachedRepository("protein", XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
    catalog.entries["protein"] = Entry("protein", PROTEIN, [], cached)
    return TestClient(create_app(catalog=catalog))


def add(path: Path, *meals: tuple[dt.date, str, float]) -> None:
    writer = RecordWriter(PROTEIN, XlsxBackend(path))
    for day, meal, grams in meals:  # no number: the next one of the day (D-050)
        writer.add("meal", {"date": day, "meal": meal, "protein_g": grams})


def test_the_module_loads_and_makes_its_tabs(workbook: Path) -> None:
    assert PROTEIN.module == "protein"
    assert list(XlsxBackend(workbook).read_table("Meals").columns[:5]) == [
        "date",
        "meal_no",
        "meal",
        "protein_g",
        "what",
    ]


def test_today_says_the_days_total_against_the_target(workbook: Path, tmp_path: Path) -> None:
    yesterday = DAY - dt.timedelta(days=1)
    add(workbook, (yesterday, "Dinner", 60), (DAY, "Breakfast", 30), (DAY, "Lunch", 45.5))
    body = client_for(workbook, tmp_path).get("/api/recommendation", params={"date": str(DAY)})
    [advice] = body.json()["items"]
    assert (advice["label"], advice["headline"], advice["message"]) == (
        "Protein today",
        None,  # no headline: nothing to weigh against the climbing advice
        "Below the daily target so far.",
    )
    reasons = {r["label"]: r["value"] for r in advice["reasons"]}
    assert reasons == {
        "Today (g)": 75.5,
        "Still to go (g)": 64.5,
        "Daily target (g)": 140,
        "Last 7 days, per day (g)": 19,  # 135.5 / 7, days without a meal as 0 g
    }


@pytest.mark.parametrize(
    ("grams", "message"),
    [((), "Nothing logged today yet."), ((90, 50), "Daily target reached.")],
)
def test_nothing_logged_and_target_reached(
    workbook: Path, tmp_path: Path, grams: tuple[float, ...], message: str
) -> None:
    add(workbook, *((DAY, "Snack", g) for g in grams))
    body = client_for(workbook, tmp_path).get("/api/recommendation", params={"date": str(DAY)})
    [advice] = body.json()["items"]
    assert advice["message"] == message


def test_today_offers_another_meal_after_the_first(workbook: Path, tmp_path: Path) -> None:
    client = client_for(workbook, tmp_path)
    [day] = client.get("/api/today", params={"date": str(DAY)}).json()["modules"]
    assert [(i["form"], i["key"], i["status"]) for i in day["items"]] == [
        ("meal", {"date": str(DAY)}, "missing")
    ]
    add(workbook, (DAY, "Breakfast", 30), (DAY, "Snack", 12))
    [day] = client.get("/api/today", params={"date": str(DAY)}).json()["modules"]
    assert [(i["key"], i["status"]) for i in day["items"]] == [
        ({"date": str(DAY), "meal_no": 1}, "done"),
        ({"date": str(DAY), "meal_no": 2}, "done"),
        ({"date": str(DAY)}, "another"),  # the next meal: no number yet
    ]


def test_the_bars_draw_the_target() -> None:
    meals: list[dict[str, Value]] = [
        {"date": DAY, "meal_no": 1, "meal": "Lunch", "protein_g": 40},
        {"date": DAY, "meal_no": 2, "meal": "Dinner", "protein_g": 55},
    ]
    daily, weekly = compute_view(
        PROTEIN, (PROTEIN.views or {})["overview"], {"meal": meals}, {"target_g": 150}, DAY
    )
    assert (daily["categories"][-1], daily["values"][-1], daily["goal"]) == ("2026-11-09", 95, 150)
    assert weekly["goal"] is None


def test_a_goal_must_be_a_number_or_a_setting(problems: Problems, load: LoadYaml) -> None:
    text = (ROOT / "modules" / "protein.yaml").read_text(encoding="utf-8")
    bad = text.replace("goal: settings.target_g", "goal: settings.nope")
    assert any("'settings.nope' is not a number or a setting" in p for p in problems(bad))
    plain = load(text.replace("goal: settings.target_g", "goal: 120"))
    [daily, _] = compute_view(plain, (plain.views or {})["overview"], {"meal": []}, {}, DAY)
    assert daily["goal"] == 120
