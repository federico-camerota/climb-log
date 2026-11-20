// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { RunList } from "../api/client";
import { HEALTH, module, stubApi } from "../test/api";
import { renderApp } from "../test/render";

describe("Settings", () => {
  it("lists each module, with the problems of one that doesn't load", async () => {
    stubApi({
      "/api/health": HEALTH,
      "/api/modules": {
        modules: [
          module("journal", "Climbing journal", ["session"]),
          { id: "broken", problems: ["broken.yaml:3:1: unknown key 'feilds'"], notes: [] },
        ],
        problems: ["modules.old: the definition file doesn't exist"],
      },
    });
    renderApp("/settings");
    expect(await screen.findByText("Climbing journal")).toBeInTheDocument();
    expect(screen.getByText("journal · version 1 · journal")).toBeInTheDocument();
    expect(screen.getByText("loaded")).toBeInTheDocument();
    expect(screen.getByText("doesn't load")).toBeInTheDocument();
    expect(screen.getByText("broken.yaml:3:1: unknown key 'feilds'")).toBeInTheDocument();
    expect(screen.getByText("modules.old: the definition file doesn't exist")).toBeInTheDocument();
  });

  it("says when the app config has no modules", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": { modules: [], problems: [] } });
    renderApp("/settings");
    expect(await screen.findByText("No modules in the app config.")).toBeInTheDocument();
  });

  it("shows a program's runs and starts a new one", async () => {
    const runs: RunList = {
      module: "shoulder",
      weeks: 12,
      runs: [{ number: 1, start_week: "2026-W42", start: "2026-10-12", end: "2027-01-03" }],
      current: { run: 1, week: 6, phase: "Block 2", light_week: false },
      next_week: "2026-W47",
      issues: [],
      as_of: null,
      offline: false,
    };
    const started: RunList = {
      ...runs,
      runs: [
        ...runs.runs,
        { number: 2, start_week: "2026-W48", start: "2026-11-23", end: "2027-02-14" },
      ],
      current: { run: 2, week: 1, phase: "Block 1", light_week: false },
    };
    let posted = false;
    const calls = stubApi({
      "/api/health": HEALTH,
      "/api/modules": {
        modules: [{ ...module("shoulder", "Shoulder program", ["checkin"]), kind: "program" }],
        problems: [],
      },
      // after the POST the server reads the new run back, as the app asks again
      "/api/modules/shoulder/runs": () => Promise.resolve(Response.json(posted ? started : runs)),
      "POST /api/modules/shoulder/runs": () => {
        posted = true;
        return Promise.resolve(Response.json(started));
      },
    });
    renderApp("/settings");
    expect(await screen.findByText("Today: run 1, week 6 · Block 2")).toBeInTheDocument();
    expect(screen.getByText("12/10/2026")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start a new run…" }));
    const input = await screen.findByRole("textbox", { name: /Start week/ });
    expect(input).toHaveValue("2026-W47");
    await userEvent.clear(input);
    await userEvent.type(input, "2026-W4x");
    expect(screen.getByText("Not a week like 2026-W47")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start run 2" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "2026-W48");
    expect(screen.getByText("Week 1 of run 2 starts on Monday 23/11/2026.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start run 2" }));
    expect(await screen.findByText("Today: run 2, week 1 · Block 1")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ start_week: "2026-W48" });
  });
});
