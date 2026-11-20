// SPDX-License-Identifier: GPL-3.0-or-later
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ModuleInfo, ReferenceTableRows } from "../api/client";
import { HEALTH, MODULES, stubApi } from "../test/api";
import { renderApp } from "../test/render";

// A fictional program with two reference tables (D-112): exercises with a prescription per
// week (three weeks), and tracks.
const PROGRAM: ModuleInfo = {
  id: "mobility",
  name: "Mobility block",
  version: 1,
  kind: "program",
  problems: [],
  module_schema: {
    entities: { session: { fields: { date: { type: "date" } } } },
    reference: {
      exercises: {
        label: "Exercises",
        tab: "Exercises",
        key: "id",
        fields: {
          id: { type: "text" },
          name: { type: "text", required: true },
          session: { type: "choice", choices: ["A", "B"] },
        },
        per_week: { name: "prescription" },
      },
      tracks: { tab: "Tracks", key: "id", fields: { id: { type: "text" } } },
    },
  },
};

const EXERCISES = {
  name: "exercises",
  label: "Exercises",
  tab: "Exercises",
  key: "id",
  columns: ["id", "name", "session", "w1", "w2", "w3", "retired"],
  week_columns: ["w1", "w2", "w3"],
  per_week_label: "Prescription",
};

function rows(extra: Partial<ReferenceTableRows> = {}): ReferenceTableRows {
  return {
    module: "mobility",
    table: EXERCISES,
    rows: [
      {
        values: {
          id: "A1",
          name: "Wall slides",
          session: "A",
          w1: "2×10",
          w2: "3×10",
          w3: null,
          retired: false,
        },
        row: 3,
      },
      { values: { id: "A2", name: "Band pulls", session: "A", retired: true }, row: 4 },
    ],
    issues: [
      {
        tab: "Exercises",
        row: 5,
        field: "id",
        message: "no id: the row is left out",
        kind: "left_out",
      },
    ],
    as_of: "2026-11-20T09:05:00",
    offline: false,
    ...extra,
  };
}

const URL = "/api/modules/mobility/reference/exercises";
const API = {
  "/api/health": HEALTH,
  "/api/modules": { modules: [...MODULES.modules, PROGRAM], problems: [] },
  [URL]: rows(),
};

describe("Program", () => {
  it("opens the first module with tables, on its first table", async () => {
    stubApi(API);
    const { router } = renderApp("/program");
    expect(await screen.findByText("1 row · 1 retired · 1 data issue")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/program/mobility/exercises");
    expect(screen.getByRole("tab", { name: "Exercises" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Tracks" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Id", "Name", "Session", "W1", "W2", "W3"]);
    expect(within(table).getByText("Wall slides")).toBeInTheDocument();
    expect(within(table).queryByText("Band pulls")).not.toBeInTheDocument(); // retired
    expect(screen.getByText(/Exercises, row 5: id: no id/)).toBeInTheDocument();
  });

  it("shows retired rows on demand", async () => {
    stubApi(API);
    renderApp("/program/mobility/exercises");
    await userEvent.click(await screen.findByRole("switch", { name: "Show retired" }));
    expect(screen.getByText("Band pulls")).toBeInTheDocument();
    expect(screen.getByText("retired")).toBeInTheDocument();
  });

  it("edits a row without its key, sending only what changed", async () => {
    const calls = stubApi({
      ...API,
      [`PATCH ${URL}/row?key=A1`]: rows(),
    });
    renderApp("/program/mobility/exercises");
    await userEvent.click(await screen.findByText("Wall slides"));
    const dialog = await screen.findByRole("dialog", { name: "Exercises · A1" });
    expect(within(dialog).getByRole("textbox", { name: "Id" })).toHaveAttribute("readonly");
    const w3 = within(dialog).getByRole("textbox", { name: "W3" });
    await userEvent.type(w3, "Skip");
    await userEvent.click(within(dialog).getByRole("switch", { name: /Retired/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({
      values: { w3: "Skip", retired: true },
      expected: { w3: null, retired: false },
    });
  });

  it("adds a row, and shows the API's problem", async () => {
    const calls = stubApi({
      ...API,
      [`POST ${URL}`]: () =>
        Promise.resolve(
          Response.json(
            {
              detail: {
                message: "Exercises: A1 is already there",
                field: "id",
                problems: [{ field: "id", message: "Exercises: A1 is already there" }],
              },
            },
            { status: 409 },
          ),
        ),
    });
    renderApp("/program/mobility/exercises");
    await userEvent.click(await screen.findByRole("button", { name: "Add row" }));
    const dialog = await screen.findByRole("dialog", { name: "New row · Exercises" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(within(dialog).getByText("A new row needs its id.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Id" }), "A1");
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Name/ }), "Squats");
    await userEvent.type(within(dialog).getByRole("textbox", { name: "W1" }), "3×8");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    expect((await within(dialog).findAllByText("Exercises: A1 is already there")).length).toBe(2);
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      values: { id: "A1", name: "Squats", w1: "3×8" },
    });
  });

  it("is read-only offline", async () => {
    stubApi({ ...API, [URL]: rows({ offline: true }) });
    renderApp("/program/mobility/exercises");
    expect(await screen.findByText("Offline · read-only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add row" })).toBeDisabled();
  });

  it("says so when no module has tables", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": MODULES });
    renderApp("/program");
    expect(await screen.findByText(/No module has reference tables yet/)).toBeInTheDocument();
  });

  it("says so for an unknown table", async () => {
    stubApi(API);
    renderApp("/program/mobility/rungs");
    expect(await screen.findByText("Module 'mobility' has no table 'rungs'.")).toBeInTheDocument();
  });
});
