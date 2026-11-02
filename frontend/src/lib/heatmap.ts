// SPDX-License-Identifier: GPL-3.0-or-later
// The `heatmap_calendar` widget's ECharts option (D-084): one square per day from the first
// record's month, coloured by the worst status of the day's sessions (rest days in lighter
// colours), a letter per day (e.g. G gym, O outdoor, R rest), on a grid with month lines.
import type { EChartsCoreOption } from "echarts/core";

import type { HeatmapData } from "../api/client";
import { formatDateTime } from "./format";

type Day = HeatmapData["days"][number];

// A day's colour: its sessions' worst status; a day with only a rest day, the rest day's
// status in a lighter shade. The legend shows them in this order.
export const PIECES = [
  { key: "LOW", label: "LOW", color: "#fa5252" },
  { key: "WATCH", label: "WATCH", color: "#fab005" },
  { key: "GOOD", label: "GOOD", color: "#40c057" },
  { key: "none", label: "No status", color: "#adb5bd" },
  { key: "rest LOW", label: "Rest day LOW", color: "#ffc9c9" },
  { key: "rest WATCH", label: "Rest day WATCH", color: "#ffec99" },
  { key: "rest GOOD", label: "Rest day GOOD", color: "#b2f2bb" },
  { key: "rest none", label: "Rest day, no status", color: "#d0ebff" },
] as const;
const COLOURS = new Map<string, string>(PIECES.map((p) => [p.key, p.color]));
const LEVELS = new Set(["LOW", "WATCH", "GOOD"]);
const CELL = 22; // px: room for two letters

function level(value: unknown): string {
  return typeof value === "string" && LEVELS.has(value) ? value : "none";
}

/** A day's piece: by its sessions' status; a day with only a rest day, by the rest day's. */
export function dayKey(day: Day): string {
  return day.records > 0 ? level(day.status) : `rest ${level(day.extra)}`;
}

/** The weeks (columns) from start to end, weeks from Monday. */
export function weeks(start: string, end: string): number {
  const from = new Date(`${start}T00:00:00Z`);
  const to = new Date(`${end}T00:00:00Z`);
  const monday = (d: Date) => d.getTime() - ((d.getUTCDay() + 6) % 7) * 86_400_000;
  return Math.round((monday(to) - monday(from)) / (7 * 86_400_000)) + 1;
}

export const CALENDAR_HEIGHT = 7 * CELL + 24 + 8; // the rows, the month names, a margin

/** The option; `background` is the card's colour, drawn between the squares as grid lines. */
export function heatmapOption(
  data: HeatmapData,
  dark = false,
  background = dark ? "#242424" : "#ffffff",
): EChartsCoreOption {
  const byDate = new Map(data.days.map((d) => [d.date, d]));
  const empty = dark ? "#2c2e33" : "#f1f3f5";
  const gap = background;
  const columns = weeks(data.start, data.end);
  return {
    tooltip: {
      formatter: (params: { value: [string, number] }) => {
        const day = byDate.get(params.value[0]);
        const parts = [formatDateTime(params.value[0])];
        if (day === undefined) return parts.join("");
        if (day.records > 0) {
          const status = typeof day.status === "string" ? day.status : "no status";
          parts.push(`${String(day.records)} session${day.records > 1 ? "s" : ""}: ${status}`);
        }
        if (day.extra !== null || day.records === 0) {
          parts.push(`Rest day: ${typeof day.extra === "string" ? day.extra : "logged"}`);
        }
        const mark = day.mark;
        if (mark !== null) {
          const named = data.marks.filter((m) => mark.includes(m.letter));
          parts.push(named.map((m) => `${m.letter} ${m.label}`).join(", ") || mark);
        }
        return parts.join("<br>");
      },
    },
    calendar: {
      range: [data.start, data.end],
      orient: "horizontal",
      // square cells: a fixed width while the weeks fit, else as wide as the card allows
      cellSize: [columns <= 40 ? CELL : "auto", CELL],
      ...(columns <= 40 ? { width: columns * CELL } : { right: 16 }),
      top: 24,
      left: 32,
      bottom: 8,
      dayLabel: { firstDay: 1, nameMap: ["S", "M", "T", "W", "T", "F", "S"], fontSize: 10 },
      monthLabel: { fontSize: 11 },
      yearLabel: { show: false },
      splitLine: { show: true, lineStyle: { color: dark ? "#5c5f66" : "#868e96", width: 1 } },
      itemStyle: { color: empty, borderWidth: 2, borderColor: gap },
    },
    series: [
      {
        type: "heatmap",
        coordinateSystem: "calendar",
        // a heatmap's value must be a number: the piece's index; the letters go alongside
        data: data.days.map((d) => ({
          value: [d.date, PIECES.findIndex((p) => p.key === dayKey(d))],
          mark: d.mark ?? "",
          itemStyle: { color: COLOURS.get(dayKey(d)), borderWidth: 2, borderColor: gap },
        })),
        label: {
          show: true,
          color: "#212529",
          fontSize: 10,
          fontWeight: "bold",
          formatter: (params: { data: { mark: string } }) => params.data.mark,
        },
      },
    ],
  };
}
