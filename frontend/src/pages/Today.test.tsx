// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { HEALTH, stubApi } from "../test/api";
import { renderApp } from "../test/render";

const DAY = "2026-10-30";

function day(items: object[], extra: object = {}) {
  return {
    date: DAY,
    modules: [
      {
        module: "journal",
        name: "Climbing journal",
        items,
        any_one: false,
        last: DAY,
        last_label: "Session",
        days_since: 0,
        week: null,
        notes: [],
        as_of: "2026-10-30T09:05:00",
        offline: false,
        ...extra,
      },
    ],
    problems: [],
  };
}

const ADVICE = {
  date: DAY,
  items: [
    {
      module: "journal",
      label: "Suggested next session",
      headline: "RECOVER",
      message: "rest day or easy technical climbing.",
      text: "RECOVER — rest day or easy technical climbing.",
      reasons: [
        { name: "last_session", label: "Last session", value: "2026-10-28" },
        { name: "latest_status", label: "Latest overall status", value: "LOW" },
        { name: "low_sessions", label: "LOW sessions in the last 14 days", value: 1 },
        { name: "weakest_area", label: "Weakest area (latest session)", value: "Physical · 3.3" },
      ],
      as_of: null,
      offline: false,
    },
  ],
  problems: [],
};

function api(today: object) {
  return stubApi({
    "/api/health": HEALTH,
    [`/api/today?date=${DAY}`]: today,
    [`/api/recommendation?date=${DAY}`]: ADVICE,
  });
}

describe("Today", () => {
  it("gives the recommendation with its reasons", async () => {
    api(day([]));
    renderApp(`/?date=${DAY}`);
    expect(await screen.findByText("RECOVER")).toBeInTheDocument();
    expect(screen.getByText("rest day or easy technical climbing.")).toBeInTheDocument();
    expect(screen.getByText("Last session: 28/10/2026")).toBeInTheDocument();
    expect(screen.getByText("LOW sessions in the last 14 days: 1")).toBeInTheDocument();
    expect(screen.getByText("Weakest area (latest session): Physical · 3.3")).toBeInTheDocument();
  });

  it("shows this week's training load", async () => {
    const week = {
      label: "Training load",
      load: 1005,
      sessions: 2,
      without_load: 1,
      acwr: 1.12,
      zones: [0.8, 1.3, 1.5],
      others: [{ label: "Finger training (sets x effort)", load: 48.5, without: 0 }],
    };
    api(day([], { week }));
    renderApp(`/?date=${DAY}`);
    const line = await screen.findByText(/^\(from Monday\)/);
    expect(line.parentElement).toHaveTextContent(
      "This week (from Monday) · Training load: 1005 · 2 sessions · 1 without load · " +
        "ratio 1,1 (in the usual range) · Finger training (sets x effort): 48,5",
    );
  });

  it("offers a session or a rest day when nothing is logged", async () => {
    const key = { date: DAY };
    api(
      day(
        [
          { form: "pre_session", label: "Pre session", key, status: "missing", missing: [] },
          { form: "rest_day", label: "Rest day", key, status: "missing", missing: [] },
        ],
        { any_one: true, last: "2026-10-27", days_since: 3 },
      ),
    );
    renderApp(`/?date=${DAY}`);
    expect(await screen.findByText("Nothing logged yet: one of these.")).toBeInTheDocument();
    expect(screen.getByText("Last session: 27/10/2026 · 3 days ago")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Fill in" });
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      `/log/journal/pre_session?date=${DAY}`,
      `/log/journal/rest_day?date=${DAY}`,
    ]);
  });

  it("lists each session's forms with what is missing, and links to them", async () => {
    const one = { date: DAY, session_no: 1 };
    const two = { date: DAY, session_no: 2 };
    api(
      day([
        { form: "pre_session", label: "Pre session", key: one, status: "done", missing: [] },
        {
          form: "post_session",
          label: "Post session",
          key: one,
          status: "partial",
          missing: ["Session feel", "Wins & reflect"],
          log_check: "Missing: Feel, Reflect",
        },
        { form: "pre_session", label: "Pre session", key: two, status: "missing", missing: [] },
      ]),
    );
    const { router } = renderApp(`/?date=${DAY}`);
    expect(await screen.findByText("Missing: Session feel, Wins & reflect")).toBeInTheDocument();
    expect(screen.getByText("Log check: Missing: Feel, Reflect")).toBeInTheDocument();
    expect(screen.getByText("Pre session · session 2")).toBeInTheDocument();
    expect(screen.getByText("Last session: 30/10/2026 · today")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Complete" }));
    expect(router.state.location.pathname).toBe("/log/journal/post_session");
    expect(router.state.location.search).toBe(`?date=${DAY}&session_no=1`);
  });

  it("offers another record of a repeated form, without a status", async () => {
    api(
      day([
        {
          form: "meal",
          label: "Meal",
          key: { date: DAY, meal_no: 1 },
          status: "done",
          missing: [],
        },
        { form: "meal", label: "Meal", key: { date: DAY }, status: "another", missing: [] },
      ]),
    );
    const { router } = renderApp(`/?date=${DAY}`);
    const add = await screen.findByRole("link", { name: "Add another" });
    expect(screen.getAllByText("done")).toHaveLength(1);
    expect(screen.queryByText("another")).not.toBeInTheDocument();
    await userEvent.click(add);
    expect(router.state.location.pathname).toBe("/log/journal/meal");
    expect(router.state.location.search).toBe(`?date=${DAY}`);
  });

  it("says when a module can't be read", async () => {
    api({ date: DAY, modules: [], problems: ["journal: workbook not found"] });
    renderApp(`/?date=${DAY}`);
    expect(await screen.findByText("journal: workbook not found")).toBeInTheDocument();
  });
});
