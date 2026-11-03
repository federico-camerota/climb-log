// SPDX-License-Identifier: GPL-3.0-or-later
// The Log form's child rows: finger-strength sets (D-101). A fictional module shaped like
// modules/finger-strength.yaml (hang sets for Max hangs, curl sets for Finger curls).
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ModuleInfo } from "../api/client";
import { HEALTH, stubApi, written } from "../test/api";
import { renderApp } from "../test/render";

const FINGERS: ModuleInfo = {
  id: "fingers",
  name: "Finger strength",
  version: 1,
  kind: "journal",
  problems: [],
  module_schema: {
    scales: {
      rpe: { min: 1, max: 10, direction: "neutral" },
      s10: { min: 1, max: 10, direction: "higher_better" },
    },
    entities: {
      session: {
        label: "Session",
        key: ["date", "session_type"],
        sections: {
          wb_pre: { label: "Wellbeing · before", phase: "pre" },
          wb_post: { label: "Wellbeing · after", phase: "post" },
        },
        fields: {
          date: { type: "date", required: true },
          session_type: { type: "choice", choices: ["Max hangs", "Finger curls"], required: true },
          wb_mood_pre: { type: "scale", scale: "s10", section: "wb_pre" },
          session_rpe: { type: "scale", scale: "rpe", label: "Session effort", section: "wb_post" },
        },
      },
      hang_set: {
        label: "Hang set",
        key: ["date", "set_no"],
        parent: { entity: "session", key: ["date"], fixed: { session_type: "Max hangs" } },
        fields: {
          date: { type: "date", required: true },
          set_no: { type: "integer", min: 1, default: "next" },
          edge_mm: { type: "number", min: 5, max: 40 },
          added_kg: { type: "number" },
          rpe: { type: "scale", scale: "rpe" },
        },
      },
      curl_set: {
        label: "Curl set",
        key: ["date", "set_no"],
        parent: { entity: "session", key: ["date"], fixed: { session_type: "Finger curls" } },
        fields: {
          date: { type: "date", required: true },
          set_no: { type: "integer", min: 1, default: "next" },
          load_left_kg: { type: "number", min: 0, label: "Block left (kg)" },
        },
      },
    },
    forms: {
      session: {
        entity: "session",
        children: [
          { entity: "hang_set", repeat: true, copy_previous: ["edge_mm", "added_kg"] },
          { entity: "curl_set", repeat: true, copy_previous: ["load_left_kg"] },
        ],
      },
    },
  },
};

const BASE = "/api/modules/fingers";
const SESSION = `${BASE}/session/record?date=2026-10-30&session_type=Max+hangs`;
const HANGS = `${BASE}/hang_set`;
const SET = (n: number) => `${HANGS}/record?date=2026-10-30&set_no=${String(n)}`;
const FORM = "/log/fingers/session?date=2026-10-30";

const hang = (date: string, set_no: number, edge_mm: number, added_kg: number) => ({
  values: { date, set_no, edge_mm, added_kg, rpe: null },
  derived: {},
  rows: {},
});
const STORED = {
  module: "fingers",
  entity: "hang_set",
  as_of: null,
  offline: false,
  issues: [],
  records: [
    hang("2026-10-30", 2, 18, 12.5), // sheet order isn't set order
    hang("2026-10-30", 1, 20, 10),
    hang("2026-10-28", 1, 20, 7.5), // another session's
  ],
};
const NONE = { ...STORED, records: [] };

function api(extra: Record<string, object | ((body: unknown) => Promise<Response>)> = {}) {
  return stubApi({
    "/api/health": HEALTH,
    "/api/modules": { modules: [FINGERS], problems: [] },
    ...extra,
  });
}

/** The card of one set, by its name ("Hang set 1", "New hang set (3)"). */
function card(name: string) {
  const title = screen.getByText(name);
  const found = title.closest<HTMLElement>(".mantine-Card-root");
  if (found === null) throw new Error(`no card for ${name}`);
  return within(found);
}

describe("Log, finger-strength sets (D-101)", () => {
  it("asks for the session type first, then shows only its sets", async () => {
    api({ [HANGS]: STORED, [`${BASE}/curl_set`]: NONE });
    renderApp(FORM);
    expect(await screen.findByText("Pick the session type first.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("combobox", { name: "Session type" }));
    await userEvent.click(await screen.findByRole("option", { name: "Max hangs" }));

    expect(await screen.findByRole("heading", { name: "Hang sets" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Curl sets" })).not.toBeInTheDocument();
    const names = screen.getAllByText(/^Hang set \d$/).map((n) => n.textContent);
    expect(names).toEqual(["Hang set 1", "Hang set 2"]); // this day's, by set number
    expect(card("Hang set 2").getByRole("textbox", { name: "Added kg" })).toHaveValue("12.5");
  });

  it("puts the sets between the session's before and after groups", async () => {
    api({ [HANGS]: STORED });
    renderApp(`${FORM}&session_type=Max+hangs`);
    await screen.findByText("Hang set 2");
    const headings = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(headings).toEqual(["Wellbeing · before", "Hang sets", "Wellbeing · after"]);
  });

  it("copies the previous set's copy_previous fields into a new set", async () => {
    api({ [HANGS]: STORED });
    renderApp(`${FORM}&session_type=Max+hangs`);
    await screen.findByText("Hang set 2");
    await userEvent.click(screen.getByRole("button", { name: "+ hang set" }));
    const added = card("New hang set (3)");
    expect(added.getByRole("textbox", { name: "Edge mm" })).toHaveValue("18");
    expect(added.getByRole("textbox", { name: "Added kg" })).toHaveValue("12.5");
    expect(added.getByRole("combobox", { name: "Rpe" })).toHaveValue(""); // not copied
  });

  it("saves the sets after the session: removed, changed and new, then reads it again", async () => {
    const read = { date: "2026-10-30", session_type: "Max hangs", session_rpe: null };
    const calls = api({
      [SESSION]: written(read, { n_sets: 2 }),
      [HANGS]: STORED,
      [`DELETE ${SET(1)}`]: { deleted: true },
      [`PATCH ${SET(2)}`]: written({}),
      [`POST ${HANGS}`]: written({}),
    });
    renderApp(`${FORM}&session_type=Max+hangs`);
    await screen.findByText("Hang set 2");
    await userEvent.click(card("Hang set 1").getByRole("button", { name: "Remove" }));
    const second = card("Hang set 2").getByRole("textbox", { name: "Added kg" });
    await userEvent.clear(second);
    await userEvent.type(second, "15");
    await userEvent.click(screen.getByRole("button", { name: "+ hang set" }));
    await userEvent.click(screen.getByRole("button", { name: /^Save/ }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();

    const writes = calls.filter((c) => c.method !== "GET");
    expect(writes).toEqual([
      { method: "DELETE", path: SET(1), body: undefined },
      {
        method: "PATCH",
        path: SET(2),
        body: { values: { added_kg: "15" }, expected: { edge_mm: 18, added_kg: 12.5, rpe: null } },
      },
      {
        method: "POST",
        path: HANGS,
        body: { values: { date: "2026-10-30", edge_mm: "18", added_kg: "15", rpe: null } },
      }, // no set_no: the next number (D-050)
    ]);
    const reads = calls.filter((c) => c.method === "GET" && c.path === SESSION);
    expect(reads.length).toBeGreaterThan(1); // the set count changed: read the session again
  });

  it("creates a new session before its first set, and drops a blank new set", async () => {
    const session = { date: "2026-10-30", session_type: "Max hangs" };
    let created = false;
    const calls = api({
      [HANGS]: NONE,
      [SESSION]: () =>
        Promise.resolve(
          created
            ? Response.json(written(session, { n_sets: 1 }))
            : Response.json({ detail: "Not Found" }, { status: 404 }),
        ),
      [`POST ${BASE}/session`]: () => {
        created = true;
        return Promise.resolve(Response.json(written(session)));
      },
      [`POST ${HANGS}`]: written({}),
    });
    renderApp(`${FORM}&session_type=Max+hangs`);
    expect(await screen.findByText("None yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "+ hang set" }));
    await userEvent.type(card("New hang set (1)").getByRole("textbox", { name: "Edge mm" }), "20");
    await userEvent.click(screen.getByRole("button", { name: "+ hang set" }));
    await userEvent.clear(card("New hang set (2)").getByRole("textbox", { name: "Edge mm" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Saved");
    const writes = calls.filter((c) => c.method === "POST").map((c) => c.path);
    expect(writes).toEqual([`${BASE}/session`, HANGS]);
  });

  it("checks a set's numbers before saving anything", async () => {
    const calls = api({ [HANGS]: NONE });
    renderApp(`${FORM}&session_type=Max+hangs`);
    await screen.findByText("None yet.");
    await userEvent.click(screen.getByRole("button", { name: "+ hang set" }));
    await userEvent.type(card("New hang set (1)").getByRole("textbox", { name: "Edge mm" }), "2");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/at least 5/i)).toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });
});
