// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { HEALTH, MODULES, records, stubApi } from "../test/api";
import { renderApp } from "../test/render";

const API = {
  "/api/health": HEALTH,
  "/api/modules": MODULES,
  "/api/modules/journal/session": records(3),
  "/api/modules/journal/rest_day": records(1, { entity: "rest_day" }),
  "/api/modules/fingers/sessions": records(0, { module: "fingers", entity: "sessions" }),
};

describe("Records", () => {
  it("takes the first module and entity when the URL names none", async () => {
    stubApi(API);
    const { router } = renderApp("/records");
    expect(await screen.findByText("3 records · 0 data issues")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/records/journal/session");
    expect(screen.getByText("As of 30/10/2026 09:05")).toBeInTheDocument();
  });

  it("picks another entity and module through the URL", async () => {
    stubApi(API);
    const { router } = renderApp("/records/journal/session");
    await screen.findByText("3 records · 0 data issues");
    await userEvent.click(screen.getByRole("combobox", { name: "Entity" }));
    await userEvent.click(await screen.findByRole("option", { name: "rest_day", hidden: true }));
    expect(await screen.findByText("1 record · 0 data issues")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/records/journal/rest_day");
    await userEvent.click(screen.getByRole("combobox", { name: "Module" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Finger strength", hidden: true }),
    );
    expect(await screen.findByText("0 records · 0 data issues")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/records/fingers/sessions");
  });

  it("warns when the data is an offline snapshot, and counts the issues", async () => {
    const issue = {
      tab: "Wellbeing",
      row: 7,
      field: null,
      message: "no Session row",
      kind: "orphan",
    };
    stubApi({
      ...API,
      "/api/modules/journal/session": records(2, { offline: true, issues: [issue] }),
    });
    renderApp("/records/journal/session");
    expect(await screen.findByText("Offline · read-only")).toBeInTheDocument();
    expect(screen.getByText("2 records · 1 data issue")).toBeInTheDocument();
  });

  it("leaves out when the data was read if the API doesn't say", async () => {
    stubApi({
      ...API,
      "/api/modules/journal/session": records(2, { offline: true, as_of: null }),
    });
    renderApp("/records/journal/session");
    expect(
      await screen.findByText("The workbook can't be reached: this is the last snapshot."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/As of/)).not.toBeInTheDocument();
  });

  it("shows the API's message when the records can't be read", async () => {
    stubApi({
      ...API,
      "/api/modules/journal/session": () =>
        Promise.resolve(Response.json({ detail: "cannot reach Google" }, { status: 503 })),
    });
    renderApp("/records/journal/session");
    expect(await screen.findByText("cannot reach Google")).toBeInTheDocument();
  });

  it("says so for an unknown module", async () => {
    stubApi(API);
    renderApp("/records/shoulder");
    expect(
      await screen.findByText("No module 'shoulder' is ready: see Settings."),
    ).toBeInTheDocument();
  });

  it("says so for an unknown entity", async () => {
    stubApi(API);
    renderApp("/records/journal/falls");
    expect(await screen.findByText("Module 'journal' has no entity 'falls'.")).toBeInTheDocument();
  });

  it("explains when no module is ready", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": { modules: [], problems: [] } });
    renderApp("/records");
    expect(await screen.findByText(/No module is ready/)).toBeInTheDocument();
  });
});
