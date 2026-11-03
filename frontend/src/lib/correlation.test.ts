// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { CorrelationPair, MatrixData } from "../api/client";
import {
  correlationQuery,
  matrixOption,
  pairOption,
  readCorrelation,
  strength,
  withCi,
  writeCorrelation,
} from "./correlation";

type Option = Record<string, unknown> & { series: Record<string, unknown>[] };
const TODAY = "2026-10-30";
const NO_SCOPE = { range: "90d", start: null, end: null, filters: {} };

describe("the correlation tabs", () => {
  it("keep their state in the URL next to the trends', each tab its own range and filters", () => {
    const params = new URLSearchParams(
      "metric=a.b.c&filter=a.b.t=Board&tab=pair&x=a.b.c&y=a.b.d&lag=1&points=week&method=pearson&pair-range=all&pair-filter=a.b.t=Climbing&good-range=custom&good-start=2026-10-01",
    );
    const state = readCorrelation(params);
    expect(state).toEqual({
      tab: "pair",
      x: "a.b.c",
      y: "a.b.d",
      lag: 1,
      group: "week",
      matrix: [],
      target: null,
      method: "pearson",
      scopes: {
        // Over time's filter (`filter=`) is its own: no tab takes it
        pair: { range: "all", start: null, end: null, filters: { "a.b.t": ["Climbing"] } },
        matrix: NO_SCOPE,
        predictors: { range: "custom", start: "2026-10-01", end: null, filters: {} },
      },
    });
    const written = writeCorrelation(new URLSearchParams("metric=a.b.c"), {
      ...state,
      matrix: ["m1", "m2"],
    });
    expect(written.toString()).toBe(
      "metric=a.b.c&tab=pair&x=a.b.c&y=a.b.d&lag=1&points=week&mx=m1&mx=m2&method=pearson&pair-range=all&pair-filter=a.b.t%3DClimbing&good-range=custom&good-start=2026-10-01",
    );
    expect(readCorrelation(new URLSearchParams("tab=nope&lag=99")).tab).toBe("trends");
    expect(readCorrelation(new URLSearchParams("lag=99")).lag).toBe(0);
    expect(readCorrelation(new URLSearchParams("points=year")).group).toBe("auto");
  });

  it("build each tab's query over its own range and filters", () => {
    const pair = readCorrelation(new URLSearchParams("tab=pair&x=a&y=b&lag=2"));
    // 90 days by default, ending today
    expect(correlationQuery(pair, TODAY)).toBe("x=a&y=b&lag=2&start=2026-08-02&end=2026-10-30");
    expect(correlationQuery({ ...pair, y: null }, TODAY)).toBeNull();
    const matrix = readCorrelation(new URLSearchParams("tab=matrix&mx=a&mx=b&matrix-range=all"));
    expect(correlationQuery(matrix, TODAY)).toBe(
      "metric=a&metric=b&method=spearman&end=2026-10-30",
    );
    expect(correlationQuery({ ...matrix, matrix: ["a"] }, TODAY)).toBeNull();
    const ranked = readCorrelation(
      new URLSearchParams("tab=predictors&target=t&good-filter=j.s.type=Climbing&pair-filter=x=y"),
    );
    expect(correlationQuery(ranked, TODAY)).toBe(
      "target=t&method=spearman&start=2026-08-02&end=2026-10-30&filter=j.s.type%3DClimbing",
    );
    expect(correlationQuery({ ...pair, group: "week" }, TODAY)).toContain("group=week");
    expect(correlationQuery({ ...ranked, target: null }, TODAY)).toBeNull();
    expect(correlationQuery(readCorrelation(new URLSearchParams()), TODAY)).toBeNull();
  });

  it("say r with its interval in plain words", () => {
    expect(withCi({ r: 0.62, low: 0.31, high: 0.82 })).toBe("0,62 (0,31 to 0,82)");
    expect(withCi({ r: 0.5, low: null, high: null })).toBe("0,50");
    expect(withCi({ r: null, low: null, high: null })).toBe("–");
    expect([0.05, -0.2, 0.4, 0.7, null].map((r) => strength({ r, low: null, high: null }))).toEqual(
      [
        "no clear association",
        "a weak negative association",
        "a moderate positive association",
        "a strong positive association",
        "no estimate",
      ],
    );
    // an interval that includes 0: there could be no association at all
    expect(strength({ r: 0.77, low: -0.09, high: 0.97 })).toBe(
      "a strong positive association (could be none: the interval includes 0)",
    );
    expect(strength({ r: 0.61, low: 0.29, high: 0.8 })).toBe("a strong positive association");
  });

  it("draw the pair faded when there are too few points, with its line", () => {
    const data: CorrelationPair = {
      x: "a",
      y: "b",
      lag: 1,
      n: 3,
      min_n: 10,
      too_few: true,
      pearson: { r: null, low: null, high: null, p: null },
      spearman: { r: null, low: null, high: null, p: null },
      slope: 2,
      intercept: -1,
      points: [
        { x: 1, y: 1, date: "2026-10-01" },
        { x: 3, y: 5, date: "2026-10-02" },
      ],
      sources: [],
    };
    const option = pairOption(data, new Map([["b", "Mood · Rest day"]])) as Option;
    expect(option.series[0]).toMatchObject({
      name: "Mood · Rest day (1 day(s) later)",
      itemStyle: { opacity: 0.35 },
    });
    expect(option.series[1]?.data).toEqual([
      [1, 1],
      [3, 5],
    ]);
  });

  it("draw the matrix with hidden cells empty", () => {
    const data: MatrixData = {
      metrics: ["a", "b"],
      method: "spearman",
      min_n: 10,
      cells: [
        [
          { r: 1, n: 12 },
          { r: null, n: 4 },
        ],
        [
          { r: null, n: 4 },
          { r: 1, n: 8 },
        ],
      ],
      sources: [],
    };
    const option = matrixOption(data, ["A", "B"]) as Option;
    expect(option.series[0]?.data).toEqual([
      [0, 0, 1, 12],
      [1, 0, "-", 4],
      [0, 1, "-", 4],
      [1, 1, 1, 8],
    ]);
    expect(option.visualMap).toMatchObject({ dimension: 2, min: -1, max: 1 });
  });
});
