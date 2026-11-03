// SPDX-License-Identifier: GPL-3.0-or-later
// The Explore page's correlation tabs (#103, D-096): their URL state, the queries and the
// charts. Every number comes with n and a 95% CI; under the minimum n it is greyed out.
import type { EChartsCoreOption } from "echarts/core";

import type { CorrelationPair, MatrixData } from "../api/client";
import { decimal, PALETTE } from "./charts";

export type Tab = "trends" | "pair" | "matrix" | "predictors";
export type Method = "spearman" | "pearson";
/** A pair's points: per record within one entity without a lag, else per day ("auto"); or
 * per day, week or month (each point the period's means; 05-analytics §3.2). */
export type PairGroup = "auto" | "none" | "day" | "week" | "month";
const PAIR_GROUPS: readonly PairGroup[] = ["auto", "none", "day", "week", "month"];

export interface CorrelationState {
  tab: Tab;
  x: string | null;
  y: string | null;
  lag: number;
  group: PairGroup;
  matrix: string[];
  target: string | null;
  method: Method;
}

export function readCorrelation(params: URLSearchParams): CorrelationState {
  const tab = params.get("tab");
  const lag = Number(params.get("lag"));
  return {
    tab: tab === "pair" || tab === "matrix" || tab === "predictors" ? tab : "trends",
    x: params.get("x"),
    y: params.get("y"),
    lag: Number.isInteger(lag) && Math.abs(lag) <= 31 ? lag : 0,
    group: PAIR_GROUPS.find((g) => g === params.get("points")) ?? "auto",
    matrix: params.getAll("mx"),
    target: params.get("target"),
    method: params.get("method") === "pearson" ? "pearson" : "spearman",
  };
}

/** Writes the correlation state into `params` (the trends' own keys are kept). */
export function writeCorrelation(
  params: URLSearchParams,
  state: CorrelationState,
): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of ["tab", "x", "y", "lag", "points", "mx", "target", "method"]) next.delete(key);
  if (state.tab !== "trends") next.set("tab", state.tab);
  if (state.x) next.set("x", state.x);
  if (state.y) next.set("y", state.y);
  if (state.lag !== 0) next.set("lag", String(state.lag));
  if (state.group !== "auto") next.set("points", state.group);
  for (const m of state.matrix) next.append("mx", m);
  if (state.target) next.set("target", state.target);
  if (state.method !== "spearman") next.set("method", state.method);
  return next;
}

/** The API query of a tab, over the trends' date range and filters (`window`: their start,
 * end and filter parameters; a filter applies to its own entity's metrics). */
export function correlationQuery(state: CorrelationState, window: URLSearchParams): string | null {
  const params = new URLSearchParams();
  if (state.tab === "pair") {
    if (!state.x || !state.y) return null;
    params.set("x", state.x);
    params.set("y", state.y);
    if (state.lag !== 0) params.set("lag", String(state.lag));
    if (state.group !== "auto") params.set("group", state.group);
  } else if (state.tab === "matrix") {
    if (state.matrix.length < 2) return null;
    for (const m of state.matrix) params.append("metric", m);
    params.set("method", state.method);
  } else if (state.tab === "predictors") {
    if (!state.target) return null;
    params.set("target", state.target);
    params.set("method", state.method);
  } else {
    return null;
  }
  for (const key of ["start", "end"]) {
    const value = window.get(key);
    if (value) params.set(key, value);
  }
  for (const f of window.getAll("filter")) params.append("filter", f);
  return params.toString();
}

/** "0,62 (0,31 to 0,82)": r with its 95% CI, or a dash. */
export function withCi(stat: {
  r: number | null;
  low: number | null;
  high: number | null;
}): string {
  if (stat.r === null) return "–";
  const r = stat.r.toFixed(2).replace(".", ",");
  if (stat.low === null || stat.high === null) return r;
  const [low, high] = [stat.low, stat.high].map((v) => v.toFixed(2).replace(".", ","));
  return `${r} (${low ?? ""} to ${high ?? ""})`;
}

/** Plain words for an r, never causal (05-analytics §0); when its 95% interval includes 0,
 * they say there could be none. */
export function strength(stat: {
  r: number | null;
  low?: number | null;
  high?: number | null;
}): string {
  const { r, low = null, high = null } = stat;
  if (r === null) return "no estimate";
  const size = Math.abs(r);
  if (size < 0.1) return "no clear association";
  const word = size < 0.3 ? "weak" : size < 0.5 ? "moderate" : "strong";
  const words = `a ${word} ${r > 0 ? "positive" : "negative"} association`;
  const unsure = low !== null && high !== null && low <= 0 && high >= 0;
  return unsure ? `${words} (could be none: the interval includes 0)` : words;
}

export function pairOption(
  data: CorrelationPair,
  names: Map<string, string>, // the metrics' names, told apart (lib/explore metricNames)
): EChartsCoreOption {
  const xName = names.get(data.x) ?? data.x;
  const yName =
    data.lag === 0
      ? (names.get(data.y) ?? data.y)
      : `${names.get(data.y) ?? data.y} (${String(data.lag)} day(s) later)`;
  const series: Record<string, unknown>[] = [
    {
      type: "scatter",
      name: yName,
      data: data.points.map((p) => [p.x, p.y, p.date]),
      symbolSize: 9,
      itemStyle: { color: PALETTE[0], opacity: data.too_few ? 0.35 : 0.8 },
    },
  ];
  if (data.slope !== null && data.intercept !== null && data.points.length > 0) {
    const xs = data.points.map((p) => p.x);
    const [from, to] = [Math.min(...xs), Math.max(...xs)];
    series.push({
      type: "line",
      name: "Least-squares line",
      data: [
        [from, data.intercept + data.slope * from],
        [to, data.intercept + data.slope * to],
      ],
      symbol: "none",
      lineStyle: { color: "#868e96", type: "dashed" },
    });
  }
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: { value: [number, number, string?] }) =>
        `${p.value[2] ?? ""}<br/>${xName}: ${decimal(p.value[0])}<br/>${yName}: ${decimal(p.value[1])}`,
    },
    grid: { left: 56, right: 24, top: 24, bottom: 48 },
    xAxis: { type: "value", scale: true, name: xName, nameLocation: "middle", nameGap: 28 },
    yAxis: { type: "value", scale: true, name: yName },
    series,
  };
}

/** The matrix as a heatmap from -1 (red) to 1 (blue); a hidden cell shows its n. */
export function matrixOption(data: MatrixData, labels: string[]): EChartsCoreOption {
  const cells = data.cells.flatMap((row, i) =>
    row.map((cell, j) => [j, i, cell.r === null ? "-" : cell.r, cell.n]),
  );
  return {
    tooltip: {
      formatter: (p: { value: [number, number, number | string, number] }) =>
        `${labels[p.value[1]] ?? ""} × ${labels[p.value[0]] ?? ""}: ${
          typeof p.value[2] === "number" ? p.value[2].toFixed(2).replace(".", ",") : "too few"
        } (n = ${String(p.value[3])})`,
    },
    grid: { left: 140, right: 24, top: 16, bottom: 100 },
    xAxis: { type: "category", data: labels, axisLabel: { rotate: 30 } },
    yAxis: { type: "category", data: labels, inverse: true },
    visualMap: {
      dimension: 2, // r: each cell is [column, row, r, n]
      min: -1,
      max: 1,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: { color: ["#e03131", "#f8f9fa", "#1c7ed6"] },
    },
    series: [
      {
        type: "heatmap",
        data: cells,
        label: {
          show: true,
          formatter: (p: { value: [number, number, number | string, number] }) =>
            typeof p.value[2] === "number"
              ? p.value[2].toFixed(2).replace(".", ",")
              : `n ${String(p.value[3])}`,
        },
      },
    ],
  };
}
