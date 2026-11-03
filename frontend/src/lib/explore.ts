// SPDX-License-Identifier: GPL-3.0-or-later
// The Explore page's state and chart (#102, D-095): everything lives in the page's URL, so a
// view can be bookmarked; the metric query (D-090) is built from it.
import dayjs from "dayjs";
import type { EChartsCoreOption } from "echarts/core";

import type { MetricInfo, QueryResult } from "../api/client";
import { decimal, PALETTE, THICK_LINE_ICON } from "./charts";

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

/** What a metric's values are measured in, for the axes: its unit or its scale (1–10). A
 * metric with neither is a unit of its own (its id), so two of them never share an axis where
 * one could hide the other (a weekly load of 2000 next to one of 40). */
export function unitOf(metric: MetricInfo): string {
  if (metric.unit) return metric.unit;
  if (metric.scale) return `${String(metric.scale[0])}–${String(metric.scale[1])}`;
  return `#${metric.id}`;
}

/** An axis's name: the unit, else the metric's own name. */
export function axisName(metric: MetricInfo, names: Map<string, string>): string {
  const unit = unitOf(metric);
  return unit.startsWith("#") ? (names.get(metric.id) ?? metric.label) : unit;
}

/** Every metric's name, told apart where labels repeat: "Mood · Wellbeing · before",
 * "Mood · Rest day" (its section, else its entity, else its module). */
export function metricNames(metrics: MetricInfo[]): Map<string, string> {
  const byLabel = new Map<string, MetricInfo[]>();
  for (const m of metrics) byLabel.set(m.label, [...(byLabel.get(m.label) ?? []), m]);
  const names = new Map<string, string>();
  const entity = (m: MetricInfo) =>
    m.entity.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase());
  for (const [label, same] of byLabel) {
    if (same.length === 1) {
      for (const m of same) names.set(m.id, label);
      continue;
    }
    const ways = [
      (m: MetricInfo) => m.section ?? entity(m),
      entity,
      (m: MetricInfo) => `${m.module} · ${entity(m)}`,
      (m: MetricInfo) => m.id,
    ];
    const way =
      ways.find((w) => new Set(same.map(w)).size === same.length) ?? ((m: MetricInfo) => m.id);
    for (const m of same) names.set(m.id, `${label} · ${way(m)}`);
  }
  return names;
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

const BAND_COLOURS: Record<string, string> = {
  LOW: "rgba(250, 82, 82, 0.12)",
  WATCH: "rgba(250, 176, 5, 0.12)",
  GOOD: "rgba(64, 192, 87, 0.12)",
};

export function exploreOption(
  result: QueryResult,
  metrics: MetricInfo[],
  chart: ChartKind,
  names: Map<string, string> = metricNames(metrics),
): EChartsCoreOption {
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const known = result.series.map((s) => byId.get(s.metric)).filter((m) => m !== undefined);
  const units = [...new Set(known.map(unitOf))];
  const labels = result.points.map(pointLabel);
  const lines = result.series.flatMap((series, i) => {
    const metric = byId.get(series.metric);
    const name = names.get(series.metric) ?? series.metric;
    const axis = metric ? units.indexOf(unitOf(metric)) : 0;
    const colour = PALETTE[i % PALETTE.length];
    const main = {
      type: chart === "bars" ? "bar" : "line",
      id: series.metric,
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
        id: `${series.metric} rolling`,
        name: `${name} (rolling mean)`,
        yAxisIndex: axis,
        data: series.rolling,
        connectNulls: true,
        symbol: "none", // a plain thick line, in the legend too (THICK_LINE_ICON)
        itemStyle: { color: colour },
        lineStyle: { width: 3 },
      },
    ];
  });
  // a line's status bands (the class scores' LOW/WATCH/GOOD), when its axis has one set of them
  // (every line on that axis has the same bands: a rest-day mood gets no score's bands)
  const banded = result.series.filter((s) => s.bands);
  const first = banded[0];
  const bandAxis = first ? units.indexOf(unitOf(byId.get(first.metric) as MetricInfo)) : -1;
  const onAxis = result.series.filter((s) => {
    const m = byId.get(s.metric);
    return m !== undefined && units.indexOf(unitOf(m)) === bandAxis;
  });
  const sameBands =
    onAxis.every((s) => s.bands) && new Set(onAxis.map((s) => JSON.stringify(s.bands))).size === 1;
  const bandSeries =
    chart === "line" && first?.bands && sameBands && bandAxis >= 0
      ? [
          {
            type: "line",
            id: "bands",
            name: "bands",
            yAxisIndex: bandAxis,
            data: labels.map(() => null),
            silent: true,
            markArea: {
              silent: true,
              data: first.bands.map((band) => [
                {
                  name: band.label,
                  yAxis: band.from ?? byId.get(first.metric)?.scale?.[0] ?? 0,
                  itemStyle: { color: BAND_COLOURS[band.label] ?? "rgba(134, 142, 150, 0.1)" },
                  label: { position: "insideRight", opacity: 0.6 },
                },
                { yAxis: band.to ?? unitScaleTop(byId.get(first.metric)) },
              ]),
            },
          },
        ]
      : [];
  return {
    tooltip: {
      trigger: "axis",
      formatter: (
        params: { dataIndex: number; seriesId: string; seriesName: string; value: number | null }[],
      ) => {
        const i = params[0]?.dataIndex ?? 0;
        const rows = params
          .filter((p) => p.seriesId !== "bands")
          .map((p) => {
            const series = result.series.find((s) => s.metric === p.seriesId); // by id, not name
            const n = series ? ` (n = ${String(series.n[i] ?? 0)})` : "";
            return `${p.seriesName}: ${decimal(p.value)}${n}`;
          });
        return [labels[i] ?? "", ...rows].join("<br/>");
      },
    },
    legend: {
      top: 0,
      data: lines.map((l) =>
        l.id.endsWith(" rolling") ? { name: l.name, icon: THICK_LINE_ICON } : l.name,
      ),
    },
    grid: { left: 56, right: units.length > 1 ? 56 : 24, top: 48, bottom: 64 },
    xAxis: { type: "category", data: labels, boundaryGap: chart === "bars" },
    yAxis: units.map((unit, i) => {
      const metric = known.find((m) => unitOf(m) === unit);
      const banded = i === bandAxis && bandSeries.length > 0;
      return {
        type: "value",
        name: metric ? axisName(metric, names) : unit,
        // a banded axis shows the whole scale, so the bands keep their place
        ...(banded ? { min: metric?.scale?.[0] ?? 0, max: unitScaleTop(metric) } : {}),
        scale: chart === "line" && !banded,
        splitLine: { show: i === 0 },
      };
    }),
    dataZoom: [{ type: "slider" }, { type: "inside" }],
    series: [...bandSeries, ...lines],
  };
}

/** The top of a metric's scale (10 for a 1–10 score), for the bands' last range. */
function unitScaleTop(metric: MetricInfo | undefined): number {
  return metric?.scale?.[1] ?? 10;
}
