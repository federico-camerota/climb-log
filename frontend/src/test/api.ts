// SPDX-License-Identifier: GPL-3.0-or-later
// A fake backend for component tests: `fetch` answers from a table of paths (fictional data).
import { vi } from "vitest";

import type { ModuleInfo, ModuleList, Records } from "../api/client";

type Answer = object | ((body: unknown) => Promise<Response>);

export interface Call {
  method: string;
  path: string;
  body: unknown; // the JSON sent, if any
}

/** Stub `fetch` with JSON answers by `"METHOD path"` (or the path alone, for GET); anything
 * else is 404. Returns the calls made, to check what was sent. */
export function stubApi(answers: Record<string, Answer>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, path, body });
      const answer = answers[`${method} ${path}`] ?? (method === "GET" ? answers[path] : undefined);
      if (answer === undefined) {
        return Promise.resolve(Response.json({ detail: "Not Found" }, { status: 404 }));
      }
      return typeof answer === "function"
        ? (answer as (body: unknown) => Promise<Response>)(body)
        : Promise.resolve(Response.json(answer));
    }),
  );
  return calls;
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

/** A fictional module with forms: a session split in sections (created at pre, completed at
 * post) and a rest day. */
export const DIARY: ModuleInfo = {
  id: "diary",
  name: "Training diary",
  version: 1,
  kind: "journal",
  problems: [],
  module_schema: {
    scales: {
      s10: { min: 1, max: 10, direction: "higher_better" },
      s10_down: { min: 1, max: 10, direction: "lower_better" },
    },
    entities: {
      session: {
        label: "Session",
        key: ["date", "session_no"],
        sections: {
          info: { label: "Session details", phase: "pre" },
          wb_pre: { label: "Wellbeing · before", phase: "pre" },
          wb_post: { label: "Wellbeing · after", phase: "post" },
        },
        fields: {
          date: { type: "date", required: true, section: "*" },
          session_no: { type: "integer", default: 1, min: 1, section: "*", label: "Session #" },
          venue: { type: "text", section: "info" },
          setting: { type: "choice", choices: ["Indoor", "Outdoor"], section: "info" },
          minutes: { type: "duration", section: "info", phase: "post" },
          notes: { type: "text", multiline: true, section: "info", phase: "post" },
          old: { type: "text", section: "info", retired: true },
          wb_sleep_hours: { type: "number", min: 0, max: 14, unit: "h", section: "wb_pre" },
          wb_mood_pre: { type: "scale", scale: "s10", section: "wb_pre" },
          wb_fatigue_post: { type: "scale", scale: "s10_down", section: "wb_post" },
        },
      },
      rest_day: {
        label: "Rest day",
        key: ["date"],
        fields: {
          date: { type: "date", required: true },
          rest_type: { type: "choice", choices: ["Full rest", "Active recovery"] },
          mood: { type: "scale", scale: "s10" },
        },
      },
    },
    forms: {
      pre_session: { entity: "session", phase: "pre", sections: ["info", "wb_pre"] },
      post_session: { entity: "session", phase: "post", sections: ["wb_post"] },
      rest_day: { entity: "rest_day" },
    },
  },
};

/** A write's answer: the record as read back, with some derived values. */
export function written(values: Record<string, unknown>, derived: Record<string, unknown> = {}) {
  return {
    record: { values, derived, rows: { Session: 3 } },
    as_of: "2026-10-30T09:05:00",
  };
}
