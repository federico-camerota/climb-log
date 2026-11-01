// SPDX-License-Identifier: GPL-3.0-or-later
import { expect, it } from "vitest";

import { csvCell, csvOf } from "./csv";
import { matches } from "./search";

it("writes cells for an Italian locale", () => {
  expect(csvCell(7.5)).toBe("7,5");
  expect(csvCell("2026-10-30")).toBe("30/10/2026");
  expect(csvCell(true)).toBe("Yes");
  expect(csvCell(null)).toBe("");
  expect(csvCell('[ESEMPIO] "così"; poi')).toBe('"[ESEMPIO] ""così""; poi"');
  expect(csvCell("riga uno\nriga due")).toBe('"riga uno\nriga due"');
});

it("starts with a byte-order mark and ends lines with CRLF", () => {
  expect(csvOf(["Date", "Mood"], [["2026-10-30", 7]])).toBe(
    `${String.fromCharCode(0xfeff)}Date;Mood\r\n30/10/2026;7\r\n`,
  );
});

it("searches without case or accents, every word", () => {
  const notes = ["[ESEMPIO] Più riposo, così va meglio"];
  expect(matches(notes, "cosi")).toBe(true);
  expect(matches(notes, "PIU riposo")).toBe(true);
  expect(matches(notes, "più falesia")).toBe(false);
  expect(matches(notes, "  ")).toBe(true);
});
