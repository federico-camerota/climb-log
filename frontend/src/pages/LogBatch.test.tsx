// SPDX-License-Identifier: GPL-3.0-or-later
// Batch and repeated forms on the Log page (D-115): a fictional program's session exercises,
// one row each saved together, and drill tries with the drill and level kept for the next.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { BatchRows, ModuleInfo, ReferenceTableRows } from "../api/client";
import { HEALTH, records, stubApi, written } from "../test/api";
import { renderApp } from "../test/render";

const PROGRAM: ModuleInfo = {
  id: "prog",
  name: "Mobility",
  version: 1,
  kind: "journal",
  problems: [],
  notes: [],
  module_schema: {
    scales: { sore: { min: 0, max: 10, direction: "lower_better" } },
    reference: {
      exercises: { tab: "Exercises", key: "id", fields: { id: { type: "text" } } },
      drills: { tab: "Drills", key: "id", fields: { id: { type: "text" } } },
    },
    entities: {
      exercise_log: {
        label: "Exercise log",
        key: ["date", "exercise"],
        fields: {
          date: { type: "date", required: true },
          exercise: { type: "ref", reference: "exercises", required: true },
          done: { type: "text" },
          effort: { type: "integer", min: 1, max: 10 },
        },
      },
      drill_try: {
        label: "Drill try",
        key: ["date", "try_no"],
        fields: {
          date: { type: "date", required: true },
          try_no: { type: "integer", min: 1, default: "next" },
          drill: { type: "text" },
          level: { type: "choice", choices: ["L1", "L2"] },
          wobble: { type: "integer", min: 0, max: 10 },
        },
      },
    },
    forms: {
      session_a: {
        entity: "exercise_log",
        batch_over: { reference: "exercises", where: { session: ["Warm-up", "A"] } },
      },
      drill_tries: { entity: "drill_try", repeat: true, keep_fields: ["drill", "level"] },
    },
  },
};

const logged = (exercise: string, done: string) => ({
  values: { date: "2026-09-15", exercise, done, effort: null },
  derived: {},
  rows: { "Exercise log": 3 },
});
const BATCH: BatchRows = {
  module: "prog",
  form: "session_a",
  entity: "exercise_log",
  field: "exercise",
  table: "exercises",
  shared: ["date"],
  rows: [
    {
      key: "W1",
      label: "W1 · Arm circles",
      hint: "Prescription W2: 1×20",
      retired: false,
      record: logged("W1", "1×20"),
    },
    {
      key: "A1",
      label: "A1 · Wall slides",
      hint: "Prescription W2: 3×10",
      retired: false,
      record: null,
    },
    { key: "A3", label: "A3 · Push-ups", hint: null, retired: false, record: null },
  ],
  others: [logged("B1", "2×8")],
  issues: [],
  as_of: "2026-09-15T09:05:00",
  offline: false,
};
const GET_BATCH = "/api/modules/prog/forms/session_a/batch?date=2026-09-15";
const SAVE = "POST /api/modules/prog/exercise_log/batch";

function batchApi(save: object) {
  return stubApi({
    "/api/health": HEALTH,
    "/api/modules": { modules: [PROGRAM], problems: [] },
    [GET_BATCH]: BATCH,
    [SAVE]: save,
  });
}

describe("Log, a batch form (D-115)", () => {
  it("shows a row per exercise and saves the typed ones together", async () => {
    const calls = batchApi({ keys: [{}, {}] });
    renderApp("/log/prog/session_a?date=2026-09-15");
    const a1 = (await screen.findByText("A1 · Wall slides")).closest("div.mantine-Card-root");
    expect(
      screen.getByText("1 of 3 logged on this day. Rows left empty are not saved."),
    ).toBeInTheDocument();
    expect(screen.getByText("Prescription W2: 3×10")).toBeInTheDocument();
    expect(screen.getByText("B1 · 2×8")).toBeInTheDocument(); // also logged that day
    expect(screen.queryByRole("combobox", { name: "Exercise" })).not.toBeInTheDocument();
    await userEvent.type(within(a1 as HTMLElement).getByRole("textbox", { name: "Done" }), "3×8");
    const w1 = screen.getByText("W1 · Arm circles").closest("div.mantine-Card-root");
    const done = within(w1 as HTMLElement).getByRole("textbox", { name: "Done" });
    await userEvent.clear(done);
    await userEvent.type(done, "1×15");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved 2 rows.")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      new: [{ date: "2026-09-15", exercise: "A1", done: "3×8", effort: null }],
      changed: [
        {
          key: { date: "2026-09-15", exercise: "W1" },
          values: { done: "1×15" },
          expected: { done: "1×20" },
        },
      ],
    }); // A3, left empty, is skipped
  });

  it("names the row a refused save is about", async () => {
    batchApi(() =>
      Promise.resolve(
        Response.json(
          { detail: { message: "effort: 11 is more than 10", field: "effort", index: 0 } },
          { status: 422 },
        ),
      ),
    );
    renderApp("/log/prog/session_a?date=2026-09-15");
    const a1 = (await screen.findByText("A1 · Wall slides")).closest("div.mantine-Card-root");
    await userEvent.type(within(a1 as HTMLElement).getByRole("textbox", { name: "Done" }), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("A1 · Wall slides: effort: 11 is more than 10"),
    ).toBeInTheDocument();
    expect(screen.getByText("Not saved (nothing was written)")).toBeInTheDocument();
  });

  it("says when nothing changed", async () => {
    const calls = batchApi({ keys: [] });
    renderApp("/log/prog/session_a?date=2026-09-15");
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByText("Nothing changed.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

const DRILLS: ReferenceTableRows = {
  module: "prog",
  table: {
    name: "drills",
    label: "Drills",
    tab: "Drills",
    key: "id",
    display: null,
    columns: ["id", "retired"],
    week_columns: [],
    per_week_label: null,
  },
  rows: [],
  issues: [],
  as_of: null,
  offline: false,
};

describe("Log, a repeated form with kept fields (D-115)", () => {
  it("keeps the drill and level for the next try", async () => {
    const tries = "/api/modules/prog/drill_try";
    const calls = stubApi({
      "/api/health": HEALTH,
      "/api/modules": { modules: [PROGRAM], problems: [] },
      "/api/modules/prog/reference/drills": DRILLS,
      [tries]: records(0, { module: "prog", entity: "drill_try" }),
      [`POST ${tries}`]: written({ date: "2026-09-15", try_no: 1, drill: "D1", level: "L2" }),
    });
    renderApp("/log/prog/drill_tries?date=2026-09-15");
    expect(await screen.findByText(/no drill try yet/)).toBeInTheDocument();
    await userEvent.type(await screen.findByRole("textbox", { name: "Drill" }), "D1");
    await userEvent.click(screen.getByRole("combobox", { name: "Level" }));
    await userEvent.click(await screen.findByRole("option", { name: "L2", hidden: true }));
    await userEvent.type(screen.getByRole("textbox", { name: "Wobble" }), "3");
    await userEvent.click(screen.getByRole("button", { name: "Save and add another" }));
    expect(await screen.findByText("Saved Drill try 1. Here is the next one.")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      values: { date: "2026-09-15", drill: "D1", level: "L2", wobble: "3" },
    });
    expect(screen.getByRole("textbox", { name: "Drill" })).toHaveValue("D1");
    expect(screen.getByRole("textbox", { name: "Wobble" })).toHaveValue("");
  });
});
