// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { LineData } from "../api/client";
import { THICK_LINE_ICON } from "./charts";
import { firstShown, lineOption, pointLabel } from "./lineChart";

function line(dates: string[], values: (number | null)[], last = 12): LineData {
  return {
    widget: "line",
    label: "Scores by class",
    points: dates.map((date, i) => ({ date, key: { session_no: i === 1 ? 2 : 1 } })),
    series: [{ metric: "session.wb_score", label: "Wellbeing", values, rolling: values }],
    bands: [
      { label: "LOW", from: null, to: 4 },
      { label: "WATCH", from: 4, to: 6 },
      { label: "GOOD", from: 6, to: null },
    ],
    rolling: 4,
    last,
  };
}

const DATES = ["2025-09-01", "2025-09-01", "2026-06-15", "2026-09-10", "2026-10-30"];

describe("the line chart", () => {
  it("labels a point by its day, and a day's second session", () => {
    const data = line(DATES, [1, 2, 3, 4, 5]);
    expect(data.points.map(pointLabel)).toEqual(["01/09", "01/09 (2)", "15/06", "10/09", "30/10"]);
  });

  it("opens on the last sessions, or a range of months", () => {
    const data = line(DATES, [1, 2, 3, 4, 5], 2);
    expect(firstShown(data, "last", "2026-10-31")).toBe(3);
    expect(firstShown(data, "3m", "2026-10-31")).toBe(3); // from 31/07
    expect(firstShown(data, "12m", "2026-10-31")).toBe(2);
    expect(firstShown(data, "all", "2026-10-31")).toBe(0);
  });

  it("draws the bands behind the lines and the rolling mean on request", () => {
    const data = line(DATES, [1, 2, null, 4, 5]);
    const plain = lineOption(data, "all", false, "2026-10-31") as {
      series: { name: string; markArea?: { data: { yAxis: unknown; name?: string }[][] } }[];
      yAxis: { min?: number; max?: number };
    };
    expect(plain.series.map((s) => s.name)).toEqual(["bands", "Wellbeing"]);
    expect(
      plain.series[0]?.markArea?.data.map((b) => [b[0]?.name, b[0]?.yAxis, b[1]?.yAxis]),
    ).toEqual([
      ["LOW", 0, 4],
      ["WATCH", 4, 6],
      ["GOOD", 6, 10],
    ]);
    expect([plain.yAxis.min, plain.yAxis.max]).toEqual([0, 10]); // scores
    const rolling = lineOption(data, "all", true, "2026-10-31") as {
      series: { name: string; symbol?: string }[];
      legend: { data: unknown[] };
    };
    expect(rolling.series.map((s) => s.name)).toEqual([
      "bands",
      "Wellbeing",
      "Wellbeing (mean of 4)",
    ]);
    expect(rolling.series[2]?.symbol).toBe("none");
    expect(rolling.legend.data[1]).toEqual({
      name: "Wellbeing (mean of 4)",
      icon: THICK_LINE_ICON,
    });
  });

  it("fits the axis to values that aren't scores", () => {
    const option = lineOption(line(DATES, [20, 35, 40, 42, 45]), "all", false, "2026-10-31") as {
      yAxis: { scale?: boolean; max?: number };
    };
    expect(option.yAxis).toEqual({ type: "value", scale: true });
  });
});
