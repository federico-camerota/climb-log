// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { HeatmapData } from "../api/client";
import { monthName } from "./format";
import { dayKey, heatmapOption, weeks } from "./heatmap";

const DATA: HeatmapData = {
  widget: "heatmap_calendar",
  label: "Training calendar",
  entity: "session",
  start: "2026-10-01",
  end: "2026-10-31",
  extra: "rest_day",
  marks: [
    { letter: "G", label: "Indoor" },
    { letter: "R", label: "rest day" },
  ],
  days: [
    { date: "2026-10-05", status: "LOW", records: 2, extra: null, mark: "GO" },
    { date: "2026-10-06", status: null, records: 1, extra: null, mark: null },
    { date: "2026-10-07", status: null, records: 0, extra: "GOOD", mark: "R" },
    { date: "2026-10-08", status: "GOOD", records: 1, extra: "WATCH", mark: "G" },
    { date: "2026-10-09", status: null, records: 0, extra: null, mark: "R" },
  ],
};

type Option = {
  calendar: {
    range: string[];
    dayLabel: { firstDay: number };
    cellSize: (number | string)[];
    splitLine: { show: boolean };
    itemStyle: { color: string };
  };
  series: {
    data: { value: [string, number]; mark: string; itemStyle: { color: string } }[];
  }[];
};

describe("the calendar", () => {
  it("colours a day by its sessions' status, else by its rest day's, lighter", () => {
    expect(DATA.days.map(dayKey)).toEqual(["LOW", "none", "rest GOOD", "GOOD", "rest none"]);
    const option = heatmapOption(DATA) as Option;
    const colours = option.series[0]?.data.map((d) => d.itemStyle.color);
    expect(colours).toEqual(["#fa5252", "#adb5bd", "#b2f2bb", "#40c057", "#d0ebff"]);
  });

  it("writes the day's letters on its square", () => {
    const option = heatmapOption(DATA) as Option;
    expect(option.series[0]?.data.map((d) => d.mark)).toEqual(["GO", "", "R", "G", "R"]);
    expect(option.series[0]?.data.map((d) => d.value[1])).toEqual([0, 3, 6, 2, 7]); // numbers
  });

  it("draws a grid: empty days filled, month lines, square cells while they fit", () => {
    const option = heatmapOption(DATA) as Option;
    expect(option.calendar.range).toEqual(["2026-10-01", "2026-10-31"]);
    expect(option.calendar.dayLabel.firstDay).toBe(1);
    expect(option.calendar.splitLine.show).toBe(true);
    expect(option.calendar.itemStyle.color).toBe("#f1f3f5");
    expect(option.calendar.cellSize).toEqual([22, 22]);
    const year = heatmapOption({ ...DATA, start: "2025-11-01" }) as Option;
    expect(year.calendar.cellSize).toEqual(["auto", 22]);
  });

  it("counts the weeks from Monday", () => {
    expect(weeks("2026-10-01", "2026-10-31")).toBe(5); // Thu 1 to Sat 31
    expect(weeks("2026-11-02", "2026-11-08")).toBe(1);
    expect(weeks("2025-11-01", "2026-10-31")).toBe(53);
  });

  it("names a month as the legacy table", () => {
    expect([monthName("2026-10"), monthName("2027-01")]).toEqual(["Oct 26", "Jan 27"]);
  });
});
