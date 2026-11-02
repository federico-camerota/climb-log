// SPDX-License-Identifier: GPL-3.0-or-later
// The `line` widget's ECharts option (D-083): one line per series over the records (one point
// per session, labelled dd/mm), the status bands behind them, optionally the rolling mean, and
// a zoom slider opened on the range picked.
import dayjs from "dayjs";
import type { EChartsCoreOption } from "echarts/core";

import type { LineData } from "../api/client";

export type Range = "last" | "3m" | "12m" | "all";

export const RANGES: { value: Range; label: string }[] = [
  { value: "last", label: "Last sessions" }, // the widget's `last` (12 in the journal)
  { value: "3m", label: "3 months" },
  { value: "12m", label: "12 months" },
  { value: "all", label: "All" },
];

// One colour per series, the same for its rolling mean.
const PALETTE = ["#228be6", "#40c057", "#fd7e14", "#be4bdb", "#15aabf", "#e64980"];
const BAND_COLOURS: Record<string, string> = {
  LOW: "rgba(250, 82, 82, 0.12)",
  RED: "rgba(250, 82, 82, 0.12)",
  WATCH: "rgba(250, 176, 5, 0.12)",
  YELLOW: "rgba(250, 176, 5, 0.12)",
  GOOD: "rgba(64, 192, 87, 0.10)",
  GREEN: "rgba(64, 192, 87, 0.10)",
};

/** "28/10", and "28/10 (2)" for a day's second session. */
export function pointLabel(point: LineData["points"][number]): string {
  const [, month, day] = point.date.split("-");
  const numbers = Object.values(point.key).filter((v) => typeof v === "number" && v > 1);
  const suffix = numbers.length > 0 ? ` (${numbers.map(String).join(", ")})` : "";
  return `${day ?? ""}/${month ?? ""}${suffix}`;
}

/** The index of the first point shown for a range (the last one is always the latest). */
export function firstShown(data: LineData, range: Range, today: string): number {
  const n = data.points.length;
  if (range === "last") return Math.max(0, n - data.last);
  if (range === "all") return 0;
  const from = dayjs(today)
    .subtract(range === "3m" ? 3 : 12, "month")
    .format("YYYY-MM-DD");
  const found = data.points.findIndex((p) => p.date >= from);
  return found === -1 ? n : found;
}

export function lineOption(
  data: LineData,
  range: Range,
  rolling: boolean,
  today: string,
): EChartsCoreOption {
  const labels = data.points.map(pointLabel);
  const lines = data.series.flatMap((series, i) => {
    const colour = PALETTE[i % PALETTE.length];
    const raw = {
      type: "line",
      name: series.label,
      data: series.values,
      connectNulls: true,
      showSymbol: true,
      symbolSize: 5,
      itemStyle: { color: colour },
      lineStyle: { color: colour, width: 2, opacity: rolling ? 0.3 : 1 },
    };
    if (!rolling || series.rolling == null) return [raw];
    return [
      raw,
      {
        type: "line",
        name: `${series.label} (mean of ${String(data.rolling ?? "")})`,
        data: series.rolling,
        connectNulls: true,
        showSymbol: false,
        itemStyle: { color: colour },
        lineStyle: { color: colour, width: 3 },
      },
    ];
  });
  // scores (0–10) on a fixed axis, so the bands keep their place; anything else fits its values
  const values = data.series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const scores = values.every((v) => v >= 0 && v <= 10);
  const bottom = scores ? 0 : Math.min(...values, ...bounds(data));
  const top = scores ? 10 : Math.max(...values, ...bounds(data));
  const bands = {
    type: "line",
    name: "bands",
    data: labels.map(() => null),
    silent: true,
    markArea: {
      silent: true,
      data: data.bands.map((band) => [
        {
          name: band.label,
          yAxis: band.from ?? bottom,
          itemStyle: { color: BAND_COLOURS[band.label] ?? "rgba(134, 142, 150, 0.1)" },
          label: { position: "insideRight", opacity: 0.6 },
        },
        { yAxis: band.to ?? top },
      ]),
    },
  };
  const start = firstShown(data, range, today);
  return {
    tooltip: { trigger: "axis" },
    legend: { data: lines.map((l) => l.name), top: 0 },
    grid: { left: 40, right: 24, top: 48, bottom: 64 },
    xAxis: { type: "category", data: labels, boundaryGap: false },
    yAxis: scores ? { type: "value", min: 0, max: 10 } : { type: "value", scale: true },
    dataZoom: [
      {
        type: "slider",
        startValue: Math.min(start, Math.max(0, labels.length - 1)),
        endValue: Math.max(0, labels.length - 1),
      },
      { type: "inside" },
    ],
    series: [bands, ...lines],
  };
}

/** The bands' finite bounds (a band without a lower or upper bound runs to the axis's end). */
function bounds(data: LineData): number[] {
  return data.bands.flatMap((b) => [b.from, b.to]).filter((v): v is number => v !== null);
}
