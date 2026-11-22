// SPDX-License-Identifier: GPL-3.0-or-later
// How a program's dashboard shows its values (D-117).

const QUALITY_COLOURS = ["green", "yellow", "orange", "red"];

export function decimal(value: number, digits = 1): string {
  return value.toFixed(digits).replace(".", ",");
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${String(Math.round(value * 100))}%`;
}

/** A week table's value: a share as a %, a count whole, a mean or sum with one decimal. */
export function weekValue(agg: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (agg === "share") return percent(value);
  if (agg === "count") return String(Math.round(value));
  return decimal(value);
}

/** The colour of a quality: the best green, the worst red (in the choices' order). */
export function qualityColour(quality: string | null | undefined, qualities: string[]): string {
  const i = quality == null ? -1 : qualities.indexOf(quality);
  if (i < 0) return "gray";
  const step = qualities.length > 1 ? i / (qualities.length - 1) : 0;
  return QUALITY_COLOURS[Math.round(step * (QUALITY_COLOURS.length - 1))] ?? "gray";
}
