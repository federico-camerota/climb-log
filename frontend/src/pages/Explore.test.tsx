// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HEALTH, stubApi } from "../test/api";
import { renderApp } from "../test/render";

vi.mock("../components/Chart", () => ({
  Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));

const CATALOGUE = {
  metrics: [
    {
      id: "diary.session.sleep",
      module: "diary",
      entity: "session",
      field: "sleep",
      label: "Sleep hours",
      section: "Before",
      derived: false,
      unit: "h",
      scale: [0, 14],
      direction: null,
    },
    {
      id: "diary.session.mood",
      module: "diary",
      entity: "session",
      field: "mood",
      label: "Mood",
      section: "Before",
      derived: false,
      unit: null,
      scale: [1, 10],
      direction: "higher_better",
    },
    {
      id: "diary.session.load",
      module: "diary",
      entity: "session",
      field: "load",
      label: "Session load",
      section: null,
      derived: true,
      unit: null,
      scale: null,
      direction: null,
    },
  ],
  filters: [
    {
      id: "diary.session.kind",
      module: "diary",
      entity: "session",
      field: "kind",
      label: "Session type",
      choices: ["Climbing", "Hangboard"],
    },
  ],
};
const PAGE =
  "/explore?metric=diary.session.sleep&metric=diary.session.mood&range=custom&start=2026-10-01&end=2026-10-30&group=week";
const QUERY =
  "/api/metrics/query?metric=diary.session.sleep&metric=diary.session.mood&start=2026-10-01&end=2026-10-30&group=week&agg=mean";
const RESULT = {
  group: "week",
  agg: "mean",
  lag: 0,
  points: [{ start: "2026-10-26", end: "2026-11-01", label: "2026-W44", key: null }],
  series: [
    { metric: "diary.session.sleep", values: [7], n: [3], rolling: null },
    { metric: "diary.session.mood", values: [6], n: [2], rolling: null },
  ],
  sources: [],
};

function api(extra: Record<string, object> = {}) {
  return stubApi({ "/api/health": HEALTH, "/api/metrics": CATALOGUE, [QUERY]: RESULT, ...extra });
}

describe("Explore", () => {
  it("draws the metrics of the URL with their n", async () => {
    api();
    renderApp(PAGE);
    expect(await screen.findByRole("img", { name: "Explore chart" })).toBeInTheDocument();
    expect(screen.getByText("Sleep hours: n = 3 · Mood: n = 2")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Custom" })).toBeChecked();
    expect(screen.getByRole("textbox", { name: "From" })).toHaveValue("01/10/2026");
    expect(screen.getAllByLabelText("Only session type").length).toBeGreaterThan(0);
  });

  it("keeps a third unit out", async () => {
    api();
    renderApp(PAGE);
    await userEvent.click(await screen.findByPlaceholderText("Pick one or more"));
    const load = await screen.findByRole("option", { name: "Session load", hidden: true });
    expect(load).toHaveAttribute("data-combobox-disabled", "true");
  });

  it("asks for a metric first, and says when nothing is in the range", async () => {
    api({ [QUERY]: { ...RESULT, points: [], series: [] } });
    renderApp("/explore");
    expect(await screen.findByText("Pick a metric to see it over time.")).toBeInTheDocument();
    renderApp(PAGE);
    expect(await screen.findByText("Nothing logged in this range.")).toBeInTheDocument();
  });

  it("says when no module has numbers", async () => {
    api({ "/api/metrics": { metrics: [], filters: [] } });
    renderApp("/explore");
    expect(await screen.findByText(/No module with numbers to explore/)).toBeInTheDocument();
  });

  it("shows the query's error", async () => {
    stubApi({ "/api/health": HEALTH, "/api/metrics": CATALOGUE });
    renderApp(PAGE);
    expect(await screen.findByText(/failed with HTTP 404|Not Found/)).toBeInTheDocument();
  });

  it("shows a pair with n, its interval, and a warning under the minimum n", async () => {
    api({
      "/api/correlation/pair?x=diary.session.sleep&y=diary.session.mood&start=2026-10-01&end=2026-10-30":
        {
          x: "diary.session.sleep",
          y: "diary.session.mood",
          lag: 0,
          n: 6,
          min_n: 10,
          too_few: true,
          pearson: { r: 0.62, low: -0.3, high: 0.95, p: 0.2 },
          spearman: { r: 0.55, low: -0.4, high: 0.93, p: 0.25 },
          slope: 1,
          intercept: 0,
          points: [{ x: 7, y: 6, date: "2026-10-02" }],
          sources: [],
        },
    });
    renderApp(`${PAGE}&tab=pair&x=diary.session.sleep&y=diary.session.mood`);
    expect(await screen.findByRole("img", { name: "Pair chart" })).toBeInTheDocument();
    expect(screen.getByText(/Only 6 point\(s\): under 10/)).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Pearson/ })).toHaveTextContent(
      "Pearson (linear)0,62 (-0,30 to 0,95)a strong positive association",
    );
  });

  it("ranks what goes with a good session, feel score by default", async () => {
    const catalogue = {
      ...CATALOGUE,
      metrics: [
        ...CATALOGUE.metrics,
        {
          ...CATALOGUE.metrics[1],
          id: "diary.session.feel_score",
          field: "feel_score",
          label: "Feel score",
        },
      ],
    };
    api({
      "/api/metrics": catalogue,
      "/api/correlation/predictors?target=diary.session.feel_score&method=spearman&start=2026-10-01&end=2026-10-30":
        {
          target: "diary.session.feel_score",
          method: "spearman",
          min_n: 10,
          predictors: [
            {
              metric: "diary.session.sleep",
              n: 14,
              too_few: false,
              stat: { r: 0.4, low: 0.1, high: 0.7, p: 0.04 },
            },
            {
              metric: "diary.session.mood",
              n: 3,
              too_few: true,
              stat: { r: null, low: null, high: null, p: null },
            },
          ],
          sources: [],
        },
    });
    renderApp(`${PAGE}&tab=predictors`);
    expect(await screen.findByRole("row", { name: /Sleep hours/ })).toHaveTextContent(
      "Sleep hours0,40 (0,10 to 0,70)14a moderate positive association",
    );
    expect(screen.getByRole("row", { name: /Mood/ })).toHaveTextContent("too few (under 10)");
    expect(screen.getByText(/Associations, not causes/)).toBeInTheDocument();
  });

  it("asks for two metrics in the matrix", async () => {
    api();
    renderApp(`${PAGE}&tab=matrix`);
    expect(await screen.findByPlaceholderText("Pick two or more")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Matrix" })).toHaveAttribute("aria-selected", "true");
  });
});
