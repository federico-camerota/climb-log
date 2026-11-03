// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import { ANY_STATUS, highlight, NO_FILTERS, passes, statusColumns, weekday } from "./recordFilters";

const ROW = { wb_status: "LOW", ph_status: "GOOD" };
const STATUSES = ["wb_status", "ph_status"];

describe("record filters (D-102)", () => {
  it("numbers weekdays from Monday", () => {
    expect(weekday("2026-10-26")).toBe(1); // a Monday
    expect(weekday("2026-11-01")).toBe(7); // a Sunday
    expect(weekday("not a date")).toBeNull();
  });

  it("keeps the dates in the range, both ends included", () => {
    const range = { ...NO_FILTERS, from: "2026-10-20", to: "2026-10-28" };
    expect(passes(ROW, "2026-10-20", range, STATUSES)).toBe(true);
    expect(passes(ROW, "2026-10-28", range, STATUSES)).toBe(true);
    expect(passes(ROW, "2026-10-29", range, STATUSES)).toBe(false);
    expect(passes(ROW, null, range, STATUSES)).toBe(false); // no date: out of any range
  });

  it("keeps the weekdays picked", () => {
    const weekend = { ...NO_FILTERS, weekdays: ["6", "7"] };
    expect(passes(ROW, "2026-10-31", weekend, STATUSES)).toBe(true);
    expect(passes(ROW, "2026-10-30", weekend, STATUSES)).toBe(false);
  });

  it("reads one status class, or any of them", () => {
    const low = { ...NO_FILTERS, level: "LOW" };
    expect(passes(ROW, null, low, STATUSES)).toBe(true); // any class
    expect(passes(ROW, null, { ...low, status: ANY_STATUS }, STATUSES)).toBe(true);
    expect(passes(ROW, null, { ...low, status: "ph_status" }, STATUSES)).toBe(false);
    expect(passes(ROW, null, { ...NO_FILTERS, status: "ph_status" }, STATUSES)).toBe(true); // no value
  });

  it("finds the status columns among the derived values", () => {
    const rows = [
      { wb_status: "LOW", wb_score: 3.2, log_check: "OK" },
      { wb_status: null, wb_score: 7, log_check: "Missing: Feel" },
    ];
    expect(statusColumns(rows, ["wb_status", "wb_score", "log_check"], ["GOOD", "LOW"])).toEqual([
      "wb_status",
    ]);
  });

  it("highlights each word in the original text, accents and case ignored", () => {
    expect(highlight("Perché così?", "perche COSI")).toEqual([
      { text: "Perché", hit: true },
      { text: " ", hit: false },
      { text: "così", hit: true },
      { text: "?", hit: false },
    ]);
    expect(highlight("giovedì e giovedi'", "giovedi")).toEqual([
      { text: "giovedì", hit: true },
      { text: " e ", hit: false },
      { text: "giovedi", hit: true },
      { text: "'", hit: false },
    ]);
    expect(highlight("nothing", "")).toEqual([{ text: "nothing", hit: false }]);
  });
});
