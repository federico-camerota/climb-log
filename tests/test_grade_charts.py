# SPDX-License-Identifier: GPL-3.0-or-later
"""Grade charts (#101, D-094): French and gym never converted, gym grades per venue, the
pyramid of hardest grades tried, by setting and venue. Fictional data only."""

import datetime as dt
from pathlib import Path
from typing import Any

import openpyxl
from conftest import LoadYaml, Problems
from fastapi.testclient import TestClient

from climblog.analytics import compute_view
from climblog.analytics.grade_charts import french_label
from climblog.catalog import Catalog, Entry
from climblog.config import AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module
from climblog.storage.cells import VALUE_ISSUES

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
GRADES = next(w for w in (JOURNAL.views or {})["progress"] if w.widget == "grades")
OCT = dt.date(2026, 10, 1)


def day(n: int) -> dt.date:
    return OCT + dt.timedelta(days=n - 1)


def session(
    n: int, grade: str | None, venue: str = "[ESEMPIO] Falesia", setting: str = "Outdoor"
) -> dict[str, Value]:
    return {
        "date": day(n),
        "session_no": 1,
        "hardest_grade": grade,
        "venue": venue,
        "setting": setting,
    }


def charts(*sessions: dict[str, Value], on: dt.date = dt.date(2026, 11, 30)) -> dict[str, Any]:
    [found] = compute_view(JOURNAL, [GRADES], {"session": list(sessions)}, {}, on)
    return found


def test_grade_labels() -> None:
    assert [french_label(i) for i in (30, 31, 32, 36, 32.5)] == ["6a", "6a+", "6b", "7a", "6b"]


def test_french_is_one_series_and_gym_one_per_venue() -> None:
    found = charts(
        session(1, "6b+"),
        session(2, "5", "[ESEMPIO] Palestra Nord", "Indoor"),
        session(3, "7", "[ESEMPIO] Palestra Sud", "Indoor"),
        session(4, "6c", "[ESEMPIO] Palestra Nord", "Indoor"),  # a French grade in a gym
        session(5, "6", "[ESEMPIO] Palestra Nord", "Indoor"),
    )
    assert [s["label"] for s in found["series"]] == [
        "French",
        "Gym · [ESEMPIO] Palestra Nord",
        "Gym · [ESEMPIO] Palestra Sud",
    ]
    french, nord, _ = found["series"]
    assert [(p["grade"], p["index"]) for p in french["points"]] == [("6b+", 33), ("6c", 34)]
    assert [p["index"] for p in nord["points"]] == [5, 6]
    assert french["points"][1]["setting"] == "Indoor"
    assert [t["label"] for t in found["french_ticks"]] == ["6b+", "6c"]


def test_the_pyramid_counts_sessions_by_hardest_grade_per_month() -> None:
    found = charts(session(1, "6a"), session(2, "6b"), session(3, "6a"), session(40, "6b"))
    pyramid = found["pyramid"]
    assert pyramid["periods"] == ["2026-10", "2026-11"]
    [row] = pyramid["rows"]
    assert (row["label"], row["grades"], row["counts"]) == (
        "French",
        ["6a", "6b"],
        [[2, 0], [1, 1]],
    )
    assert found["last"] == 6


def test_by_setting_and_venue() -> None:
    found = charts(
        session(1, "6a"),
        session(2, "6c"),
        session(3, "6b"),
        session(4, "5", "[ESEMPIO] Palestra Nord", "Indoor"),
        session(5, "6", "[ESEMPIO] Palestra Nord", "Indoor"),
        session(6, "22", "[ESEMPIO] Palestra Sud", "Indoor"),  # another gym, another scale
    )
    french = {"system": "french", "venue": None, "discipline": None}
    assert found["by_setting"] == [
        {"setting": "Outdoor", **french, "sessions": 3, "hardest": "6c", "median": "6b"},
        # gym grades per venue: one gym's 22 never meets another's 5 (D-094)
        {
            "setting": "Indoor",
            "discipline": None,
            "system": "gym",
            "venue": "[ESEMPIO] Palestra Nord",
            "sessions": 2,
            "hardest": "6",
            "median": "5",
        },
        {
            "setting": "Indoor",
            "discipline": None,
            "system": "gym",
            "venue": "[ESEMPIO] Palestra Sud",
            "sessions": 1,
            "hardest": "22",
            "median": "22",
        },
    ]
    assert [r["venue"] for r in found["by_venue"]] == [
        "[ESEMPIO] Falesia",
        "[ESEMPIO] Palestra Nord",
        "[ESEMPIO] Palestra Sud",
    ]


def test_a_slash_grade_keeps_its_text() -> None:
    found = charts(session(1, "7a/7a+"), session(2, "7a"), session(3, "6c+/7a"))
    [row] = found["pyramid"]["rows"]
    assert row["grades"] == ["6c+/7a", "7a", "7a/7a+"]
    assert found["by_setting"][0]["hardest"] == "7a/7a+"


def test_bad_values_are_counted_and_later_ones_left_out() -> None:
    found = charts(
        session(1, "hard"), session(2, None), session(3, "6a"), session(60, "7a"), on=day(10)
    )
    assert found["unparsed"] == 1
    assert [p["grade"] for p in found["series"][0]["points"]] == ["6a"]


def test_nothing_logged() -> None:
    found = charts()
    assert (found["series"], found["french_ticks"], found["pyramid"]) == (
        [],
        [],
        {"periods": [], "rows": []},
    )


def test_weekly_pyramid_without_venue_or_setting(load: LoadYaml) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "      venue: session.venue\n      setting: session.setting\n      group: month\n",
        "      group: week\n",
    )
    module = load(text)
    widget = next(w for w in (module.views or {})["progress"] if w.widget == "grades")
    rows = [session(1, "5"), session(9, "6a")]
    [found] = compute_view(module, [widget], {"session": rows}, {}, day(20))
    assert [s["label"] for s in found["series"]] == ["French", "Gym"]
    assert found["pyramid"]["periods"] == ["2026-W40", "2026-W41"]
    assert (found["by_setting"], found["by_venue"]) == ([], [])


def test_the_field_must_be_a_grade(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    bad = text.replace("      grade: session.hardest_grade\n", "      grade: session.venue\n")
    assert any("'session.venue' is not a grade field" in p for p in problems(bad))
    bad = text.replace(
        "      venue: session.venue\n      setting: session.setting\n      group: month",
        "      venue: rest_day.note\n      group: month",
    )
    assert any("'rest_day.note' is not a field of 'session'" in p for p in problems(bad))


def test_a_value_typed_in_the_sheet_that_isnt_a_grade_is_counted(tmp_path: Path) -> None:
    # the loader makes it a data issue and blanks it; the card still says it left one out
    book = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(book))
    writer = RecordWriter(JOURNAL, XlsxBackend(book))
    writer.add("session", {"date": "2026-10-05", "hardest_grade": "6b"})
    writer.add("session", {"date": "2026-10-06", "hardest_grade": "6c"})
    wb = openpyxl.load_workbook(book)
    tab = wb["Session"]
    column = next(c.column for c in tab[2] if c.value == "hardest_grade")
    tab.cell(4, column).value = "boh"  # the second session, typed by hand
    wb.save(book)
    catalog = Catalog(AppConfig())
    catalog.entries["journal"] = Entry(
        "journal",
        JOURNAL,
        [],
        CachedRepository("journal", XlsxBackend(book), Snapshots(tmp_path / "snapshots")),
    )
    tables, _ = catalog.full_tables(catalog.entries["journal"])
    assert [r.get(VALUE_ISSUES) for r in tables["session"]] == [None, "hardest_grade"]
    client = TestClient(create_app(catalog=catalog))
    body = client.get("/api/modules/journal/views/progress", params={"date": "2026-10-10"}).json()
    grades = next(w for w in body["widgets"] if w["widget"] == "grades")
    assert grades["unparsed"] == 1
    assert [p["grade"] for p in grades["series"][0]["points"]] == ["6b"]


SENDS = [w for w in (JOURNAL.views or {})["progress"] if w.widget == "grades"][1]


def climbed(n: int, **values: Value) -> dict[str, Value]:
    return {**session(n, None), **values}


def test_series_are_split_by_discipline_and_font_has_its_own() -> None:
    found = charts(
        climbed(1, hardest_grade="6b+"),  # before the discipline field: a series of its own
        climbed(2, hardest_grade="7a", tried_discipline="Sport"),
        climbed(3, hardest_grade="6B+", tried_discipline="Bouldering"),
        climbed(4, hardest_grade="6C", tried_discipline="Bouldering"),
        climbed(5, hardest_grade="5", tried_discipline="Bouldering", venue="[ESEMPIO] Blocco"),
    )
    assert [s["label"] for s in found["series"]] == [
        "French",
        "Sport · French",
        "Bouldering · Font",
        "Bouldering · Gym · [ESEMPIO] Blocco",
    ]
    font = found["series"][2]
    assert (font["system"], font["discipline"]) == ("font", "Bouldering")
    assert [p["grade"] for p in font["points"]] == ["6B+", "6C"]
    assert [t["label"] for t in found["font_ticks"]] == ["6B+", "6C"]
    assert [t["label"] for t in found["french_ticks"]][:2] == ["6b+", "6c"]
    assert [r["label"] for r in found["pyramid"]["rows"]] == [s["label"] for s in found["series"]]
    assert [(r["discipline"], r["system"]) for r in found["by_venue"]] == [
        (None, "french"),
        ("Sport", "french"),
        ("Bouldering", "font"),
        ("Bouldering", "gym"),
    ]
    assert found["grade_label"] == "Hardest grade tried"


def test_the_hardest_send_with_how_it_was_climbed() -> None:
    [found] = compute_view(
        JOURNAL,
        [SENDS],
        {
            "session": [
                climbed(1, hardest_grade="7a", hardest_send="6c+", send_discipline="Sport",
                        send_type="Redpoint / send"),
                climbed(2, hardest_grade="6C", hardest_send="6B", send_discipline="Bouldering",
                        send_type="Flash"),
                climbed(3, hardest_grade="6a"),  # tried, nothing sent: not in the sends
            ]
        },
        {},
        dt.date(2026, 11, 30),
    )  # fmt: skip
    assert found["grade_label"] == "Hardest send"
    sends = [(s["label"], [(p["grade"], p["style"]) for p in s["points"]]) for s in found["series"]]
    assert sends == [
        ("Sport · French", [("6c+", "Redpoint / send")]),
        ("Bouldering · Font", [("6B", "Flash")]),
    ]


def test_the_discipline_must_be_of_the_grade_entity(problems: Problems) -> None:
    text = (ROOT / "modules" / "journal.yaml").read_text(encoding="utf-8")
    bad = text.replace(
        "      discipline: session.tried_discipline\n", "      discipline: rest_day.rest_type\n"
    )
    assert any("discipline" in p for p in problems(bad)), problems(bad)
