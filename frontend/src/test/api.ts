// SPDX-License-Identifier: GPL-3.0-or-later
// A fake backend for component tests: `fetch` answers from a table of paths (fictional data).
import { vi } from "vitest";

import type { ModuleInfo, ModuleList, Records } from "../api/client";

type Answer = object | (() => Promise<Response>);

/** Stub `fetch` with JSON answers by path; unknown paths are 404. Returns the paths asked. */
export function stubApi(answers: Record<string, Answer>): string[] {
  const asked: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) => {
      asked.push(path);
      const answer = answers[path];
      if (answer === undefined) {
        return Promise.resolve(Response.json({ detail: "Not Found" }, { status: 404 }));
      }
      return typeof answer === "function"
        ? (answer as () => Promise<Response>)()
        : Promise.resolve(Response.json(answer));
    }),
  );
  return asked;
}

export const HEALTH = { status: "ok", version: "0.0.0" };

export function module(id: string, name: string, entities: string[]): ModuleInfo {
  return {
    id,
    name,
    version: 1,
    kind: "journal",
    problems: [],
    module_schema: { entities: Object.fromEntries(entities.map((e) => [e, {}])) },
  };
}

export const MODULES: ModuleList = {
  modules: [
    module("journal", "Climbing journal", ["session", "rest_day"]),
    module("fingers", "Finger strength", ["sessions", "sets"]),
  ],
  problems: [],
};

export function records(count: number, extra: Partial<Records> = {}): Records {
  return {
    module: "journal",
    entity: "session",
    records: Array.from({ length: count }, (_, i) => ({
      values: { date: `2026-10-${String(10 + i)}` },
      derived: {},
      rows: { Session: 3 + i },
    })),
    issues: [],
    as_of: "2026-10-30T09:05:00",
    offline: false,
    ...extra,
  };
}
