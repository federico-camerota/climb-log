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
});
