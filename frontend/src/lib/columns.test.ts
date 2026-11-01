// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import type { ModuleInfo } from "../api/client";
import type { EntityDef } from "../forms/schema";
import { DIARY } from "../test/api";
import { fieldColumns } from "./columns";

// A fictional session with the journal's shapes: notes in every section, mood and body parts
// before and after.
const SESSION: EntityDef = {
  key: ["date"],
  sections: {
    wb_pre: { label: "Wellbeing · before" },
    wb_post: { label: "Wellbeing · after" },
    ph_pre: { label: "Physical · before" },
    ph_post: { label: "Physical · after" },
    feel: { label: "Session feel" },
  },
  fields: {
    date: { type: "date", section: "*" },
    wb_mood_pre: { type: "scale", scale: "s10", section: "wb_pre" },
    wb_mood_post: { type: "scale", scale: "s10", section: "wb_post" },
    wb_note_pre: { type: "text", section: "wb_pre" },
    wb_note_post: { type: "text", section: "wb_post" },
    ph_pre_fingers: { type: "scale", scale: "s10_down", section: "ph_pre" },
    ph_post_fingers: { type: "scale", scale: "s10_down", section: "ph_post" },
    ph_note_pre: { type: "text", section: "ph_pre" },
    feel_note: { type: "text", section: "feel" },
    wb_sleep_hours: { type: "number", section: "wb_pre" },
  },
};

function labels(entity: EntityDef, module: ModuleInfo = DIARY): Record<string, string> {
  return Object.fromEntries(fieldColumns(module, entity).map((c) => [c.id, c.label]));
}

describe("column names", () => {
  it("gives a shared label its section", () => {
    expect(labels(SESSION)).toEqual({
      date: "Date",
      wb_mood_pre: "Mood (before)",
      wb_mood_post: "Mood (after)",
      wb_note_pre: "Wellbeing note (before)",
      wb_note_post: "Wellbeing note (after)",
      ph_pre_fingers: "Fingers (before) ↓",
      ph_post_fingers: "Fingers (after) ↓",
      ph_note_pre: "Physical note (before)",
      feel_note: "Session feel note",
      wb_sleep_hours: "Sleep hours", // not shared: as in the form
    });
  });

  it("groups the fields by their section", () => {
    const groups = Object.fromEntries(fieldColumns(DIARY, SESSION).map((c) => [c.id, c.group]));
    expect([groups.date, groups.wb_note_pre, groups.feel_note]).toEqual([
      null,
      "Wellbeing · before",
      "Session feel",
    ]);
  });
});
