// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type {
  BarsData,
  BodyHeatmapData,
  BoxByData,
  GradesData,
  PrePostData,
  LineData,
  ScatterData,
  TrainingLoadData,
  WeekbarsData,
} from "../api/client";
import {
  barsOption,
  bodyOption,
  boxLabel,
  boxOption,
  changeTone,
  decimal,
  gradesOption,
  loadOption,
  othersOption,
  pairStats,
  prePostOption,
  pyramidOption,
  scatterOption,
  shortDate,
  stackedOption,
  weekbarsOption,
  zoneOf,
} from "./charts";
import { lineOption } from "./lineChart";

// The options are plain objects: read them as such.
type Option = Record<string, unknown> & {
  series: Record<string, unknown>[];
  dataZoom?: Record<string, unknown>[];
};

function bars(categories: string[], last = 12): BarsData {
  return {
    widget: "bars",
    label: null,
    metric: "Session load",
    agg: "sum",
    categories,
    values: categories.map((_, i) => i * 10),
    n: categories.map(() => 1),
    last,
  };
}

describe("the chart options", () => {
  it("shows numbers with a decimal comma", () => {
    expect([decimal(7.25), decimal(8), decimal(null)]).toEqual(["7,3", "8", "–"]);
  });

  it("opens bars over periods on the last ones", () => {
    const weeks = Array.from({ length: 20 }, (_, i) => `2026-W${String(i + 10)}`);
    const option = barsOption(bars(weeks)) as Option;
    expect(option.dataZoom?.[0]).toMatchObject({ startValue: 8, endValue: 19 });
    const tooltip = option.tooltip as { formatter: (p: { dataIndex: number }[]) => string };
    expect(tooltip.formatter([{ dataIndex: 2 }])).toBe(
      "2026-W12<br/>Session load (sum): 20<br/>n = 1",
    );
    // bars per value of a field: no zoom
    expect((barsOption(bars(["Climbing", "Hangboard"], 1)) as Option).dataZoom).toBeUndefined();
  });

  it("stacks weekbars and keeps the status colours", () => {
    const data: WeekbarsData = {
      widget: "weekbars",
      label: null,
      agg: "count_by_value",
      weeks: ["2026-W43", "2026-W44"],
      starts: ["2026-10-19", "2026-10-26"],
      stacks: [
        { label: "GOOD", values: [1, 2] },
        { label: "Other", values: [0, 1] },
      ],
      shown: 12,
    };
    const option = weekbarsOption(data) as Option;
    expect(option.series.map((s) => [s.name, s.stack, s.itemStyle])).toEqual([
      ["GOOD", "week", { color: "#40c057" }],
      ["Other", "week", { color: "#40c057" }],
    ]);
    const single = weekbarsOption({ ...data, stacks: [{ label: "", values: [3, 4] }] }) as Option;
    expect(single.series[0]?.name).toBe("Total");
    expect(single.legend).toBeUndefined();
  });

  it("stacks several metrics", () => {
    const option = stackedOption({
      widget: "stacked",
      label: null,
      agg: "sum",
      categories: ["2026-W44"],
      series: [
        { metric: "a", label: "Climbing", values: [100] },
        { metric: "b", label: "Fingers", values: [20] },
      ],
      last: 12,
    }) as Option;
    expect(option.series.map((s) => [s.name, s.stack, s.data])).toEqual([
      ["Climbing", "all", [100]],
      ["Fingers", "all", [20]],
    ]);
  });

  it("draws boxes with their n and the outliers as points", () => {
    const data: BoxByData = {
      widget: "box_by",
      label: null,
      metric: "Feel score",
      by: "Session type",
      boxes: [
        { label: "Climbing", n: 8, low: 5, q1: 5.75, median: 6.5, q3: 7, high: 8, outliers: [1] },
      ],
    };
    const option = boxOption(data) as Option;
    expect(boxLabel(data.boxes[0] as BoxByData["boxes"][number])).toBe("Climbing (n = 8)");
    expect(option.series[0]?.data).toEqual([[5, 5.75, 6.5, 7, 8]]);
    expect(option.series[1]?.data).toEqual([[0, 1]]);
  });

  it("colours scatter points by group and draws the trend", () => {
    const data: ScatterData = {
      widget: "scatter",
      label: null,
      x_label: "Sleep hours",
      y_label: "Feel score",
      lag: 0,
      points: [
        { x: 6, y: 5, date: "2026-10-01", group: "Indoor" },
        { x: 7, y: 7, date: "2026-10-02", group: "Outdoor" },
        { x: 8, y: 9, date: "2026-10-03", group: "Indoor" },
      ],
      n: 3,
      trend: { slope: 2, intercept: -7, from: 6, to: 8 },
    };
    const option = scatterOption(data) as Option;
    expect(option.series.map((s) => s.name)).toEqual(["Indoor", "Outdoor", "Trend"]);
    expect(option.series[0]?.data).toEqual([
      [6, 5, "2026-10-01"],
      [8, 9, "2026-10-03"],
    ]);
    expect(option.series[2]?.data).toEqual([
      [6, 5],
      [8, 9],
    ]);
    const tooltip = option.tooltip as {
      formatter: (p: { value: [number, number, string] }) => string;
    };
    expect(tooltip.formatter({ value: [7.5, 8, "2026-10-04"] })).toBe(
      "2026-10-04<br/>Sleep hours: 7,5<br/>Feel score: 8",
    );
    const plain = scatterOption({
      ...data,
      points: data.points.slice(0, 1),
      trend: null,
    }) as Option;
    expect(plain.series.map((s) => s.name)).toEqual(["Indoor"]);
    expect(plain.legend).toBeUndefined();
  });

  it("draws a line over another x than the date", () => {
    const data: LineData = {
      widget: "line",
      label: null,
      points: [],
      series: [{ metric: "session.feel_score", label: "Feel", values: [5.5, 8], rolling: null }],
      bands: [],
      rolling: null,
      last: 12,
      x: [1, 2],
      x_label: "Days since prev",
    };
    const option = lineOption(data, "last", false, "2026-10-30") as Option;
    expect(option.xAxis).toMatchObject({ type: "value", name: "Days since prev" });
    expect(option.series[0]?.data).toEqual([
      [1, 5.5],
      [2, 8],
    ]);
  });

  it("draws the journal load with the ratio on its own axis, other sources apart", () => {
    const data: TrainingLoadData = {
      widget: "training_load",
      label: null,
      others: ["Fingers"],
      absent: [],
      zones: [0.8, 1.3, 1.5],
      acute: 7,
      chronic: 28,
      baseline_from: "2026-10-01",
      acwr_today: 2.4,
      weeks: [
        {
          label: "2026-W44",
          start: "2026-10-26",
          load: 900,
          sessions: 3,
          days: 2,
          without_load: 0,
          rest_days: 1,
          others: [40],
          others_without: [1],
          acwr: 2.4,
          monotony: null,
          strain: null,
        },
      ],
      shown: 12,
      longest_streak: null,
      current_streak: 0,
    };
    const option = loadOption(data) as Option;
    expect(option.series.map((s) => [s.name, s.yAxisIndex])).toEqual([
      ["Climbing journal", undefined],
      ["ACWR", 1],
    ]);
    const others = othersOption(data) as Option; // other units: a chart of their own
    expect(others.series.map((s) => [s.name, s.stack, s.data])).toEqual([
      ["Fingers", "others", [40]],
    ]);
    const axes = option.yAxis as Record<string, unknown>[];
    expect(axes[1]).toMatchObject({ min: 0, max: 2.5 }); // room for 2.4
    const zones = (option.series[1]?.markArea as { data: { yAxis: number }[][] }).data;
    expect(zones.map(([from, to]) => [from?.yAxis, to?.yAxis])).toEqual([
      [0, 0.8],
      [0.8, 1.3],
      [1.3, 1.5],
      [1.5, 2.5],
    ]);
    expect([0.5, 1, 1.4, 2].map((r) => zoneOf(r, data.zones))).toEqual([
      "below the usual range",
      "in the usual range",
      "high",
      "very high",
    ]);
    expect(shortDate("2026-10-05")).toBe("05/10");
  });

  it("draws before and after per pair, for all sessions or a group", () => {
    const data: PrePostData = {
      widget: "pre_post",
      label: null,
      groups: ["Climbing"],
      pairs: [
        {
          label: "Mood",
          lower_better: false,
          all: { n: 2, pre: 6, post: 7, change: 1 },
          groups: [{ n: 1, pre: 5, post: 8, change: 3 }],
        },
        {
          label: "Skin",
          lower_better: true,
          all: { n: 0, pre: null, post: null, change: null },
          groups: [{ n: 0, pre: null, post: null, change: null }],
        },
      ],
    };
    expect(pairStats(data, 0).map((s) => s.change)).toEqual([3, null]);
    const option = prePostOption(data, -1) as Option;
    const before = option.series.find((s) => s.name === "Before");
    expect(before?.data).toEqual([[6, "Mood"], null]);
    expect(option.series[0]?.data).toEqual([
      [6, "Mood"],
      [7, "Mood"],
    ]);
    expect(option.series[1]?.data).toEqual([]); // no pair for skin
    expect([
      changeTone(1, false),
      changeTone(-1, true),
      changeTone(2, true),
      changeTone(0, true),
      changeTone(1, null),
      changeTone(-1, false),
    ]).toEqual(["green", "inherit", "inherit", "dimmed", "dimmed", "red"]); // soreness: neutral
  });

  it("maps body parts by week, red at the bad end of the scale", () => {
    const data: BodyHeatmapData = {
      widget: "body_heatmap",
      label: null,
      parts: ["Fingers", "Skin"],
      weeks: ["2026-W43", "2026-W44"],
      starts: ["2026-10-19", "2026-10-26"],
      sources: [
        {
          label: "Before",
          values: [
            [3, null],
            [null, 6],
          ],
          n: [
            [1, 0],
            [0, 2],
          ],
        },
      ],
      scale: [1, 10],
      lower_better: true,
      shown: 12,
    };
    const option = bodyOption(data, 0) as Option;
    expect(option.series[0]?.data).toEqual([
      [0, 0, 3],
      [1, 1, 6],
    ]);
    const map = option.visualMap as {
      min: number;
      max: number;
      inRange: { color: string[] };
      text: string[];
    };
    expect([map.min, map.max, map.inRange.color.at(-1)]).toEqual([1, 10, "#e03131"]);
    expect(map.text).toEqual(["10", "1"]); // the scale's ends at the colour bar
    const better = bodyOption({ ...data, lower_better: false }, 0) as Option;
    expect((better.visualMap as { inRange: { color: string[] } }).inRange.color[0]).toBe("#e03131");
  });

  it("puts French and gym grades on their own axes and builds the pyramid", () => {
    const data: GradesData = {
      widget: "grades",
      label: null,
      series: [
        {
          system: "french",
          venue: null,
          label: "French",
          points: [{ date: "2026-10-01", index: 32, grade: "6b", setting: null, venue: null }],
        },
        {
          system: "gym",
          venue: "Nord",
          label: "Gym · Nord",
          points: [{ date: "2026-10-02", index: 5, grade: "5", setting: null, venue: "Nord" }],
        },
      ],
      french_ticks: [
        { index: 32, label: "6b" },
        { index: 33, label: "6b+" },
      ],
      pyramid: {
        periods: ["2026-09", "2026-10"],
        rows: [
          {
            label: "French",
            grades: ["6a", "6b"],
            counts: [
              [1, 0],
              [0, 2],
            ],
          },
        ],
      },
      by_setting: [],
      by_venue: [],
      unparsed: 0,
      last: 6,
    };
    const option = gradesOption(data) as Option;
    const axes = option.yAxis as {
      name: string;
      axisLabel?: { formatter: (v: number) => string };
    }[];
    expect(axes.map((a) => a.name)).toEqual(["French", "Gym"]);
    expect(axes[0]?.axisLabel?.formatter(33)).toBe("6b+");
    expect(option.series.map((s) => [s.name, s.yAxisIndex])).toEqual([
      ["French", 0],
      ["Gym · Nord", 1],
    ]);
    const gymOnly = gradesOption({
      ...data,
      series: data.series.slice(1),
      french_ticks: [],
    }) as Option;
    expect(gymOnly.series[0]?.yAxisIndex).toBe(0);
    const pyramid = pyramidOption(data, 0, 1) as Option;
    expect(pyramid.series[0]?.data).toEqual([0, 2]);
    expect((pyramid.yAxis as { data: string[] }).data).toEqual(["6a", "6b"]);
  });
});
