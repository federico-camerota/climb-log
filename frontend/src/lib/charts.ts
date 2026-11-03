// SPDX-License-Identifier: GPL-3.0-or-later
// ECharts options of the widget library v1 (#98, D-091): bars, weekbars, stacked, box_by and
// scatter. The backend computes every number; these only lay them out. Every chart says n.
import type { EChartsCoreOption } from "echarts/core";

import type {
  BarsData,
  BodyHeatmapData,
  BoxByData,
  PrePostData,
  ScatterData,
  StackedData,
  TrainingLoadData,
  WeekbarsData,
} from "../api/client";

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

/** "05/10" for 2026-10-05. */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day ?? ""}/${month ?? ""}`;
}

// The ACWR zones' colours: under the low limit, the usual range, high, very high.
const ZONE_COLOURS = [
  "rgba(134, 142, 150, 0.10)",
  "rgba(64, 192, 87, 0.10)",
  "rgba(250, 176, 5, 0.12)",
  "rgba(250, 82, 82, 0.12)",
];

/** Weekly load (stacked with the other sources) on the left axis, the ACWR at each week's end
 * on the right one, with its zones behind it. */
export function loadOption(data: TrainingLoadData): EChartsCoreOption {
  const weeks = data.weeks.map((w) => w.label);
  const [low = 0.8, high = 1.3, top = 1.5] = data.zones;
  const ratios = data.weeks.map((w) => w.acwr).filter((v): v is number => v !== null);
  const ceiling = Math.max(2, ...ratios.map((r) => Math.ceil(r * 2) / 2));
  const bounds = [0, low, high, top, ceiling];
  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 56, right: 48, top: 48, bottom: 64 },
    xAxis: { type: "category", data: weeks },
    yAxis: [
      { type: "value", name: "Load" },
      { type: "value", name: "ACWR", min: 0, max: ceiling, splitLine: { show: false } },
    ],
    series: [
      {
        type: "bar",
        name: "Climbing journal",
        data: data.weeks.map((w) => w.load),
        itemStyle: { color: PALETTE[0] },
      },
      {
        type: "line",
        name: "ACWR",
        yAxisIndex: 1,
        data: data.weeks.map((w) => w.acwr),
        connectNulls: false,
        itemStyle: { color: "#495057" },
        markArea: {
          silent: true,
          data: ZONE_COLOURS.map((colour, i) => [
            { yAxis: bounds[i], itemStyle: { color: colour } },
            { yAxis: bounds[i + 1] },
          ]),
        },
      },
    ],
    ...zoom(weeks.length, data.shown),
  };
}

/** The other sources' weekly loads (e.g. finger training, sets × effort), stacked on a chart
 * of their own: their units differ from the journal's (D-092). */
export function othersOption(data: TrainingLoadData): EChartsCoreOption {
  const weeks = data.weeks.map((w) => w.label);
  return {
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 56, right: 48, top: 40, bottom: 64 },
    xAxis: { type: "category", data: weeks },
    yAxis: { type: "value" },
    series: data.others.map((label, i) => ({
      type: "bar",
      stack: "others",
      name: label,
      data: data.weeks.map((w) => w.others[i] ?? 0),
      itemStyle: { color: PALETTE[(i + 2) % PALETTE.length] },
    })),
    ...zoom(weeks.length, data.shown),
  };
}

/** Where a ratio lies among the zones. */
export function zoneOf(ratio: number, zones: number[]): string {
  const [low = 0.8, high = 1.3, top = 1.5] = zones;
  if (ratio < low) return "below the usual range";
  if (ratio <= high) return "in the usual range";
  if (ratio <= top) return "high";
  return "very high";
}

type PairStats = PrePostData["pairs"][number]["all"];

/** The stats of each pair for a group (-1: all records). */
export function pairStats(data: PrePostData, group: number): PairStats[] {
  return data.pairs.map((p) => (group < 0 ? p.all : (p.groups[group] ?? p.all)));
}

/** A change's colour: green up and red down on a higher-is-better scale (mood); neutral on a
 * lower-is-better one (soreness), which is expected to rise after a session (D-093). */
export function changeTone(change: number | null, lowerBetter: boolean | null): string {
  if (change === null || change === 0 || lowerBetter === null) return "dimmed";
  if (lowerBetter) return "inherit";
  return change > 0 ? "green" : "red";
}

/** A dumbbell per pair: the mean before and after, joined. */
export function prePostOption(data: PrePostData, group: number): EChartsCoreOption {
  const stats = pairStats(data, group);
  const labels = data.pairs.map((p) => p.label);
  const shown = (side: "pre" | "post") =>
    stats.map((x, i) => (x[side] === null ? null : [x[side], labels[i]]));
  return {
    tooltip: { trigger: "item" },
    legend: { top: 0, data: ["Before", "After"] },
    grid: { left: 110, right: 24, top: 40, bottom: 32 },
    xAxis: { type: "value", scale: true },
    yAxis: { type: "category", data: labels, inverse: true },
    series: [
      ...stats.map((s, i) => ({
        type: "line",
        name: `${labels[i] ?? ""} change`,
        data:
          s.pre === null || s.post === null
            ? []
            : [
                [s.pre, labels[i]],
                [s.post, labels[i]],
              ],
        showSymbol: false,
        silent: true,
        lineStyle: { color: "#adb5bd", width: 3 },
        tooltip: { show: false },
      })),
      {
        type: "scatter",
        name: "Before",
        data: shown("pre"),
        symbolSize: 11,
        itemStyle: { color: "#adb5bd" },
      },
      {
        type: "scatter",
        name: "After",
        data: shown("post"),
        symbolSize: 11,
        itemStyle: { color: PALETTE[0] },
      },
    ],
  };
}

/** Weeks across, the template's fields (body parts) down; colour by the week's mean, red for
 * the bad end of the scale. */
export function bodyOption(data: BodyHeatmapData, source: number): EChartsCoreOption {
  const values = data.sources[source]?.values ?? [];
  const cells = values.flatMap((row, part) =>
    row.flatMap((v, week) => (v === null ? [] : [[week, part, v]])),
  );
  const [min, max] = data.scale ?? [0, 10];
  const ramp = ["#d3f9d8", "#ffec99", "#ffa8a8", "#e03131"];
  return {
    tooltip: {
      formatter: (p: { value: [number, number, number] }) =>
        `${data.weeks[p.value[0]] ?? ""} · ${data.parts[p.value[1]] ?? ""}: ${decimal(p.value[2])}`,
    },
    grid: { left: 110, right: 24, top: 16, bottom: 72 },
    xAxis: { type: "category", data: data.weeks, splitArea: { show: true } },
    yAxis: { type: "category", data: data.parts, inverse: true, splitArea: { show: true } },
    visualMap: {
      min,
      max,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: { color: data.lower_better === false ? [...ramp].reverse() : ramp },
      text: [decimal(max), decimal(min)], // the scale's ends, at the colour bar
    },
    series: [
      {
        type: "heatmap",
        data: cells,
        label: { show: true, formatter: (p: { value: number[] }) => decimal(p.value[2]) },
      },
    ],
    ...zoom(data.weeks.length, data.shown),
  };
}
