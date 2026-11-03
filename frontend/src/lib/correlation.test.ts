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
const WINDOW = new URLSearchParams("start=2026-08-02&end=2026-10-30");

describe("the correlation tabs", () => {
  it("keep their state in the URL next to the trends'", () => {
    const params = new URLSearchParams(
      "metric=a.b.c&tab=pair&x=a.b.c&y=a.b.d&lag=1&method=pearson",
    );
    const state = readCorrelation(params);
    expect(state).toEqual({
      tab: "pair",
      x: "a.b.c",
      y: "a.b.d",
      lag: 1,
      matrix: [],
      target: null,
      method: "pearson",
    });
    const written = writeCorrelation(new URLSearchParams("metric=a.b.c"), {
      ...state,
      matrix: ["m1", "m2"],
    });
    expect(written.toString()).toBe(
      "metric=a.b.c&tab=pair&x=a.b.c&y=a.b.d&lag=1&mx=m1&mx=m2&method=pearson",
    );
    expect(readCorrelation(new URLSearchParams("tab=nope&lag=99")).tab).toBe("trends");
    expect(readCorrelation(new URLSearchParams("lag=99")).lag).toBe(0);
  });

  it("build each tab's query over the trends' range", () => {
    const pair = readCorrelation(new URLSearchParams("tab=pair&x=a&y=b&lag=2"));
    expect(correlationQuery(pair, WINDOW)).toBe("x=a&y=b&lag=2&start=2026-08-02&end=2026-10-30");
    expect(correlationQuery({ ...pair, y: null }, WINDOW)).toBeNull();
    const matrix = readCorrelation(new URLSearchParams("tab=matrix&mx=a&mx=b"));
    expect(correlationQuery(matrix, new URLSearchParams())).toBe(
      "metric=a&metric=b&method=spearman",
    );
    expect(correlationQuery({ ...matrix, matrix: ["a"] }, WINDOW)).toBeNull();
    const ranked = readCorrelation(new URLSearchParams("tab=predictors&target=t"));
    expect(correlationQuery(ranked, new URLSearchParams())).toBe("target=t&method=spearman");
    expect(correlationQuery({ ...ranked, target: null }, WINDOW)).toBeNull();
    expect(correlationQuery(readCorrelation(new URLSearchParams()), WINDOW)).toBeNull();
  });

  it("say r with its interval in plain words", () => {
    expect(withCi({ r: 0.62, low: 0.31, high: 0.82 })).toBe("0,62 (0,31 to 0,82)");
    expect(withCi({ r: 0.5, low: null, high: null })).toBe("0,50");
    expect(withCi({ r: null, low: null, high: null })).toBe("–");
    expect([strength(0.05), strength(-0.2), strength(0.4), strength(0.7), strength(null)]).toEqual([
      "no clear association",
      "a weak negative association",
      "a moderate positive association",
      "a strong positive association",
      "no estimate",
    ]);
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
    const option = pairOption(data, undefined, undefined) as Option;
    expect(option.series[0]).toMatchObject({
      name: "b (1 day(s) later)",
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
