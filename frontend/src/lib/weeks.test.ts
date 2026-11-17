// SPDX-License-Identifier: GPL-3.0-or-later
import { describe, expect, it } from "vitest";

import { weekMonday, weekSpan, weekText } from "./weeks";

describe("weekMonday", () => {
  it("gives the Monday of an ISO week, as the backend does", () => {
    expect(weekMonday("2026-W42")).toBe("2026-10-12");
    expect(weekMonday("2026-W01")).toBe("2025-12-29");
    expect(weekMonday("2026-W53")).toBe("2026-12-28"); // 2026 starts on a Thursday
    expect(weekMonday(" 2027-W03 ")).toBe("2027-01-18");
  });

  it("is null for what isn't a week", () => {
    expect(weekMonday("2027-W53")).toBeNull();
    expect(weekMonday("2026-W00")).toBeNull();
    expect(weekMonday("2026-W4")).toBeNull();
    expect(weekMonday("2026-42")).toBeNull();
  });
});

describe("weekText and weekSpan", () => {
  it("names a day's ISO week and gives a week's Monday and Sunday", () => {
    expect(weekText("2026-11-18")).toBe("2026-W47");
    expect(weekText("2026-11-22")).toBe("2026-W47"); // Sunday: still that week
    expect(weekText("2025-12-29")).toBe("2026-W01"); // week 1 starts in the year before
    expect(weekText("2027-01-01")).toBe("2026-W53");
    expect(weekSpan("2026-W47")).toEqual(["2026-11-16", "2026-11-22"]);
    expect(weekSpan("2026-W4x")).toBeNull();
  });
});
