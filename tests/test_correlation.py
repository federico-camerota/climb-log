# SPDX-License-Identifier: GPL-3.0-or-later
"""Correlations (#103, D-096): n, 95% CIs, too few points, the matrix and the pre-session
metrics. Fictional data; the statistics are checked by hand where it's short."""

import datetime as dt
import math
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from climblog.analytics.correlation import aligned, matrix, pair, pre_session, predictors
from climblog.analytics.metrics import QueryError
from climblog.catalog import Catalog, Entry
from climblog.config import AnalyticsConfig, AppConfig
from climblog.expr import Value
from climblog.main import create_app
from climblog.modules import load_module
from climblog.storage import CachedRepository, RecordWriter, Snapshots, XlsxBackend, sync_module

ROOT = Path(__file__).parent.parent
JOURNAL = load_module(ROOT / "modules" / "journal.yaml")
OCT = dt.date(2026, 10, 1)
TODAY = dt.date(2026, 11, 30)
SLEEP, FEEL = "journal.session.wb_sleep_hours", "journal.session.feel_score"


def day(n: int) -> dt.date:
    return OCT + dt.timedelta(days=n - 1)


def sources(
    sessions: Sequence[Mapping[str, Any]], rests: Sequence[Mapping[str, Any]] | None = None
) -> Any:
    return {"journal": (JOURNAL, {"session": sessions, "rest_day": rests or []})}


def sessions_of(pairs: Sequence[tuple[float, float]]) -> list[dict[str, Value]]:
    return [
        {"date": day(i + 1), "session_no": 1, "wb_sleep_hours": x, "feel_score": y}
        for i, (x, y) in enumerate(pairs)
    ]


DATA = [
    (6, 5),
    (7, 6),
    (8, 8),
    (6.5, 6),
    (7.5, 7),
    (5, 4),
    (8.5, 9),
    (7, 7),
    (6, 6),
    (9, 8),
    (5.5, 5),
    (8, 7),
]


def test_pearson_and_its_fisher_ci() -> None:
    points = aligned(SLEEP, FEEL, sources(sessions_of(DATA)), TODAY)
    found = pair(SLEEP, FEEL, points, min_n=10)
    xs, ys = [p[0] for p in DATA], [p[1] for p in DATA]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    r = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True)) / math.sqrt(
        sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)
    )
    z, se = math.atanh(r), 1 / math.sqrt(n - 3)
    assert found.n == 12 and not found.too_few
    assert found.pearson.r == round(r, 4)
    assert found.pearson.low == round(math.tanh(z - 1.959963984540054 * se), 4)
    assert found.pearson.high == round(math.tanh(z + 1.959963984540054 * se), 4)
    assert found.pearson.p is not None and found.pearson.p < 0.001
    assert found.spearman.r is not None and 0.8 < found.spearman.r < 1
    assert found.spearman.low is not None and found.spearman.low < found.spearman.r
    assert found.slope is not None and found.slope > 0


def test_too_few_points_are_flagged_and_tiny_samples_have_no_r() -> None:
    few = pair(SLEEP, FEEL, aligned(SLEEP, FEEL, sources(sessions_of(DATA[:6])), TODAY), min_n=10)
    assert (few.n, few.too_few, few.pearson.r is not None) == (6, True, True)
    tiny = pair(SLEEP, FEEL, aligned(SLEEP, FEEL, sources(sessions_of(DATA[:3])), TODAY), min_n=10)
    assert (tiny.pearson.r, tiny.spearman.r, tiny.slope is not None) == (None, None, True)
    flat = pair(
        SLEEP,
        FEEL,
        aligned(SLEEP, FEEL, sources(sessions_of([(7, y) for y in range(5)])), TODAY),
        3,
    )
    assert (flat.pearson.r, flat.slope) == (None, None)  # no spread in x
    perfect = pair(
        SLEEP,
        FEEL,
        aligned(SLEEP, FEEL, sources(sessions_of([(x, 2 * x) for x in range(1, 7)])), TODAY),
        3,
    )
    assert (perfect.pearson.r, perfect.pearson.low, perfect.pearson.high) == (1.0, 1.0, 1.0)


def test_a_pair_across_entities_with_a_lag() -> None:
    sessions = [{"date": day(n), "session_no": 1, "feel_score": f} for n, f in [(1, 8), (3, 5)]]
    rests: list[dict[str, Value]] = [{"date": day(2), "mood": 7}, {"date": day(4), "mood": 4}]
    points = aligned(FEEL, "journal.rest_day.mood", sources(sessions, rests), TODAY, lag=1)
    assert points == [(8, 7, "2026-10-01"), (5, 4, "2026-10-03")]
    with pytest.raises(QueryError, match="one entity and no lag"):
        aligned(FEEL, "journal.rest_day.mood", sources(sessions, rests), TODAY, group="none")


def test_the_matrix_hides_cells_under_the_minimum_n() -> None:
    rows = sessions_of(DATA)
    for i, row in enumerate(rows):
        row["wb_mood_pre"] = 5 + i % 3 if i < 6 else None  # only 6 days
    cells = matrix([SLEEP, FEEL, "journal.session.wb_mood_pre"], sources(rows), TODAY, min_n=10)
    assert cells[0][0].r == 1.0 and cells[0][0].n == 12
    assert cells[0][1].r is not None and cells[0][1] == cells[1][0]
    assert (cells[0][2].r, cells[0][2].n) == (None, 6)  # hidden
    with pytest.raises(QueryError, match="2 to 12"):
        matrix([SLEEP], sources(rows), TODAY, 10)


def test_pre_session_metrics_are_known_before_climbing() -> None:
    found = {m.field for m in pre_session(JOURNAL, "journal", "session")}
    for name in [
        "wb_sleep_hours",
        "wb_mood_pre",
        "ph_pre_fingers",
        "mn_life_stress",
        "ph_readiness",
        "days_since_prev",
    ]:
        assert name in found
    for name in [
        "wb_mood_post",
        "feel_effort",
        "duration_min",
        "wb_score",
        "feel_score",
        "overall_score",
        "session_load",
    ]:
        assert name not in found


def test_predictors_are_ranked_with_the_too_few_last() -> None:
    rows = sessions_of(DATA)
    for i, row in enumerate(rows):
        row["wb_mood_pre"] = [5, 9, 2, 7, 4, 6, 8, 3, 5, 6, 7, 4][i]  # unrelated
        row["mn_confidence"] = 7 if i < 5 else None
    found = predictors(FEEL, sources(rows), TODAY, min_n=10)
    assert found[0].metric == SLEEP
    ranked = [p for p in found if not p.too_few and p.stat.r is not None]
    assert [abs(p.stat.r or 0) for p in ranked] == sorted(
        (abs(p.stat.r or 0) for p in ranked), reverse=True
    )
    confidence = next(p for p in found if p.metric == "journal.session.mn_confidence")
    assert confidence.too_few and found.index(confidence) > found.index(ranked[-1])
    with pytest.raises(QueryError, match="unknown metric"):
        predictors("other.session.x", sources(rows), TODAY, 10)


# ---- The API ----


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "journal.xlsx"
    sync_module(JOURNAL, XlsxBackend(path))
    writer = RecordWriter(JOURNAL, XlsxBackend(path))
    for i, (sleep, enjoy) in enumerate([(6, 5), (7, 6), (8, 8), (6.5, 6), (7.5, 7)]):
        writer.add(
            "session",
            {
                "date": f"2026-10-{i + 1:02d}",
                "wb_sleep_hours": sleep,
                "feel_enjoyment": enjoy,
                "feel_satisfaction": enjoy,
            },
        )
    catalog = Catalog(AppConfig(analytics=AnalyticsConfig(min_n=4)))
    cached = CachedRepository("journal", XlsxBackend(path), Snapshots(tmp_path / "snapshots"))
    catalog.entries["journal"] = Entry("journal", JOURNAL, [], cached)
    yield TestClient(create_app(catalog=catalog))


def test_the_pair_api(client: TestClient) -> None:
    body = client.get("/api/correlation/pair", params={"x": SLEEP, "y": FEEL}).json()
    assert (body["n"], body["min_n"], body["too_few"]) == (5, 4, False)
    assert body["points"][0] == {"x": 6.0, "y": 5.0, "date": "2026-10-01"}
    assert body["pearson"]["r"] > 0.9
    bad = client.get("/api/correlation/pair", params={"x": SLEEP, "y": "journal.session.nope"})
    assert (bad.status_code, bad.json()["detail"]) == (
        400,
        "unknown metric(s): journal.session.nope",
    )


def test_the_matrix_and_predictors_api(client: TestClient) -> None:
    body = client.get("/api/correlation/matrix", params={"metric": [SLEEP, FEEL]}).json()
    assert (body["method"], body["cells"][0][1]["n"]) == ("spearman", 5)
    assert client.get("/api/correlation/matrix", params={"metric": [SLEEP]}).status_code == 400
    ranked = client.get("/api/correlation/predictors", params={"target": FEEL}).json()
    assert ranked["predictors"][0]["metric"] == SLEEP
    bad = client.get("/api/correlation/predictors", params={"target": "x.y.z"})
    assert bad.status_code == 400
