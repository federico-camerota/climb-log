// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DIARY, HEALTH, MODULES, stubApi, written } from "../test/api";
import { renderApp } from "../test/render";

const LIST = { modules: [DIARY], problems: [] };
const SESSION = "/api/modules/diary/session";
const RECORD = `${SESSION}/record?date=2026-10-30&session_no=1`;
const PRE = "/log/diary/pre_session?date=2026-10-30";
const READ = { date: "2026-10-30", session_no: 1, venue: "[ESEMPIO] Palestra", wb_mood_pre: 7 };

function api(extra: Record<string, object | ((body: unknown) => Promise<Response>)> = {}) {
  return stubApi({ "/api/health": HEALTH, "/api/modules": LIST, ...extra });
}

/** Opens a scale's dropdown and picks a value. */
async function pick(label: string, value: string) {
  await userEvent.click(screen.getByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: value }));
}

function failing(status: number, detail: object) {
  return () => Promise.resolve(Response.json({ detail }, { status }));
}

describe("Log", () => {
  it("opens the module's first form for today", async () => {
    api();
    const { router } = renderApp("/log");
    expect(await screen.findByRole("textbox", { name: "Venue" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/log/diary/pre_session");
    expect(screen.getByRole("heading", { name: "Wellbeing · before" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Notes" })).not.toBeInTheDocument(); // post
  });

  it("creates the session at pre and shows its statuses", async () => {
    const calls = api({
      [`POST ${SESSION}`]: written(READ, { wb_status: "GOOD", log_check: "Missing: Feel" }),
    });
    renderApp(PRE);
    await userEvent.type(
      await screen.findByRole("textbox", { name: "Venue" }),
      "[[ESEMPIO] Più su",
    );
    await userEvent.type(screen.getByRole("textbox", { name: "Sleep hours" }), "7,5");
    await pick("Mood", "7");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("wb status: GOOD")).toBeInTheDocument();
    expect(screen.getByText("log check: Missing: Feel")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      values: {
        date: "2026-10-30",
        session_no: "1",
        venue: "[ESEMPIO] Più su",
        wb_sleep_hours: "7,5",
        wb_mood_pre: 7,
      },
    });
  });

  it("completes it at post: only what changed, with the values as read", async () => {
    const calls = api({
      [RECORD]: written(READ),
      [`PATCH ${RECORD}`]: written({ ...READ, wb_fatigue_post: 3 }),
    });
    renderApp("/log/diary/post_session?date=2026-10-30");
    await screen.findByRole("combobox", { name: "Fatigue ↓" });
    await pick("Fatigue ↓", "3");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({
      values: { wb_fatigue_post: 3 },
      expected: { wb_fatigue_post: null, minutes: null, notes: null },
    });
  });

  it("starts scales blank, with the best value first", async () => {
    api();
    renderApp("/log/diary/post_session?date=2026-10-30");
    const fatigue = await screen.findByRole("combobox", { name: "Fatigue ↓" });
    expect(fatigue).toHaveValue("");
    await userEvent.click(fatigue);
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "1best",
      "2",
      "3",
      "4",
      "5",
      "6",
      "7",
      "8",
      "9",
      "10",
    ]);
  });

  it("lists a higher-is-better scale from 10 down", async () => {
    api();
    renderApp(PRE);
    await userEvent.click(await screen.findByRole("combobox", { name: "Mood" }));
    const options = await screen.findAllByRole("option");
    expect(options[0]).toHaveTextContent("10best");
    expect(options.at(-1)).toHaveTextContent("1");
  });

  it("shows what it read, and a cleared scale picked again is unchanged", async () => {
    const calls = api({ [RECORD]: written(READ) });
    renderApp(PRE);
    expect(await screen.findByDisplayValue("[ESEMPIO] Palestra")).toBeInTheDocument();
    const mood = screen.getByRole("combobox", { name: "Mood" });
    expect(mood).toHaveValue("7");
    await pick("Mood", "7"); // the chosen value again clears it (the × does too)
    expect(mood).toHaveValue("");
    await pick("Mood", "7");
    expect(mood).toHaveValue("7");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Nothing changed.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("checks numbers before sending", async () => {
    const calls = api();
    renderApp(PRE);
    await userEvent.type(await screen.findByRole("textbox", { name: "Sleep hours" }), "tanto");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Not a number (e.g. 7,5)")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the API's problem under its field", async () => {
    const problem = { message: "minutes: 'tanto' is not a duration", field: "minutes" };
    api({ [`POST ${SESSION}`]: failing(422, problem) });
    renderApp("/log/diary/post_session?date=2026-10-30");
    await userEvent.type(await screen.findByRole("textbox", { name: "Minutes" }), "tanto");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("minutes: 'tanto' is not a duration")).toBeInTheDocument();
  });

  it("shows every problem the API finds, each under its field", async () => {
    const problems = [
      { field: "minutes", message: "minutes: 'tanto' is not a duration" },
      { field: "notes", message: "notes: too long" },
    ];
    api({ [`POST ${SESSION}`]: failing(422, { ...problems[0], problems }) });
    renderApp("/log/diary/post_session?date=2026-10-30");
    await userEvent.type(await screen.findByRole("textbox", { name: "Minutes" }), "tanto");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("minutes: 'tanto' is not a duration")).toBeInTheDocument();
    expect(screen.getByText("notes: too long")).toBeInTheDocument();
    expect(screen.queryByText("Not saved")).not.toBeInTheDocument();
  });

  it("brings a draft back with its errors, until the field is changed or discarded", async () => {
    const problems = [
      { field: "minutes", message: "minutes: 'tanto' is not a duration" },
      { field: "notes", message: "notes: too long" },
    ];
    api({ [`POST ${SESSION}`]: failing(422, { ...problems[0], problems }) });
    const first = renderApp("/log/diary/post_session?date=2026-10-30");
    await userEvent.type(await screen.findByRole("textbox", { name: "Minutes" }), "tanto");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("notes: too long");
    first.unmount();

    renderApp("/log/diary/post_session?date=2026-10-30");
    expect(await screen.findByText("Unsaved changes restored")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Minutes" })).toHaveValue("tanto");
    expect(screen.getByText("minutes: 'tanto' is not a duration")).toBeInTheDocument();
    expect(screen.getByText("notes: too long")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Minutes" }), "!");
    expect(screen.queryByText("minutes: 'tanto' is not a duration")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Discard them" }));
    expect(screen.queryByText("notes: too long")).not.toBeInTheDocument();
  });

  it("puts a problem on a field the form doesn't show in the alert", async () => {
    const problem = { field: "venue", message: "venue: bad" };
    api({ [`POST ${SESSION}`]: failing(422, { ...problem, problems: [problem] }) });
    renderApp("/log/diary/post_session?date=2026-10-30");
    await userEvent.type(await screen.findByRole("textbox", { name: "Minutes" }), "90");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Not saved")).toBeInTheDocument();
    expect(screen.getByText("venue: bad")).toBeInTheDocument();
  });

  it("says when the sheet changed since the form was opened, and keeps the changes", async () => {
    const changed = { message: "venue has changed since it was read (now 'Altrove')", field: null };
    const calls = api({ [RECORD]: written(READ), [`PATCH ${RECORD}`]: failing(409, changed) });
    renderApp(PRE);
    const venue = await screen.findByRole("textbox", { name: "Venue" });
    await userEvent.type(venue, " nord"); // types after what was read
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("Changed in the sheet since you opened the form"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Reload the record/ }));
    expect(calls.filter((c) => c.path === RECORD && c.method === "GET")).toHaveLength(2);
  });

  it("restores unsaved changes, and discards them on request", async () => {
    api();
    const first = renderApp(PRE);
    await userEvent.type(await screen.findByRole("textbox", { name: "Venue" }), "[[ESEMPIO] bozza");
    first.unmount();

    renderApp(PRE);
    expect(await screen.findByText("Unsaved changes restored")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Venue" })).toHaveValue("[ESEMPIO] bozza");
    await userEvent.click(screen.getByRole("button", { name: "Discard them" }));
    expect(screen.getByRole("textbox", { name: "Venue" })).toHaveValue("");
    expect(screen.queryByText("Unsaved changes restored")).not.toBeInTheDocument();
  });

  it("switches forms and keeps the day", async () => {
    api();
    const { router } = renderApp(PRE);
    await screen.findByRole("textbox", { name: "Venue" });
    await userEvent.click(screen.getByText("Rest day"));
    expect(router.state.location.pathname).toBe("/log/diary/rest_day");
    expect(router.state.location.search).toBe("?date=2026-10-30");
    expect(await screen.findByRole("combobox", { name: "Mood" })).toBeInTheDocument();
  });

  it("says when a module has no forms", async () => {
    api({ "/api/modules": MODULES });
    renderApp("/log/journal");
    expect(await screen.findByText("Module 'journal' has no forms.")).toBeInTheDocument();
  });
});
