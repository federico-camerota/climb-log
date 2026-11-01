// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import { DIARY } from "../test/api";
import { entityOf, fieldLabel, formGroups, formsOf, keyOf, scaleOf } from "./schema";
import { problem, scaleColour, scaleSteps, toApi, toInput, unchanged } from "./values";

const session = entityOf(DIARY, "session");
const restDay = entityOf(DIARY, "rest_day");
const forms = formsOf(DIARY);

function shown(form: string): [string | null, string[]][] {
  const def = forms[form];
  const entity = def?.entity === "rest_day" ? restDay : session;
  if (def === undefined || entity === undefined) throw new Error(form);
  return formGroups(entity, def).map((g) => [g.label, g.fields.map(([name]) => name)]);
}

describe("formGroups", () => {
  it("shows the pre-session sections in the pre phase, without key or retired fields", () => {
    expect(shown("pre_session")).toEqual([
      ["Session details", ["venue", "setting"]],
      ["Wellbeing · before", ["wb_sleep_hours", "wb_mood_pre"]],
    ]);
  });

  it("pulls post fields of other sections into the post-session form", () => {
    expect(shown("post_session")).toEqual([
      ["Wellbeing · after", ["wb_fatigue_post"]],
      ["Session details", ["minutes", "notes"]],
    ]);
  });

  it("shows every field of an entity without sections", () => {
    expect(shown("rest_day")).toEqual([[null, ["rest_type", "mood"]]]);
  });
});

describe("labels and keys", () => {
  it("names a field without its section prefix and phase, ↓ for lower is better", () => {
    const fields = session?.fields ?? {};
    const label = (name: string) => {
      const field = fields[name];
      if (field === undefined) throw new Error(name);
      return fieldLabel(name, field, scaleOf(DIARY, field.scale));
    };
    expect(label("wb_mood_pre")).toBe("Mood");
    expect(label("wb_fatigue_post")).toBe("Fatigue ↓");
    expect(label("wb_sleep_hours")).toBe("Sleep hours");
    expect(label("session_no")).toBe("Session #");
    expect(fieldLabel("rf_good_score", { type: "scale", section: "reflect" })).toBe("Good score");
  });

  it("takes the key from the entity, the date alone by default", () => {
    expect(session && keyOf(session)).toEqual(["date", "session_no"]);
    expect(keyOf({ fields: {}, date_field: "day" })).toEqual(["day"]);
  });
});

describe("values", () => {
  const number = { type: "number", min: 0, max: 14 };
  it("checks numbers as typed, decimal commas accepted", () => {
    expect(problem(number, "7,5")).toBeNull();
    expect(problem(number, "abc")).toBe("Not a number (e.g. 7,5)");
    expect(problem(number, "15")).toBe("At most 14");
    expect(problem({ type: "integer" }, "1.5")).toBe("A whole number");
    expect(problem({ type: "date", required: true }, "")).toBe("Required");
    expect(problem({ type: "duration" }, "1:30")).toBeNull(); // the API reads h:mm
  });

  it("tells a change from the value read", () => {
    expect(unchanged(number, 7.5, "7,5")).toBe(true);
    expect(unchanged(number, 7.5, "8")).toBe(false);
    expect(unchanged({ type: "text" }, null, "")).toBe(true);
    expect(unchanged({ type: "bool" }, true, "Yes")).toBe(true);
  });

  it("converts between the API and the inputs", () => {
    const scale = { min: 1, max: 10 };
    expect(toInput({ type: "scale" }, scale, 7)).toBe(7);
    expect(toInput({ type: "scale" }, scale, null)).toBeNull();
    expect(toInput({ type: "bool" }, undefined, false)).toBe("No");
    expect(toApi({ type: "number" }, " 7,5 ")).toBe("7,5");
    expect(toApi({ type: "text" }, " così ")).toBe(" così "); // notes as typed
    expect(toApi({ type: "bool" }, "No")).toBe(false);
    expect(toApi({ type: "choice" }, "")).toBeNull();
  });

  it("colours a scale from red to green, reversed for lower is better", () => {
    const up = { min: 1, max: 10, direction: "higher_better" as const };
    const down = { ...up, direction: "lower_better" as const };
    expect([scaleColour(1, up), scaleColour(10, up)]).toEqual(["red", "green"]);
    expect([scaleColour(1, down), scaleColour(10, down)]).toEqual(["green", "red"]);
    expect(scaleColour(5, { ...up, direction: "neutral" })).toBe("blue");
  });

  it("lists a scale's steps best first (neutral: from the lowest)", () => {
    const up = { min: 1, max: 5, direction: "higher_better" as const };
    expect(scaleSteps(up)).toEqual([5, 4, 3, 2, 1]);
    expect(scaleSteps({ ...up, direction: "lower_better" })).toEqual([1, 2, 3, 4, 5]);
    expect(scaleSteps({ ...up, direction: "neutral" })).toEqual([1, 2, 3, 4, 5]);
    expect(scaleSteps({ min: 0, max: 2 })).toEqual([0, 1, 2]); // no direction: as neutral
  });
});
