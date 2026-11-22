// SPDX-License-Identifier: GPL-3.0-or-later
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BeforeAfterData, ProgramGridData, WeekTableData } from "../api/client";
import { qualityColour, weekValue } from "../lib/programGrid";
import { renderWithProviders } from "../test/render";
import { BeforeAfterCard, ProgramGridCard, WeekTableCard } from "./ProgramWidgets";

const QUALITIES = ["Clean", "Some shrug/compensation", "Stopped early", "Skipped"];

describe("a program's dashboard", () => {
  it("shows a week table's values by their kind", () => {
    expect(weekValue("share", 4 / 17)).toBe("24%");
    expect(weekValue("count", 3)).toBe("3");
    expect(weekValue("mean", 1.25)).toBe("1,3");
    expect(weekValue("mean", null)).toBe("–");
  });

  it("colours the qualities from best to worst", () => {
    expect(QUALITIES.map((q) => qualityColour(q, QUALITIES))).toEqual([
      "green",
      "yellow",
      "orange",
      "red",
    ]);
    expect(qualityColour(null, QUALITIES)).toBe("gray");
  });

  it("draws the week table, the current week bold", () => {
    const data: WeekTableData = {
      widget: "week_table",
      label: "Weekly dashboard",
      columns: [
        { label: "Log completion", agg: "share" },
        { label: "Green days", agg: "count" },
      ],
      run: 1,
      current: 2,
      weeks: [
        { week: 1, phase: "Block 1", light: false, values: [1, 3] },
        { week: 2, phase: "Block 1", light: false, values: [0.5, 1] },
        { week: 4, phase: "Block 1", light: true, values: [null, 0] },
      ],
    };
    renderWithProviders(<WeekTableCard data={data} />);
    const rows = screen.getAllByRole("row");
    expect(within(rows[1] as HTMLElement).getByText("100%")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("50%")).toBeInTheDocument();
    expect(within(rows[3] as HTMLElement).getByText("light")).toBeInTheDocument();
  });

  it("asks for a run before the first", () => {
    const data: WeekTableData = {
      widget: "week_table",
      label: null,
      columns: [],
      run: null,
      current: null,
      weeks: [],
    };
    renderWithProviders(<WeekTableCard data={data} />);
    expect(screen.getByText(/No run has started yet/)).toBeInTheDocument();
  });

  it("draws the program grid by session", () => {
    const data: ProgramGridData = {
      widget: "program_grid",
      label: "Program",
      run: 1,
      current: 2,
      qualities: QUALITIES,
      weeks: [
        { week: 1, phase: null, light: false, share: 0.5 },
        { week: 2, phase: null, light: false, share: null },
      ],
      rows: [
        {
          key: "A1",
          name: "[ESEMPIO] Row",
          group: "A",
          share: 1,
          cells: [
            { prescribed: "3×8", skip: false, logged: 1, quality: "Clean" },
            { prescribed: "Skip", skip: true, logged: 0, quality: null },
          ],
        },
      ],
    };
    renderWithProviders(<ProgramGridCard data={data} />);
    expect(screen.getByText("A1 · [ESEMPIO] Row")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("3×8")).toBeInTheDocument();
    expect(screen.getByText("Skip")).toBeInTheDocument();
    expect(screen.getAllByText("50%")).toHaveLength(1);
  });

  it("draws the retests with their change", () => {
    const data: BeforeAfterData = {
      widget: "before_after",
      label: "Retests",
      checkpoints: ["Start", "End W4"],
      rows: [
        {
          key: "M1",
          label: "[ESEMPIO] Hang (s)",
          cells: [
            { date: "2026-09-07", value: 10 },
            { date: "2026-10-04", value: 12.5 },
          ],
          change: { diff: 2.5, better: true, first: null, latest: null },
        },
        {
          key: "M2",
          label: "[ESEMPIO] Clicking?",
          cells: [{ date: "2026-09-07", value: "Yes" }, null],
          change: null,
        },
      ],
    };
    renderWithProviders(<BeforeAfterCard data={data} />);
    expect(screen.getByText("+2,5")).toBeInTheDocument();
    expect(screen.getByText("12,5")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });
});
