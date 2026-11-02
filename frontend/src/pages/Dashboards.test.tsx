// SPDX-License-Identifier: GPL-3.0-or-later
import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ModuleInfo } from "../api/client";
import { DIARY, HEALTH, stubApi } from "../test/api";
import { renderApp } from "../test/render";

// jsdom draws no canvas: the chart is a labelled box here (lib/lineChart.test.ts checks its option)
vi.mock("../components/Chart", () => ({
  Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));

const WITH_VIEW: ModuleInfo = {
  ...DIARY,
  module_schema: { ...DIARY.module_schema, views: { overview: [], trends: [] } },
};
const VIEW = {
  module: "diary",
  view: "overview",
  date: "2026-10-30",
  as_of: "2026-10-30T09:05:00",
  offline: false,
  widgets: [
    { widget: "kpi", label: "Latest status", agg: "latest", value: "LOW" },
    { widget: "kpi", label: "Days since last session", agg: "days_since_latest", value: 2 },
    {
      widget: "status_board",
      label: "Status by class",
      compare_last: 4,
      window: 12,
      rows: [
        {
          label: "Wellbeing",
          status: "GOOD",
          score: 7.5,
          average_last: 7.3,
          average_previous: 5,
          change: 2.3,
          direction: "up",
          low: 1,
        },
        {
          label: "Physical",
          status: null,
          score: null,
          average_last: null,
          average_previous: null,
          change: null,
          direction: null,
          low: 0,
        },
      ],
    },
    {
      widget: "line",
      label: "Scores by class",
      points: [{ date: "2026-10-28", key: { session_no: 1 } }],
      series: [{ metric: "session.wb_mood_pre", label: "Mood", values: [7], rolling: [7] }],
      bands: [],
      rolling: 4,
      last: 12,
    },
    { widget: "planned", label: null, kind: "heatmap_calendar", why: "comes with #78" },
  ],
};

function api(view: object = VIEW) {
  return stubApi({
    "/api/health": HEALTH,
    "/api/modules": { modules: [WITH_VIEW], problems: [] },
    "/api/modules/diary/views/overview?date=2026-10-30": view,
  });
}

describe("Dashboards", () => {
  it("draws the view's widgets for the day", async () => {
    api();
    renderApp("/dashboards/diary?date=2026-10-30");
    expect(await screen.findByText("Days since last session")).toBeInTheDocument();
    expect(screen.getAllByText("Latest status")).toHaveLength(2); // the KPI and a column
    expect(screen.getByText("LOW")).toBeInTheDocument();
    expect(screen.getByText("2 days")).toBeInTheDocument();
    const board = screen.getByRole("table");
    const wellbeing = within(board).getByRole("row", { name: /Wellbeing/ });
    expect(wellbeing).toHaveTextContent("GOOD7,57,35,0+2,3▲ Improving1");
    expect(within(board).getByRole("row", { name: /Physical/ })).toHaveTextContent(
      "Physical––––––0",
    );
    expect(screen.getByRole("img", { name: "Scores by class" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Last 12" })).toBeChecked();
    expect(screen.getByText("Not drawn yet: comes with #78.")).toBeInTheDocument();
    expect(screen.getByText("Calendar")).toBeInTheDocument();
  });

  it("lets you pick another view, kept in the URL", async () => {
    api();
    const { router } = renderApp("/dashboards/diary?date=2026-10-30");
    expect(await screen.findByRole("radio", { name: "overview" })).toBeChecked();
    screen.getByRole("radio", { name: "trends" }).click();
    await vi.waitFor(() => {
      expect(router.state.location.search).toContain("view=trends");
    });
  });

  it("says when a module has no views", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": { modules: [DIARY], problems: [] } });
    renderApp("/dashboards/diary");
    expect(await screen.findByText("Module 'diary' has no views.")).toBeInTheDocument();
  });
});
