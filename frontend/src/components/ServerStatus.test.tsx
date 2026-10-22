// SPDX-License-Identifier: GPL-3.0-or-later
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithMantine } from "../test/render";
import { ServerStatus } from "./ServerStatus";

function stubFetch(impl: () => Promise<Response>): void {
  vi.stubGlobal("fetch", vi.fn(impl));
}

describe("ServerStatus", () => {
  it("shows a loading state before the server answers", () => {
    stubFetch(() => new Promise(() => undefined)); // never resolves
    renderWithMantine(<ServerStatus />);
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
  });

  it("shows the version when the health check succeeds", async () => {
    stubFetch(() => Promise.resolve(Response.json({ status: "ok", version: "1.2.3" })));
    renderWithMantine(<ServerStatus />);
    expect(await screen.findByText("Server OK · v1.2.3")).toBeInTheDocument();
  });

  it("shows unreachable when the server returns an error", async () => {
    stubFetch(() => Promise.resolve(new Response("boom", { status: 500 })));
    renderWithMantine(<ServerStatus />);
    expect(await screen.findByText("Server unreachable")).toBeInTheDocument();
  });

  it("shows unreachable when the request fails", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    renderWithMantine(<ServerStatus />);
    expect(await screen.findByText("Server unreachable")).toBeInTheDocument();
  });
});
