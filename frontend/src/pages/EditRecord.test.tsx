// SPDX-License-Identifier: GPL-3.0-or-later
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { DIARY, HEALTH, stubApi, written } from "../test/api";
import { renderApp } from "../test/render";

// Fixing records from the Records page (D-082). Fictional data only.
const PAGE = "/records/diary/session";
const SESSIONS = "/api/modules/diary/session";
const RECORD = `${SESSIONS}/record?date=2026-10-28&session_no=2`;
const VALUES = { date: "2026-10-28", session_no: 2, venue: "[ESEMPIO] Home wall", minutes: null };
const RECORDS = {
  module: "diary",
  entity: "session",
  records: [{ values: VALUES, derived: {}, rows: { Session: 5, Wellbeing: 5 } }],
  issues: [
    {
      tab: "Session",
      row: 5,
      field: "minutes",
      message: "'boh' is not a duration",
      kind: "value",
      value: "boh",
    },
    {
      tab: "Wellbeing",
      row: 5,
      field: "wb_mood_pre",
      message: "'tanto' is not a number",
      kind: "value",
      value: "tanto",
    },
    {
      tab: "Session",
      row: 8,
      field: "date",
      message: "no date: the row is left out",
      kind: "left_out",
    },
    {
      tab: "Wellbeing",
      row: 9,
      field: null,
      message: "no Session row for date 2026-10-29",
      kind: "orphan",
    },
    { tab: "Session", row: null, field: "notes", message: "the column is missing", kind: "column" },
  ],
  as_of: "2026-10-30T09:05:00",
  offline: false,
};

function api(extra: Record<string, object | ((body: unknown) => Promise<Response>)> = {}) {
  return stubApi({
    "/api/health": HEALTH,
    "/api/modules": { modules: [DIARY], problems: [] },
    [SESSIONS]: RECORDS,
    [RECORD]: written(VALUES),
    ...extra,
  });
}

function empty() {
  return () => Promise.resolve(new Response(null, { status: 204 }));
}

async function openRecord() {
  const row = await screen.findByRole("row", { name: /28\/10\/2026/ });
  await userEvent.click(row);
  return screen.findByRole("dialog", { name: "Session · 28/10/2026 · Session # 2" });
}

afterEach(() => {
  localStorage.clear();
});

describe("Editing a record", () => {
  it("opens the whole record, every section, with its issues under their fields", async () => {
    api();
    renderApp(PAGE);
    const drawer = await openRecord();
    expect(await within(drawer).findByRole("textbox", { name: "Venue" })).toHaveValue(
      "[ESEMPIO] Home wall",
    );
    expect(within(drawer).getByRole("combobox", { name: "Fatigue ↓" })).toBeInTheDocument(); // post
    // a bad value in a text input is shown as typed; in a dropdown, its message says it
    expect(within(drawer).getByRole("textbox", { name: "Minutes" })).toHaveValue("boh");
    expect(within(drawer).getByText("'boh' is not a duration")).toBeInTheDocument();
    expect(within(drawer).getByText("'tanto' is not a number")).toBeInTheDocument();
  });

  it("saves a fix with the values as read", async () => {
    const calls = api({ [`PATCH ${RECORD}`]: written({ ...VALUES, minutes: 90 }) });
    renderApp(PAGE);
    const drawer = await openRecord();
    const minutes = await within(drawer).findByRole("textbox", { name: "Minutes" });
    await userEvent.clear(minutes);
    await userEvent.type(minutes, "1:30");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save changes" }));
    expect(await within(drawer).findByText("Saved")).toBeInTheDocument();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toMatchObject({ values: { minutes: "1:30" } });
    expect((patch?.body as { expected: object }).expected).toMatchObject({ minutes: null });
  });

  it("deletes the record after a confirmation", async () => {
    const calls = api({ [`DELETE ${RECORD}`]: empty() });
    renderApp(PAGE);
    const drawer = await openRecord();
    await userEvent.click(await within(drawer).findByRole("button", { name: "Delete…" }));
    const confirm = await screen.findByRole("dialog", { name: /^Delete Session/ });
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete" }));
    await screen.findByText("1 record · 5 data issues");
    expect(calls.some((c) => c.method === "DELETE" && c.path === RECORD)).toBe(true);
  });
});

describe("Fixing rows that are no record", () => {
  it("gives an orphan section row its session", async () => {
    const adopt = `${SESSIONS}/row/record?tab=Wellbeing&row=9`;
    const calls = api({ [`POST ${adopt}`]: written(VALUES) });
    renderApp(PAGE);
    await userEvent.click(await screen.findByText("5 data issues"));
    await userEvent.click(await screen.findByRole("button", { name: "Create the session" }));
    await screen.findByText("1 record · 5 data issues"); // refetched
    expect(calls.some((c) => c.method === "POST" && c.path === adopt)).toBe(true);
  });

  it("deletes a left-out row after a confirmation, and offers nothing for a whole column", async () => {
    const row = `${SESSIONS}/row?tab=Session&row=8`;
    const calls = api({ [`DELETE ${row}`]: empty() });
    renderApp(PAGE);
    await userEvent.click(await screen.findByText("5 data issues"));
    // left out, orphan
    expect(await screen.findAllByRole("button", { name: "Delete row" })).toHaveLength(2);
    await userEvent.click(screen.getAllByRole("button", { name: "Delete row" })[0] as HTMLElement);
    const confirm = await screen.findByRole("dialog", { name: "Delete Session row 8?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete row" }));
    await screen.findByText("1 record · 5 data issues");
    expect(calls.some((c) => c.method === "DELETE" && c.path === row)).toBe(true);
  });
});
