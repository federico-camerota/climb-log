// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { App } from "./App";
import { renderWithMantine } from "./test/render";

it("renders the header with the app name and server status", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(Response.json({ status: "ok", version: "0.0.0" }))),
  );
  renderWithMantine(<App />);
  expect(screen.getByRole("heading", { name: "climb-log" })).toBeInTheDocument();
  expect(await screen.findByText("Server OK · v0.0.0")).toBeInTheDocument();
});
