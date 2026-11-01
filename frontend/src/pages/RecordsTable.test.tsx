// SPDX-License-Identifier: GPL-3.0-or-later
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DIARY, HEALTH, stubApi } from "../test/api";
import { renderApp } from "../test/render";

const PAGE = "/records/diary/session";

function session(date: string, n: number, values: object, derived: object, row: number) {
  return {
    values: { date, session_no: n, ...values },
    derived,
    rows: { Session: row, Wellbeing: row },
  };
}

const RECORDS = {
  module: "diary",
  entity: "session",
  records: [
    session(
      "2026-10-20",
      1,
      { venue: "[ESEMPIO] Palestra Nord", notes: "Più riposo, così" },
      { wb_status: "GOOD" },
      3,
    ),
    session("2026-10-28", 1, { venue: "Falesia", notes: "dita stanche" }, { wb_status: "LOW" }, 4),
    session("2026-10-28", 2, { venue: "Home wall", wb_mood_pre: null }, { wb_status: null }, 5),
  ],
  issues: [
    { tab: "Wellbeing", row: 5, field: "wb_mood_pre", message: "'tanto' is not a number" },
    { tab: "Wellbeing", row: 9, field: null, message: "no Session row" }, // an orphan
  ],
  as_of: "2026-10-30T09:05:00",
  offline: false,
};

function api() {
  return stubApi({
    "/api/health": HEALTH,
    "/api/modules": { modules: [DIARY], problems: [] },
    "/api/modules/diary/session": RECORDS,
  });
}

function bodyRows(): string[][] {
  const table = screen.getByRole("table", { name: "" });
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );
}

afterEach(() => {
  localStorage.clear();
});

describe("Records table", () => {
  it("shows the key, scores and statuses, newest first", async () => {
    api();
    renderApp(PAGE);
    expect(await screen.findByRole("columnheader", { name: /wb status/ })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /Venue/ })).not.toBeInTheDocument();
    expect(bodyRows().map((r) => r.slice(0, 2))).toEqual([
      ["28/10/2026", "2"],
      ["28/10/2026", "1"],
      ["20/10/2026", "1"],
    ]);
    expect(screen.getAllByText("LOW")[0]).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Matched in" })).not.toBeInTheDocument();
  });

  it("finds a session by a word of its notes, accents ignored, or by its date", async () => {
    api();
    renderApp(PAGE);
    const search = await screen.findByRole("textbox", { name: "Search" });
    await userEvent.type(search, "cosi");
    expect(bodyRows().map((r) => r[0])).toEqual(["20/10/2026"]);
    // the notes aren't shown: the row says where it matched
    expect(screen.getByRole("columnheader", { name: "Matched in" })).toBeInTheDocument();
    expect(bodyRows()[0]?.at(-1)).toBe("Notes");
    await userEvent.clear(search);
    await userEvent.type(search, "28/10");
    expect(bodyRows()).toHaveLength(2);
    expect(screen.getByText("2 of 3 shown")).toBeInTheDocument();
  });

  it("marks a data issue in its cell and lists every issue", async () => {
    api();
    renderApp(PAGE);
    await userEvent.click(await screen.findByPlaceholderText("Add a column"));
    await userEvent.click(await screen.findByRole("option", { name: "Mood", hidden: true }));
    await userEvent.click(screen.getByRole("switch", { name: "Only records with data issues" }));
    expect(bodyRows()).toHaveLength(1);
    expect(screen.getByLabelText("Data issue: 'tanto' is not a number")).toBeInTheDocument();
    await userEvent.click(screen.getByText("2 data issues"));
    expect(screen.getByText("no Session row")).toBeInTheDocument(); // the orphan too
  });

  it("sorts by a column and remembers the columns picked", async () => {
    api();
    const first = renderApp(PAGE);
    await userEvent.click(await screen.findByRole("columnheader", { name: /Date/ }));
    expect(bodyRows()[0]?.[0]).toBe("20/10/2026");
    await userEvent.click(screen.getByPlaceholderText("Add a column"));
    await userEvent.click(await screen.findByRole("option", { name: "Venue", hidden: true }));
    expect(screen.getByRole("columnheader", { name: /Venue/ })).toBeInTheDocument();
    first.unmount();
    renderApp(PAGE);
    expect(await screen.findByRole("columnheader", { name: /Venue/ })).toBeInTheDocument();
  });

  it("exports the table as shown, for an Italian spreadsheet", async () => {
    api();
    const files: Blob[] = [];
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: (blob: Blob) => {
        files.push(blob);
        return "blob:fake";
      },
      revokeObjectURL: () => undefined,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderApp(PAGE);
    await userEvent.type(await screen.findByRole("textbox", { name: "Search" }), "falesia");
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    const text = await files[0]?.text();
    const lines = text?.replace(String.fromCharCode(0xfeff), "").split("\r\n");
    expect(lines?.[0]?.startsWith("Date;Session #;")).toBe(true);
    expect(lines?.[0]).not.toContain("Matched in"); // shown while searching, not exported
    expect(lines?.[1]?.startsWith("28/10/2026;1;")).toBe(true);
    expect(lines).toHaveLength(3); // the header, one record, the last line break
  });
});
