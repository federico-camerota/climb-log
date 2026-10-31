// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { HEALTH, MODULES, stubApi } from "../test/api";
import { renderApp } from "../test/render";

describe("Shell", () => {
  it("shows the app name, the server status and the pages", async () => {
    stubApi({ "/api/health": HEALTH });
    renderApp("/");
    expect(screen.getByRole("heading", { name: "climb-log" })).toBeInTheDocument();
    expect(await screen.findByText("Server OK · v0.0.0")).toBeInTheDocument();
    for (const page of ["Today", "Log", "Records", "Dashboards", "Settings"]) {
      expect(screen.getByRole("link", { name: page })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("data-active", "true");
  });

  it("goes to a page from the sidebar and marks it active", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": MODULES });
    const { router } = renderApp("/");
    await userEvent.click(screen.getByRole("link", { name: "Settings" }));
    expect(router.state.location.pathname).toBe("/settings");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: "Today" })).not.toHaveAttribute("data-active");
  });

  it("marks a page active on its sub-paths", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": MODULES });
    renderApp("/dashboards/journal");
    expect(await screen.findByText("The module's dashboard comes with #77.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboards" })).toHaveAttribute("data-active", "true");
  });

  it("shows not found for an unknown path", () => {
    stubApi({ "/api/health": HEALTH });
    renderApp("/nowhere");
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
  });

  it("hides and shows the sidebar on a wide window, and remembers it", async () => {
    stubApi({ "/api/health": HEALTH });
    const { unmount } = renderApp("/");
    const sidebar = screen.getByRole("button", { name: "Sidebar" });
    expect(sidebar).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(sidebar);
    expect(sidebar).toHaveAttribute("aria-expanded", "false");
    unmount();
    renderApp("/"); // a reload
    expect(screen.getByRole("button", { name: "Sidebar" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("closes the sidebar after a link on a narrow window, not on a wide one", async () => {
    stubApi({ "/api/health": HEALTH, "/api/modules": MODULES });
    renderApp("/");
    const menu = screen.getByRole("button", { name: "Menu" });
    await userEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("link", { name: "Settings" }));
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Sidebar" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("switches between light and dark", async () => {
    stubApi({ "/api/health": HEALTH });
    renderApp("/");
    await userEvent.click(screen.getByRole("button", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-mantine-color-scheme", "dark");
    await userEvent.click(screen.getByRole("button", { name: "Light theme" }));
    expect(document.documentElement).toHaveAttribute("data-mantine-color-scheme", "light");
  });
});
