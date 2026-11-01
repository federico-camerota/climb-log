// SPDX-License-Identifier: GPL-3.0-or-later
// A field's value as the API gives it, as an input holds it, and back. Numbers stay text as
// typed (a decimal comma included): the API parses them as the sheet would, and is the
// authority on every value (D-075); the checks here only answer sooner.

import type { FieldDef, ScaleDef } from "./schema";

/** What an input holds: text for most fields, a number (or null) for a scale. */
export type InputValue = string | number | null;

const NUMERIC = new Set(["integer", "number", "percent"]);
const NUMBER = /^-?\d+(?:[.,]\d+)?$/;

export function isScale(field: FieldDef, scale: ScaleDef | undefined): boolean {
  return field.type === "scale" && scale?.choices === undefined;
}

/** The API's value as the input shows it. */
export function toInput(field: FieldDef, scale: ScaleDef | undefined, value: unknown): InputValue {
  if (value === null || value === undefined) return isScale(field, scale) ? null : "";
  if (isScale(field, scale)) return typeof value === "number" ? value : Number(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return asText(value);
}

/** The input's value as the API takes it: blank is null. */
export function toApi(field: FieldDef, value: InputValue): unknown {
  if (value === null || value === "") return null;
  if (typeof value === "number") return value;
  const text = field.type === "text" ? value : value.trim();
  if (field.type === "bool") return text === "Yes";
  return text === "" ? null : text;
}

/** Whether the input still holds the value read (numbers compared as numbers: 7,5 = 7.5). */
export function unchanged(field: FieldDef, read: unknown, value: InputValue): boolean {
  const now = toApi(field, value);
  const before = read ?? null;
  if (now === null || before === null) return now === before;
  if ((NUMERIC.has(field.type) || field.type === "duration") && typeof now === "string") {
    const parsed = Number(now.replace(",", "."));
    if (!Number.isNaN(parsed)) return parsed === Number(before);
  }
  if (typeof before === "boolean") return now === before;
  return asText(now) === asText(before);
}

/** A problem the browser can tell at once, or null (the API checks the rest). */
export function problem(field: FieldDef, value: InputValue): string | null {
  const blank = value === null || (typeof value === "string" && value.trim() === "");
  if (blank) return field.required === true ? "Required" : null;
  if (!NUMERIC.has(field.type) || typeof value !== "string") return null;
  const text = value.trim();
  if (!NUMBER.test(text)) return "Not a number (e.g. 7,5)";
  const number = Number(text.replace(",", "."));
  if (field.type === "integer" && !Number.isInteger(number)) return "A whole number";
  if (field.min !== undefined && number < field.min) return `At least ${String(field.min)}`;
  if (field.max !== undefined && number > field.max) return `At most ${String(field.max)}`;
  return null;
}

/** A numeric scale's steps, best first (D-078): 10 → 1 when higher is better, 1 → 10 when
 * lower is better or neutral (no best). */
export function scaleSteps(scale: ScaleDef): number[] {
  const min = scale.min ?? 1;
  const max = scale.max ?? 10;
  const steps = Array.from({ length: Math.floor(max - min) + 1 }, (_, i) => min + i);
  return scale.direction === "higher_better" ? steps.reverse() : steps;
}

const HINTS = ["red", "orange", "yellow", "lime", "green"];

/** The colour of a scale value: red for the worst end, green for the best (06-ui). */
export function scaleColour(value: number, scale: ScaleDef): string {
  if (scale.direction === "neutral") return "blue";
  const min = scale.min ?? 1;
  const max = scale.max ?? 10;
  const share = max > min ? (value - min) / (max - min) : 1;
  const good = scale.direction === "lower_better" ? 1 - share : share;
  return HINTS[Math.min(HINTS.length - 1, Math.floor(good * HINTS.length))] ?? "gray";
}

/** A value from the API as text: numbers and dates as the API writes them. */
export function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return value === null || value === undefined ? "" : JSON.stringify(value);
}
