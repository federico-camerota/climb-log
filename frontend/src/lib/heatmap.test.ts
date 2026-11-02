// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { HeatmapData } from "../api/client";
import { monthName } from "./format";
import { dayCode, heatmapOption } from "./heatmap";

const DATA: HeatmapData = {
  widget: "heatmap_calendar",
  label: "Sessions and rest days",
  start: "2025-11-01",
  end: "2026-10-31",
  extra: "rest_day",
  days: [
    { date: "2026-10-05", status: "LOW", records: 2, extra: null },
    { date: "2026-10-06", status: null, records: 1, extra: null },
    { date: "2026-10-07", status: null, records: 0, extra: "GOOD" },
    { date: "2026-10-08", status: "GOOD", records: 1, extra: "WATCH" },
  ],
};

describe("the calendar", () => {
  it("colours a day by its sessions' status, else as a rest day", () => {
    expect(DATA.days.map(dayCode)).toEqual([1, 5, 4, 3]);
  });

  it("spans the months asked, weeks from Monday", () => {
    const option = heatmapOption(DATA) as {
      calendar: { range: string[]; dayLabel: { firstDay: number } };
      series: { data: [string, number][] }[];
    };
    expect(option.calendar.range).toEqual(["2025-11-01", "2026-10-31"]);
    expect(option.calendar.dayLabel.firstDay).toBe(1);
    expect(option.series[0]?.data[0]).toEqual(["2026-10-05", 1]);
  });

  it("names a month as the legacy table", () => {
    expect([monthName("2026-10"), monthName("2027-01")]).toEqual(["Oct 26", "Jan 27"]);
  });
});
