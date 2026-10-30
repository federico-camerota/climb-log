// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HEALTH, MODULES, stubApi } from "../test/api";
import { renderApp } from "../test/render";

describe("pages still to come", () => {
  it("Today names its issue", () => {
    stubApi({ "/api/health": HEALTH });
    renderApp("/");
    expect(
      screen.getByText("The due forms, log check and recommendation come with #74."),
    ).toBeInTheDocument();
  });

  it("Log takes the first module and names its issue", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": MODULES });
    const { router } = renderApp("/log");
    expect(await screen.findByText("The forms come with #72.")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/log/journal");
  });
});
