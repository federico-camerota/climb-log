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
    {
      widget: "heatmap_calendar",
      label: "Sessions and rest days",
      start: "2025-11-01",
      end: "2026-10-30",
      extra: "rest_day",
      days: [{ date: "2026-10-28", status: "LOW", records: 1, extra: null }],
    },
    {
      widget: "side_by_side",
      label: "Last sessions side by side",
      last: 4,
      groups: [{ label: "Wellbeing", rows: [{ field: "wb_mood_pre", label: "Mood" }] }],
      records: [5, 4, 3, 2, 1].map((d) => ({
        date: `2026-10-2${String(d)}`,
        key: { session_no: 1 },
        values: { wb_mood_pre: d + 3 },
      })),
      notes: [{ field: "wb_note_pre", label: "Wellbeing — before", text: "[ESEMPIO] stanco" }],
    },
    {
      widget: "text_feed",
      label: "Wins & reflect, last 2 weeks",
      window_days: 14,
      lists: [
        {
          label: "Best 'what felt good'",
          items: [
            { date: "2026-10-25", key: { session_no: 1 }, text: "[ESEMPIO] più su", score: 8 },
          ],
        },
        { label: "Biggest 'what felt off'", items: [] },
      ],
      attention: {
        label: "NEEDS ATTENTION",
        items: [{ date: "2026-10-24", key: { session_no: 2 }, texts: ["[ESEMPIO] dita"] }],
      },
    },
    {
      widget: "table",
      label: "Rest days, last 2 weeks",
      columns: [
        { field: "date", label: "Date" },
        { field: "status", label: "Status" },
      ],
      rows: [{ date: "2026-10-29", status: "GOOD" }],
      averages: [{ field: "wellbeing_score", label: "Wellbeing", value: 6.5 }],
      note: { date: "2026-10-29", text: "[ESEMPIO] riposo" },
    },
    {
      widget: "monthly",
      label: "Monthly averages",
      count_label: "Sessions logged",
      classes: ["Wellbeing"],
      overall: "Overall",
      low: true,
      extra: ["Rest days logged"],
      months: 6,
      rows: [
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
      ].map((month, i) => ({
        month,
        count: i,
        classes: [i === 0 ? null : 5.5],
        overall: i === 0 ? null : 5.5,
        low: i === 0 ? null : 1,
        extra: [2],
      })),
    },
    { widget: "planned", label: null, kind: "weekbars", why: "comes with M4" },
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
    expect(screen.getAllByText("LOW")[0]).toBeInTheDocument(); // the KPI (and the LOW column)
    expect(screen.getByText("2 days")).toBeInTheDocument();
    const board = screen.getAllByRole("table")[0] as HTMLElement; // the status board, first
    const wellbeing = within(board).getByRole("row", { name: /Wellbeing/ });
    expect(wellbeing).toHaveTextContent("GOOD7,57,35,0+2,3▲ Improving1");
    expect(within(board).getByRole("row", { name: /Physical/ })).toHaveTextContent(
      "Physical––––––0",
    );
    expect(screen.getByRole("img", { name: "Scores by class" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Last 12" })).toBeChecked();
    expect(screen.getByText("Not drawn yet: comes with M4.")).toBeInTheDocument();
    expect(screen.getByText("Weekly bars")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Sessions and rest days" })).toBeInTheDocument();
  });

  it("shows the last sessions side by side, 4 at first, and the latest notes", async () => {
    api();
    renderApp("/dashboards/diary?date=2026-10-30");
    const card = (await screen.findByText("Last sessions side by side")).closest(
      "div",
    ) as HTMLElement;
    expect(within(card).getByRole("radio", { name: "4" })).toBeChecked();
    expect(screen.getByRole("row", { name: /^Mood/ })).toHaveTextContent("Mood8765");
    screen.getByRole("radio", { name: "8" }).click();
    expect(await screen.findByRole("row", { name: /^Mood/ })).toHaveTextContent("Mood87654");
    expect(screen.getByText("[ESEMPIO] stanco")).toBeInTheDocument();
  });

  it("shows the reflections, the rest days and the monthly table", async () => {
    api();
    renderApp("/dashboards/diary?date=2026-10-30");
    expect(await screen.findByText("[ESEMPIO] più su")).toBeInTheDocument();
    expect(screen.getByText("No scored entries in the last 14 days.")).toBeInTheDocument();
    expect(screen.getByText("NEEDS ATTENTION")).toBeInTheDocument();
    expect(screen.getByText("24/10/2026 (2)")).toBeInTheDocument();
    expect(screen.getByText("1 logged · average wellbeing 6,5")).toBeInTheDocument();
    expect(screen.getByText("[ESEMPIO] riposo")).toBeInTheDocument();
    const months = screen.getAllByRole("row", { name: /^(Mar|Apr|May|Jun|Jul|Aug|Sep|Oct) 26/ });
    expect(months.map((r) => r.textContent.slice(0, 6))).toEqual([
      "Oct 26",
      "Sep 26",
      "Aug 26",
      "Jul 26",
      "Jun 26",
      "May 26",
    ]);
    within(screen.getByRole("radiogroup", { name: "Months shown" }))
      .getByRole("radio", { name: "All" })
      .click();
    await vi.waitFor(() => {
      expect(screen.getByRole("row", { name: /^Mar 26/ })).toHaveTextContent("Mar 260–––2");
    });
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
