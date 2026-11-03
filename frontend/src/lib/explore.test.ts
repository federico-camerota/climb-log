// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { MetricInfo, QueryResult } from "../api/client";
import {
  exploreOption,
  fits,
  metricGroup,
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
    expect([unitOf(SLEEP), unitOf(MOOD), unitOf(LOAD)]).toEqual(["h", "1–10", "value"]);
    expect(fits(LOAD, [SLEEP])).toBe(true);
    expect(fits(LOAD, [SLEEP, MOOD])).toBe(false);
    expect(fits(SLEEP, [SLEEP, MOOD])).toBe(true);
    expect(metricGroup(SLEEP)).toBe("journal · session · Wellbeing · before");
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
    const tooltip = option.tooltip as {
      formatter: (p: { dataIndex: number; seriesName: string; value: number | null }[]) => string;
    };
    expect(
      tooltip.formatter([
        { dataIndex: 1, seriesName: "Sleep hours", value: 7.5 },
        { dataIndex: 1, seriesName: "Mood", value: null },
      ]),
    ).toBe("2026-W44<br/>Sleep hours: 7,5 (n = 2)<br/>Mood: – (n = 0)");
    const bars = exploreOption(result, [SLEEP, MOOD], "bars") as Option;
    expect(bars.series[0]?.type).toBe("bar");
  });
});
