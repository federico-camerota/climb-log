// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HEALTH, module, stubApi } from "../test/api";
import { renderApp } from "../test/render";

describe("Settings", () => {
  it("lists each module, with the problems of one that doesn't load", async () => {
    stubApi({
      "/api/health": HEALTH,
      "/api/modules": {
        modules: [
          module("journal", "Climbing journal", ["session"]),
          { id: "broken", problems: ["broken.yaml:3:1: unknown key 'feilds'"] },
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
});
