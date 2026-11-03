// SPDX-License-Identifier: GPL-3.0-or-later
// ECharts options of the widget library v1 (#98, D-091): bars, weekbars, stacked, box_by and
// scatter. The backend computes every number; these only lay them out. Every chart says n.
import type { EChartsCoreOption } from "echarts/core";

import type { BarsData, BoxByData, ScatterData, StackedData, WeekbarsData } from "../api/client";

export const PALETTE = ["#228be6", "#40c057", "#fd7e14", "#be4bdb", "#15aabf", "#e64980"];
// A status stack keeps its status colour (the journal's levels and the programs' traffic lights).
const STATUS_HEX: Record<string, string> = {
  GOOD: "#40c057",
  GREEN: "#40c057",
  WATCH: "#fab005",
  YELLOW: "#fab005",
  LOW: "#fa5252",
  RED: "#fa5252",
};

/** "7,5": numbers as the rest of the app shows them (decimal comma, one decimal at most). */
export function decimal(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const rounded = Math.round(value * 10) / 10;
  return String(rounded).replace(".", ",");
}

/** A zoom slider opened on the last `shown` categories, when there are more. */
function zoom(count: number, shown: number): Record<string, unknown> {
  if (count <= shown) return {};
  return {
    dataZoom: [
      { type: "slider", startValue: count - shown, endValue: count - 1 },
      { type: "inside" },
    ],
  };
}

export function barsOption(data: BarsData): EChartsCoreOption {
  const periods = data.categories.some((c) => /^\d{4}-/.test(c));
  return {
    tooltip: {
      trigger: "axis",
      formatter: (params: { dataIndex: number }[]) => {
        const i = params[0]?.dataIndex ?? 0;
        const n = data.n[i] ?? 0;
        return `${data.categories[i] ?? ""}<br/>${data.metric} (${data.agg}): ${decimal(data.values[i])}<br/>n = ${String(n)}`;
      },
    },
    grid: { left: 48, right: 24, top: 24, bottom: periods ? 64 : 32 },
    xAxis: { type: "category", data: data.categories },
    yAxis: { type: "value" }, // bars start at zero: a cut axis exaggerates differences
    series: [
      { type: "bar", name: data.metric, data: data.values, itemStyle: { color: PALETTE[0] } },
    ],
    ...(periods ? zoom(data.categories.length, data.last) : {}),
  };
}

export function weekbarsOption(data: WeekbarsData): EChartsCoreOption {
  const single = data.stacks.length === 1 && data.stacks[0]?.label === "";
  return {
    tooltip: { trigger: "axis" },
    legend: single ? undefined : { top: 0 },
    grid: { left: 48, right: 24, top: single ? 24 : 48, bottom: 64 },
    xAxis: { type: "category", data: data.weeks },
    yAxis: { type: "value" },
    series: data.stacks.map((stack, i) => ({
      type: "bar",
      stack: "week",
      name: stack.label === "" ? "Total" : stack.label,
      data: stack.values,
      itemStyle: { color: STATUS_HEX[stack.label] ?? PALETTE[i % PALETTE.length] },
    })),
    ...zoom(data.weeks.length, data.shown),
  };
}

export function stackedOption(data: StackedData): EChartsCoreOption {
  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 48, right: 24, top: 48, bottom: 64 },
    xAxis: { type: "category", data: data.categories },
    yAxis: { type: "value" },
    series: data.series.map((series, i) => ({
      type: "bar",
      stack: "all",
      name: series.label,
      data: series.values,
      itemStyle: { color: PALETTE[i % PALETTE.length] },
    })),
    ...zoom(data.categories.length, data.last),
  };
}

/** A box's category label with its n, e.g. "Climbing (n = 8)". */
export function boxLabel(box: BoxByData["boxes"][number]): string {
  return `${box.label} (n = ${String(box.n)})`;
}

export function boxOption(data: BoxByData): EChartsCoreOption {
  const outliers = data.boxes.flatMap((box, i) => box.outliers.map((v) => [i, v]));
  return {
    tooltip: { trigger: "item" },
    grid: { left: 48, right: 24, top: 24, bottom: 40 },
    xAxis: { type: "category", data: data.boxes.map(boxLabel), name: data.by },
    yAxis: { type: "value", scale: true, name: data.metric },
    series: [
      {
        type: "boxplot",
        name: data.metric,
        data: data.boxes.map((b) => [b.low, b.q1, b.median, b.q3, b.high]),
        itemStyle: { color: "rgba(34, 139, 230, 0.15)", borderColor: PALETTE[0] },
      },
      { type: "scatter", name: "Outliers", data: outliers, itemStyle: { color: PALETTE[2] } },
    ],
  };
}

export function scatterOption(data: ScatterData): EChartsCoreOption {
  const groups = [...new Set(data.points.map((p) => p.group ?? ""))];
  const series: Record<string, unknown>[] = groups.map((group, i) => ({
    type: "scatter",
    name: group === "" ? data.y_label : group,
    data: data.points.filter((p) => (p.group ?? "") === group).map((p) => [p.x, p.y, p.date]),
    symbolSize: 9,
    itemStyle: { color: PALETTE[i % PALETTE.length], opacity: 0.8 },
  }));
  if (data.trend) {
    const { slope, intercept, from, to } = data.trend;
    series.push({
      type: "line",
      name: "Trend",
      data: [
        [from, intercept + slope * from],
        [to, intercept + slope * to],
      ],
      showSymbol: false,
      lineStyle: { color: "#868e96", type: "dashed" },
    });
  }
  return {
    tooltip: {
      trigger: "item",
      formatter: (p: { value: [number, number, string?] }) =>
        `${p.value[2] ?? ""}<br/>${data.x_label}: ${decimal(p.value[0])}<br/>${data.y_label}: ${decimal(p.value[1])}`,
    },
    legend: groups.length > 1 ? { top: 0 } : undefined,
    grid: { left: 56, right: 24, top: groups.length > 1 ? 48 : 24, bottom: 48 },
    xAxis: { type: "value", scale: true, name: data.x_label, nameLocation: "middle", nameGap: 28 },
    yAxis: { type: "value", scale: true, name: data.y_label },
    series,
  };
}
