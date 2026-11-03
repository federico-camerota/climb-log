// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { MetricInfo, QueryResult } from "../api/client";
import { THICK_LINE_ICON } from "./charts";
import {
  exploreOption,
  fits,
  axisName,
  metricGroup,
  metricNames,
  metricQuery,
  pointLabel,
  readState,
  unitOf,
  writeState,
} from "./explore";

function metric(
  id: string,
  label: string,
  unit: string | null,
  scale: [number, number] | null,
): MetricInfo {
  const [module = "", entity = "", field = ""] = id.split(".");
  return {
    id,
    module,
    entity,
    field,
    label,
    section: "Wellbeing · before",
    derived: false,
    unit,
    scale,
    direction: null,
  };
}

const SLEEP = metric("journal.session.wb_sleep_hours", "Sleep hours", "h", [0, 14]);
const MOOD = metric("journal.session.wb_mood_pre", "Mood", null, [1, 10]);
const LOAD = metric("journal.session.session_load", "Session load", null, null);
const FINGER_LOAD = metric("finger_strength.session.set_load", "Set load", null, null);
const MOOD_AFTER = {
  ...metric("journal.session.wb_mood_post", "Mood", null, [1, 10]),
  section: "Wellbeing · after",
};
const REST_MOOD = { ...metric("journal.rest_day.mood", "Mood", null, [1, 10]), section: null };

type Option = Record<string, unknown> & { series: Record<string, unknown>[] };

describe("the Explore page's state", () => {
  it("reads and writes the URL, leaving the defaults out", () => {
    const params = new URLSearchParams(
      "metric=a.b.c&metric=a.b.d&range=custom&start=2026-10-01&end=2026-10-30&group=week&agg=sum&rolling=3&filter=a.b.t=Climbing&filter=a.b.t=Hangboard&chart=bars",
    );
    const state = readState(params);
    expect(state).toEqual({
      metrics: ["a.b.c", "a.b.d"],
      range: "custom",
      start: "2026-10-01",
      end: "2026-10-30",
      group: "week",
      agg: "sum",
      rolling: 3,
      filters: { "a.b.t": ["Climbing", "Hangboard"] },
      chart: "bars",
    });
    expect(writeState(state).toString()).toBe(params.toString());
    const plain = readState(new URLSearchParams("group=nope&rolling=1&filter=bad"));
    expect([
      plain.range,
      plain.group,
      plain.agg,
      plain.rolling,
      plain.filters,
      plain.chart,
    ]).toEqual(["90d", "day", "mean", null, {}, "line"]);
    expect(writeState(plain).toString()).toBe("");
  });

  it("builds the metric query for the range", () => {
    const state = readState(new URLSearchParams("metric=a.b.c&range=7d"));
    expect(metricQuery(state, "2026-10-30")).toBe(
      "metric=a.b.c&start=2026-10-24&end=2026-10-30&group=day&agg=mean",
    );
    const all = readState(new URLSearchParams("metric=a.b.c&range=all&rolling=4&filter=a.b.t=X"));
    expect(metricQuery(all, "2026-10-30")).toBe(
      "metric=a.b.c&end=2026-10-30&group=day&agg=mean&rolling=4&filter=a.b.t%3DX",
    );
    const custom = readState(new URLSearchParams("metric=a.b.c&range=custom&start=2026-09-01"));
    expect(metricQuery(custom, "2026-10-30")).toBe(
      "metric=a.b.c&start=2026-09-01&end=2026-10-30&group=day&agg=mean",
    );
    expect(metricQuery(readState(new URLSearchParams()), "2026-10-30")).toBeNull();
  });

  it("allows two units at most", () => {
    // a metric without unit or scale is a unit of its own: never on another's axis
    expect([unitOf(SLEEP), unitOf(MOOD), unitOf(LOAD)]).toEqual([
      "h",
      "1–10",
      "#journal.session.session_load",
    ]);
    expect(fits(LOAD, [SLEEP])).toBe(true);
    expect(fits(LOAD, [SLEEP, MOOD])).toBe(false);
    expect(fits(SLEEP, [SLEEP, MOOD])).toBe(true);
    expect(fits(FINGER_LOAD, [LOAD])).toBe(true); // two axes
    expect(fits(SLEEP, [LOAD, FINGER_LOAD])).toBe(false);
    expect(axisName(LOAD, metricNames([LOAD]))).toBe("Session load");
    expect(metricGroup(SLEEP)).toBe("journal · session · Wellbeing · before");
  });

  it("tells metrics with the same label apart", () => {
    const names = metricNames([SLEEP, MOOD, MOOD_AFTER, REST_MOOD]);
    expect([...names.values()]).toEqual([
      "Sleep hours", // unique: as is
      "Mood · Wellbeing · before",
      "Mood · Wellbeing · after",
      "Mood · Rest day", // no section: its entity
    ]);
  });

  it("labels days shortly, a day's second record, and periods as given", () => {
    const point = { start: "2026-10-30", end: "2026-10-30", label: "2026-10-30", key: null };
    expect(pointLabel(point)).toBe("30/10/26");
    expect(pointLabel({ ...point, key: { session_no: 2 } })).toBe("30/10/26 (2)");
    expect(pointLabel({ ...point, label: "2026-W44" })).toBe("2026-W44");
  });

  it("draws one axis per unit, the rolling mean and n in the tooltip", () => {
    const result: QueryResult = {
      group: "week",
      agg: "mean",
      lag: 0,
      points: [
        { start: "2026-10-19", end: "2026-10-25", label: "2026-W43", key: null },
        { start: "2026-10-26", end: "2026-11-01", label: "2026-W44", key: null },
      ],
      series: [
        { metric: SLEEP.id, values: [7, 7.5], n: [3, 2], rolling: [7, 7.25] },
        { metric: MOOD.id, values: [6, null], n: [3, 0], rolling: null },
      ],
      sources: [],
    };
    const option = exploreOption(result, [SLEEP, MOOD], "line") as Option;
    expect((option.yAxis as { name: string }[]).map((a) => a.name)).toEqual(["h", "1–10"]);
    expect(option.series.map((s) => [s.name, s.yAxisIndex])).toEqual([
      ["Sleep hours", 0],
      ["Sleep hours (rolling mean)", 0],
      ["Mood", 1],
    ]);
    // the rolling mean is a thick line without dots, in the legend too; the values have dots
    expect(option.series.map((s) => s.symbol)).toEqual([undefined, "none", undefined]);
    // ECharts gives a line series' legend icon a dot even without symbols: a drawn bar instead
    expect((option.legend as { data: unknown[] }).data).toEqual([
      "Sleep hours",
      { name: "Sleep hours (rolling mean)", icon: THICK_LINE_ICON },
      "Mood",
    ]);
    const tooltip = option.tooltip as {
      formatter: (
        p: { dataIndex: number; seriesId: string; seriesName: string; value: number | null }[],
      ) => string;
    };
    expect(
      tooltip.formatter([
        { dataIndex: 1, seriesId: SLEEP.id, seriesName: "Sleep hours", value: 7.5 },
        { dataIndex: 1, seriesId: MOOD.id, seriesName: "Mood", value: null },
      ]),
    ).toBe("2026-W44<br/>Sleep hours: 7,5 (n = 2)<br/>Mood: – (n = 0)");
    const bars = exploreOption(result, [SLEEP, MOOD], "bars") as Option;
    expect(bars.series[0]?.type).toBe("bar");
  });

  it("finds n by the metric, not its name, when labels repeat", () => {
    const result: QueryResult = {
      group: "week",
      agg: "mean",
      lag: 0,
      points: [{ start: "2026-10-26", end: "2026-11-01", label: "2026-W44", key: null }],
      series: [
        { metric: MOOD.id, values: [7], n: [3], rolling: null },
        { metric: REST_MOOD.id, values: [8], n: [1], rolling: null },
      ],
      sources: [],
    };
    const option = exploreOption(result, [MOOD, REST_MOOD], "line") as Option;
    expect(option.series.map((s) => s.name)).toEqual([
      "Mood · Wellbeing · before",
      "Mood · Rest day",
    ]);
    const tooltip = option.tooltip as {
      formatter: (
        p: { dataIndex: number; seriesId: string; seriesName: string; value: number }[],
      ) => string;
    };
    expect(
      tooltip.formatter([
        { dataIndex: 0, seriesId: MOOD.id, seriesName: "Mood · Wellbeing · before", value: 7 },
        { dataIndex: 0, seriesId: REST_MOOD.id, seriesName: "Mood · Rest day", value: 8 },
      ]),
    ).toBe("2026-W44<br/>Mood · Wellbeing · before: 7 (n = 3)<br/>Mood · Rest day: 8 (n = 1)");
  });

  it("draws a line's status bands behind it, on the whole scale", () => {
    const bands = [
      { label: "LOW", from: null, to: 4 },
      { label: "WATCH", from: 4, to: 6 },
      { label: "GOOD", from: 6, to: null },
    ];
    const result: QueryResult = {
      group: "week",
      agg: "mean",
      lag: 0,
      points: [{ start: "2026-10-26", end: "2026-11-01", label: "2026-W44", key: null }],
      series: [{ metric: MOOD.id, values: [7], n: [3], rolling: null, bands }],
      sources: [],
    };
    const option = exploreOption(result, [MOOD], "line") as Option;
    const [band] = option.series;
    expect(band?.id).toBe("bands");
    const areas = (band?.markArea as { data: { yAxis: number }[][] }).data;
    expect(areas.map(([from, to]) => [from?.yAxis, to?.yAxis])).toEqual([
      [1, 4],
      [4, 6],
      [6, 10],
    ]);
    expect((option.yAxis as Record<string, unknown>[])[0]).toMatchObject({ min: 1, max: 10 });
    const bars = exploreOption(result, [MOOD], "bars") as Option; // bands only behind a line
    expect(bars.series.map((s) => s.id)).toEqual([MOOD.id]);
    // a line without those bands on the same axis (rest-day mood): no bands for either
    const mixed = exploreOption(
      {
        ...result,
        series: [...result.series, { metric: REST_MOOD.id, values: [8], n: [1], rolling: null }],
      },
      [MOOD, REST_MOOD],
      "line",
    ) as Option;
    expect(mixed.series.map((s) => s.id)).toEqual([MOOD.id, REST_MOOD.id]);
  });
});
