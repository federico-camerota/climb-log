# SPDX-License-Identifier: GPL-3.0-or-later
"""Metrics of every module and metric queries (05-analytics.md §1, D-090).

`GET /api/metrics`: the catalogue, every numeric field and derived value of the loaded modules
(`journal.session.wb_score`) and the choice fields that filter them.
`GET /api/metrics/query?metric=journal.session.wb_score&group=week&agg=mean&start=2026-10-01`:
the metrics lined up by record, day, week or month (`analytics/metrics.py`); `filter` is
`module.entity.field=value`, repeated for several values. Bookmarkable: everything is in the
URL.
"""

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from climblog.analytics.metrics import (
    Agg,
    Group,
    QueryError,
    Series,
    Source,
    catalogue,
    run_query,
)
from climblog.analytics.metrics import Query as MetricQuery
from climblog.analytics.views import line_bands
from climblog.api.modules import catalog
from climblog.api.views import BandData
from climblog.storage import StorageError

router = APIRouter()


class MetricInfo(BaseModel):
    id: str
    module: str
    entity: str
    field: str
    label: str
    section: str | None
    derived: bool
    unit: str | None
    scale: tuple[float, float] | None
    direction: str | None


class FilterInfo(BaseModel):
    id: str
    module: str
    entity: str
    field: str
    label: str
    choices: list[str]


class MetricCatalogue(BaseModel):
    metrics: list[MetricInfo]
    filters: list[FilterInfo]


class PointData(BaseModel):
    start: dt.date
    end: dt.date
    label: str
    key: dict[str, Any] | None


class MetricSeries(BaseModel):
    metric: str
    values: list[float | None]
    n: list[int]
    rolling: list[float | None] | None
    bands: list[BandData] | None = None  # LOW/WATCH/GOOD, as a dashboard line draws them


class SourceInfo(BaseModel):
    module: str
    as_of: dt.datetime | None
    offline: bool


class QueryResult(BaseModel):
    group: Group
    agg: Agg
    lag: int
    points: list[PointData]
    series: list[MetricSeries]
    sources: list[SourceInfo]  # when each module's data was read


@router.get("/metrics")
def get_metrics(request: Request) -> MetricCatalogue:
    """Every loaded module's metrics and filters, in config and YAML order."""
    current = catalog(request)
    metrics: list[MetricInfo] = []
    filters: list[FilterInfo] = []
    for name, entry in current.entries.items():
        if entry.module is None:
            continue
        found = catalogue(name, entry.module)
        metrics += [MetricInfo.model_validate(m, from_attributes=True) for m in found.metrics]
        filters += [FilterInfo.model_validate(f, from_attributes=True) for f in found.filters]
    return MetricCatalogue(metrics=metrics, filters=filters)


@router.get("/metrics/query")
def query_metrics(
    request: Request,
    metric: Annotated[list[str], Query()],
    start: dt.date | None = None,
    end: dt.date | None = None,
    group: Group = "day",
    agg: Agg = "mean",
    rolling: int | None = None,
    lag: Annotated[int, Query(ge=-31, le=31)] = 0,
    filter: Annotated[list[str] | None, Query()] = None,  # `filter` as in the URL
) -> QueryResult:
    """The metrics lined up by record, day, week or month (see the module docstring)."""
    filters = parse_filters(filter)
    settings: dict[str, dict[str, Any]] = {}
    sources, read = read_sources(request, metric, settings)
    asked = MetricQuery(metric, start, end, group, agg, rolling, lag, filters)
    try:
        result = run_query(asked, sources, dt.date.today())
    except QueryError as error:
        raise HTTPException(400, str(error)) from None
    return QueryResult(
        group=result.group,
        agg=result.agg,
        lag=result.lag,
        points=[PointData.model_validate(p, from_attributes=True) for p in result.points],
        series=[_series(s, sources, settings) for s in result.series],
        sources=read,
    )


def parse_filters(items: list[str] | None) -> dict[str, list[str]]:
    """`module.entity.field=value` items as {filter: values}; 400 for one without `=`."""
    filters: dict[str, list[str]] = {}
    for item in items or []:
        f_id, sep, value = item.partition("=")
        if not sep:
            raise HTTPException(400, f"a filter is 'module.entity.field=value', not {item!r}")
        filters.setdefault(f_id, []).append(value)
    return filters


def read_sources(
    request: Request, metrics: list[str], settings: dict[str, dict[str, Any]] | None = None
) -> tuple[dict[str, Source], list[SourceInfo]]:
    """The records of the modules the metrics belong to (unknown modules are left out: the
    query then says their metrics are unknown); 503 if one can't be read. With `settings`,
    each module's settings are put there too (for the status bands)."""
    current = catalog(request)
    sources: dict[str, Source] = {}
    read: list[SourceInfo] = []
    for name in dict.fromkeys(m.partition(".")[0] for m in metrics):
        entry = current.entries.get(name)
        if entry is None or entry.module is None or entry.repo is None:
            continue
        try:
            tables, found = current.full_tables(entry)
        except StorageError as error:
            raise HTTPException(503, str(error)) from None
        sources[name] = (entry.module, tables)
        if settings is not None:
            settings[name] = dict(found)
        read.append(SourceInfo(module=name, as_of=entry.repo.as_of, offline=entry.repo.offline))
    return sources, read


def _series(
    found: Series, sources: dict[str, Source], settings: dict[str, dict[str, Any]]
) -> MetricSeries:
    """A series of the answer, with the status bands of its metric if a dashboard line has them."""
    data = MetricSeries.model_validate(found, from_attributes=True)
    name, _, metric = found.metric.partition(".")
    bands = line_bands(sources[name][0], metric, settings.get(name, {}))
    if bands is not None:
        data.bands = [BandData.model_validate(b) for b in bands]
    return data
