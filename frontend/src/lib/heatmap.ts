// SPDX-License-Identifier: GPL-3.0-or-later
// The `heatmap_calendar` widget's ECharts option (D-084): one cell per day of the months shown,
// coloured by the worst status of the day's sessions, rest days marked (weeks from Monday).
import type { EChartsCoreOption } from "echarts/core";

import type { HeatmapData } from "../api/client";
import { formatDateTime } from "./format";

// A day's colour: its sessions' worst status, else a rest day, else a session without status.
export const PIECES = [
  { value: 1, label: "LOW", color: "#fa5252" },
  { value: 2, label: "WATCH", color: "#fab005" },
  { value: 3, label: "GOOD", color: "#40c057" },
  { value: 4, label: "Rest day", color: "#74c0fc" },
  { value: 5, label: "No status", color: "#adb5bd" },
];
const CODES: Record<string, number> = { LOW: 1, WATCH: 2, GOOD: 3 };

/** A day's piece: by its sessions' status; a day with only a rest day is a rest day. */
export function dayCode(day: HeatmapData["days"][number]): number {
  if (day.records > 0) return typeof day.status === "string" ? (CODES[day.status] ?? 5) : 5;
  return 4;
}

export function heatmapOption(data: HeatmapData): EChartsCoreOption {
  const byDate = new Map(data.days.map((d) => [d.date, d]));
  return {
    tooltip: {
      formatter: (params: { value: [string, number] }) => {
        const day = byDate.get(params.value[0]);
        const parts = [formatDateTime(params.value[0])];
        if (day !== undefined && day.records > 0) {
          const status = typeof day.status === "string" ? day.status : "no status";
          parts.push(`${String(day.records)} session${day.records > 1 ? "s" : ""}: ${status}`);
        }
        const rest = day?.extra;
        if (rest != null) parts.push(`Rest day: ${typeof rest === "string" ? rest : "logged"}`);
        return parts.join("<br>");
      },
    },
    visualMap: {
      type: "piecewise",
      orient: "horizontal",
      left: "center",
      bottom: 0,
      pieces: PIECES,
    },
    calendar: {
      range: [data.start, data.end],
      cellSize: ["auto", 14],
      top: 24,
      left: 32,
      right: 16,
      bottom: 48,
      dayLabel: { firstDay: 1, nameMap: ["S", "M", "T", "W", "T", "F", "S"] },
      yearLabel: { show: false },
      splitLine: { show: false },
      itemStyle: { borderWidth: 2, borderColor: "transparent" },
    },
    series: [
      {
        type: "heatmap",
        coordinateSystem: "calendar",
        data: data.days.map((d) => [d.date, dayCode(d)]),
      },
    ],
  };
}
