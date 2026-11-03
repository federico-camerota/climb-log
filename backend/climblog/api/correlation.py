# SPDX-License-Identifier: GPL-3.0-or-later
"""Correlations between metrics (05-analytics.md §3.2, D-096): n, 95% CI, `too_few` under the
app config's `[analytics] min_n` (default 10).

`GET /api/correlation/pair?x=…&y=…&lag=1`: the points and Pearson and Spearman r.
`GET /api/correlation/matrix?metric=…&metric=…&method=spearman`: every pair, hidden under n.
`GET /api/correlation/predictors?target=journal.session.feel_score`: each pre-session metric
against a session score, ranked.
"""

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from climblog.analytics.correlation import Method, aligned, matrix, pair, predictors
from climblog.analytics.metrics import QueryError
from climblog.api.metrics import SourceInfo, parse_filters, read_sources
from climblog.api.modules import catalog

router = APIRouter()


class StatData(BaseModel):
    r: float | None
    low: float | None  # the 95% CI
    high: float | None
    p: float | None


class PairPoint(BaseModel):
    x: float
    y: float
    date: dt.date


class CorrelationPair(BaseModel):
    x: str
    y: str
    lag: int
    n: int
    min_n: int
    too_few: bool  # n under min_n: read with care (greyed out)
    pearson: StatData
    spearman: StatData
    slope: float | None
    intercept: float | None
    points: list[PairPoint]
    sources: list[SourceInfo]


class CellData(BaseModel):
    r: float | None  # hidden under min_n
    n: int


class MatrixData(BaseModel):
    metrics: list[str]
    method: Method
    min_n: int
    cells: list[list[CellData]]
    sources: list[SourceInfo]


class PredictorData(BaseModel):
    metric: str
    n: int
    too_few: bool
    stat: StatData


class PredictorsData(BaseModel):
    target: str
    method: Method
    min_n: int
    predictors: list[PredictorData]
    sources: list[SourceInfo]


def _min_n(request: Request) -> int:
    return catalog(request).config.analytics.min_n


@router.get("/correlation/pair")
def get_pair(
    request: Request,
    x: str,
    y: str,
    lag: Annotated[int, Query(ge=-31, le=31)] = 0,
    group: Literal["none", "day", "week", "month"] | None = None,  # default: record or day
    start: dt.date | None = None,
    end: dt.date | None = None,
    filter: Annotated[list[str] | None, Query()] = None,  # `filter` as in the URL
) -> CorrelationPair:
    """X against Y, per record (one entity, no lag) or per day with Y read `lag` days later;
    `group` asks for days, weeks or months instead (each point a period's means)."""
    sources, read = read_sources(request, [x, y])
    min_n = _min_n(request)
    try:
        points = aligned(
            x,
            y,
            sources,
            dt.date.today(),
            lag=lag,
            group=group,
            start=start,
            end=end,
            filters=parse_filters(filter),
        )
    except QueryError as error:
        raise HTTPException(400, str(error)) from None
    found = pair(x, y, points, min_n, lag)
    return CorrelationPair.model_validate(
        {
            **found.__dict__,
            "pearson": found.pearson.__dict__,
            "spearman": found.spearman.__dict__,
            "points": [{"x": a, "y": b, "date": d} for a, b, d in found.points],
            "min_n": min_n,
            "sources": read,
        }
    )


@router.get("/correlation/matrix")
def get_matrix(
    request: Request,
    metric: Annotated[list[str], Query()],
    method: Method = "spearman",
    start: dt.date | None = None,
    end: dt.date | None = None,
    filter: Annotated[list[str] | None, Query()] = None,  # each applies to its entity's metrics
) -> MatrixData:
    """Every pair of the metrics per day; a cell under the minimum n is hidden."""
    sources, read = read_sources(request, metric)
    min_n = _min_n(request)
    try:
        cells = matrix(
            metric,
            sources,
            dt.date.today(),
            min_n,
            method,
            start=start,
            end=end,
            filters=parse_filters(filter),
        )
    except QueryError as error:
        raise HTTPException(400, str(error)) from None
    return MatrixData(
        metrics=metric,
        method=method,
        min_n=min_n,
        cells=[[CellData(r=c.r, n=c.n) for c in row] for row in cells],
        sources=read,
    )


@router.get("/correlation/predictors")
def get_predictors(
    request: Request,
    target: str,
    method: Method = "spearman",
    start: dt.date | None = None,
    end: dt.date | None = None,
    filter: Annotated[list[str] | None, Query()] = None,  # each applies to its entity's metrics
) -> PredictorsData:
    """Each pre-session metric of the target's entity against it, ranked by |r|."""
    sources, read = read_sources(request, [target])
    min_n = _min_n(request)
    try:
        found = predictors(
            target,
            sources,
            dt.date.today(),
            min_n,
            method,
            start=start,
            end=end,
            filters=parse_filters(filter),
        )
    except QueryError as error:
        raise HTTPException(400, str(error)) from None
    return PredictorsData(
        target=target,
        method=method,
        min_n=min_n,
        predictors=[
            PredictorData(
                metric=p.metric, n=p.n, too_few=p.too_few, stat=StatData(**p.stat.__dict__)
            )
            for p in found
        ],
        sources=read,
    )
