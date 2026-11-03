// SPDX-License-Identifier: GPL-3.0-or-later
// The Explore page's state and chart (#102, D-095): everything lives in the page's URL, so a
// view can be bookmarked; the metric query (D-090) is built from it.
import dayjs from "dayjs";
import type { EChartsCoreOption } from "echarts/core";

import type { MetricInfo, QueryResult } from "../api/client";
import { decimal, PALETTE } from "./charts";

export type RangeKey = "7d" | "30d" | "90d" | "all" | "custom";
export type GroupKey = "none" | "day" | "week" | "month";
export type AggKey = "mean" | "min" | "max" | "sum" | "count" | "latest";
export type ChartKind = "line" | "bars";

export const RANGE_DAYS: Partial<Record<RangeKey, number>> = { "7d": 7, "30d": 30, "90d": 90 };
export const MAX_UNITS = 2; // one y axis each

export interface ExploreState {
  metrics: string[];
  range: RangeKey;
  start: string | null; // custom range
  end: string | null;
  group: GroupKey;
  agg: AggKey;
  rolling: number | null;
  filters: Record<string, string[]>; // filter id → values kept
  chart: ChartKind;
}

function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** The page's state from its URL (unknown values fall back to the defaults). */
export function readState(params: URLSearchParams): ExploreState {
  const filters: Record<string, string[]> = {};
  for (const item of params.getAll("filter")) {
    const at = item.indexOf("=");
    if (at > 0) (filters[item.slice(0, at)] ??= []).push(item.slice(at + 1));
  }
  const rolling = Number(params.get("rolling"));
  return {
    metrics: params.getAll("metric"),
    range: oneOf(params.get("range"), ["7d", "30d", "90d", "all", "custom"] as const, "90d"),
    start: params.get("start"),
    end: params.get("end"),
    group: oneOf(params.get("group"), ["none", "day", "week", "month"] as const, "day"),
    agg: oneOf(
      params.get("agg"),
      ["mean", "min", "max", "sum", "count", "latest"] as const,
      "mean",
    ),
    rolling: Number.isInteger(rolling) && rolling >= 2 ? rolling : null,
    filters,
    chart: oneOf(params.get("chart"), ["line", "bars"] as const, "line"),
  };
}

/** The URL of a state (the defaults left out). */
export function writeState(state: ExploreState): URLSearchParams {
  const params = new URLSearchParams();
  for (const m of state.metrics) params.append("metric", m);
  if (state.range !== "90d") params.set("range", state.range);
  if (state.range === "custom") {
    if (state.start) params.set("start", state.start);
    if (state.end) params.set("end", state.end);
  }
  if (state.group !== "day") params.set("group", state.group);
  if (state.agg !== "mean") params.set("agg", state.agg);
  if (state.rolling !== null) params.set("rolling", String(state.rolling));
  for (const [id, values] of Object.entries(state.filters))
    for (const v of values) params.append("filter", `${id}=${v}`);
  if (state.chart !== "line") params.set("chart", state.chart);
  return params;
}

/** The metric query of a state, for the day `today` (null: no metric picked). */
export function metricQuery(state: ExploreState, today: string): string | null {
  if (state.metrics.length === 0) return null;
  const params = new URLSearchParams();
  for (const m of state.metrics) params.append("metric", m);
  const days = RANGE_DAYS[state.range];
  if (days !== undefined) {
    params.set(
      "start",
      dayjs(today)
        .subtract(days - 1, "day")
        .format("YYYY-MM-DD"),
    );
    params.set("end", today);
  } else if (state.range === "custom") {
    if (state.start) params.set("start", state.start);
    params.set("end", state.end ?? today);
  } else {
    params.set("end", today);
  }
  params.set("group", state.group);
  params.set("agg", state.agg);
  if (state.rolling !== null) params.set("rolling", String(state.rolling));
  for (const [id, values] of Object.entries(state.filters))
    for (const v of values) params.append("filter", `${id}=${v}`);
  return params.toString();
}

/** What a metric's values are measured in, for the axes: its unit, a 1–10 scale, or a plain
 * number. */
export function unitOf(metric: MetricInfo): string {
  if (metric.unit) return metric.unit;
  if (metric.scale) return `${String(metric.scale[0])}–${String(metric.scale[1])}`;
  return "value";
}

/** Whether `metric` can join `picked` without a third unit. */
export function fits(metric: MetricInfo, picked: MetricInfo[]): boolean {
  const units = new Set(picked.map(unitOf));
  return units.has(unitOf(metric)) || units.size < MAX_UNITS;
}

/** A metric's name in a picker: its label and where it comes from. */
export function metricGroup(metric: MetricInfo): string {
  return [metric.module, metric.entity.replace("_", " "), metric.section]
    .filter((x) => x)
    .join(" · ");
}

/** "30/10/26", "2026-W44", "2026-10": the points' labels as the API gives them, days shorter. */
export function pointLabel(point: QueryResult["points"][number]): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(point.label)) return point.label;
  const label = dayjs(point.start).format("DD/MM/YY");
  const n = Object.values(point.key ?? {}).find((v): v is number => typeof v === "number" && v > 1);
  return n === undefined ? label : `${label} (${String(n)})`;
}

export function exploreOption(
  result: QueryResult,
  metrics: MetricInfo[],
  chart: ChartKind,
): EChartsCoreOption {
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const units = [...new Set(result.series.map((s) => unitOf(byId.get(s.metric) as MetricInfo)))];
  const labels = result.points.map(pointLabel);
  const lines = result.series.flatMap((series, i) => {
    const metric = byId.get(series.metric);
    const name = metric?.label ?? series.metric;
    const axis = metric ? units.indexOf(unitOf(metric)) : 0;
    const colour = PALETTE[i % PALETTE.length];
    const main = {
      type: chart === "bars" ? "bar" : "line",
      name,
      yAxisIndex: axis,
      data: series.values,
      connectNulls: true,
      symbolSize: 6,
      itemStyle: { color: colour },
      lineStyle: { opacity: series.rolling ? 0.35 : 1 },
    };
    if (!series.rolling) return [main];
    return [
      main,
      {
        type: "line",
        name: `${name} (rolling mean)`,
        yAxisIndex: axis,
        data: series.rolling,
        connectNulls: true,
        showSymbol: false,
        itemStyle: { color: colour },
        lineStyle: { width: 3 },
      },
    ];
  });
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params: { dataIndex: number; seriesName: string; value: number | null }[]) => {
        const i = params[0]?.dataIndex ?? 0;
        const rows = params.map((p) => {
          const series = result.series.find(
            (s) => (byId.get(s.metric)?.label ?? s.metric) === p.seriesName,
          );
          const n = series ? ` (n = ${String(series.n[i] ?? 0)})` : "";
          return `${p.seriesName}: ${decimal(p.value)}${n}`;
        });
        return [labels[i] ?? "", ...rows].join("<br/>");
      },
    },
    legend: { top: 0 },
    grid: { left: 56, right: units.length > 1 ? 56 : 24, top: 48, bottom: 64 },
    xAxis: { type: "category", data: labels, boundaryGap: chart === "bars" },
    yAxis: units.map((unit, i) => ({
      type: "value",
      name: unit,
      scale: chart === "line",
      splitLine: { show: i === 0 },
    })),
    dataZoom: [{ type: "slider" }, { type: "inside" }],
    series: lines,
  };
}
