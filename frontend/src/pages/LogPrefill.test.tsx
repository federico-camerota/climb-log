// SPDX-License-Identifier: GPL-3.0-or-later
// The Log form's prefilled fields (D-114): a fictional check-in whose activity and grade come
// from the same day's diary session.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ModuleInfo, Prefill } from "../api/client";
import { HEALTH, records, stubApi, written } from "../test/api";
import { renderApp } from "../test/render";

const REHAB: ModuleInfo = {
  id: "rehab",
  name: "Rehab",
  version: 1,
  kind: "journal",
  problems: [],
  notes: [],
  module_schema: {
    entities: {
      checkin: {
        label: "Check-in",
        key: ["date"],
        fields: {
          date: { type: "date", required: true },
          activity: {
            type: "choice",
            choices: ["Gym climbing", "Board"],
            from: "diary.session.place+kind",
          },
          grade: { type: "grade", systems: ["french"], from: "diary.session.grade" },
          pain: { type: "integer", min: 0, max: 10 },
        },
      },
    },
    forms: { checkin: { entity: "checkin" } },
  },
};

const BASE = "/api/modules/rehab/checkin";
const FORM = "/log/rehab/checkin?date=2026-11-18";
const PREFILL = `${BASE}/prefill?date=2026-11-18`;
const RECORD = `${BASE}/record?date=2026-11-18`;

const source = (n: number, values: Record<string, unknown>, label: string) => ({
  module: "diary",
  entity: "session",
  label,
  key: { date: "2026-11-18", session_no: n },
  values,
});
const ONE: Prefill = {
  sources: [source(1, { activity: "Gym climbing", grade: "6c" }, "Session 1 · Gym climbing · 6c")],
  notes: [],
};
const TWO: Prefill = {
  sources: [
    source(1, { activity: "Board" }, "Session 1 · Board"),
    source(2, { activity: "Gym climbing", grade: "7a" }, "Session 2 · Gym climbing · 7a"),
  ],
  notes: ["checkin.minutes: not prefilled (no module 'diary' loaded)"],
};

function api(prefill: Prefill, extra: Record<string, object> = {}) {
  return stubApi({
    "/api/health": HEALTH,
    "/api/modules": { modules: [REHAB], problems: [] },
    [BASE]: records(0, { module: "rehab", entity: "checkin" }),
    [PREFILL]: prefill,
    [`POST ${BASE}`]: written({ date: "2026-11-18" }),
    ...extra,
  });
}

describe("Log, prefilled fields (D-114)", () => {
  it("starts a new record with the one session's values, editable", async () => {
    const calls = api(ONE);
    renderApp(FORM);
    expect(
      await screen.findByText("Prefilled from diary · Session 1 · Gym climbing · 6c (editable)"),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Grade" })).toHaveValue("6c");
    await userEvent.clear(screen.getByRole("textbox", { name: "Grade" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Grade" }), "6b+");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      values: { date: "2026-11-18", activity: "Gym climbing", grade: "6b+" },
    });
  });

  it("asks which session when there are two", async () => {
    api(TWO);
    renderApp(FORM);
    const pick = await screen.findByRole("combobox", { name: "Prefill from" });
    expect(screen.getByText("2 records that day: pick one, or leave blank")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Grade" })).toHaveValue(""); // nothing yet
    expect(screen.getByText(/no module 'diary' loaded/)).toBeInTheDocument();
    await userEvent.click(pick);
    await userEvent.click(
      await screen.findByRole("option", {
        name: "diary · Session 2 · Gym climbing · 7a",
        hidden: true,
      }),
    );
    expect(screen.getByRole("textbox", { name: "Grade" })).toHaveValue("7a");
    expect(
      screen.getByText("Prefilled from diary · Session 2 · Gym climbing · 7a (editable)"),
    ).toBeInTheDocument();
  });

  it("fills only the blank fields of a record typed in the sheet", async () => {
    api(ONE, { [RECORD]: written({ date: "2026-11-18", grade: "6a", pain: 2 }) });
    renderApp(FORM);
    const pick = await screen.findByRole("combobox", { name: "Fill the blank fields from" });
    expect(screen.getByRole("textbox", { name: "Grade" })).toHaveValue("6a");
    await userEvent.click(pick);
    await userEvent.click(
      await screen.findByRole("option", {
        name: "diary · Session 1 · Gym climbing · 6c",
        hidden: true,
      }),
    );
    expect(screen.getByRole("textbox", { name: "Grade" })).toHaveValue("6a"); // kept
    expect(screen.getByRole("combobox", { name: "Activity" })).toHaveValue("Gym climbing");
  });
});
