// SPDX-License-Identifier: GPL-3.0-or-later
// The Records filters of the legacy Log Search (00 §1, 05 §2, D-102): a date range, weekdays,
// a status class and value; and the matches of a search, highlighted in the original text
// (accents and case ignored, 05 §3.6).
import { fold } from "./search";

export interface Filters {
  from: string | null; // yyyy-mm-dd, inclusive
  to: string | null;
  weekdays: string[]; // ISO numbers: "1" Monday … "7" Sunday
  status: string | null; // a status column; ANY_STATUS: any of them
  level: string | null; // the status value, e.g. LOW
}

export const NO_FILTERS: Filters = {
  from: null,
  to: null,
  weekdays: [],
  status: null,
  level: null,
};
export const ANY_STATUS = "*";
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function active(filters: Filters): boolean {
  return (
    filters.from !== null ||
    filters.to !== null ||
    filters.weekdays.length > 0 ||
    filters.level !== null
  );
}

/** The ISO weekday of a `yyyy-mm-dd` date (1 Monday … 7 Sunday), or null. */
export function weekday(date: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
  if (match === null) return null;
  const day = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  ).getUTCDay();
  return day === 0 ? 7 : day;
}

/** Whether a record passes the filters: `date` is its date (yyyy-mm-dd, or null), `statuses`
 * the columns the status filter reads. A status filter needs a value; without a class it
 * reads any status column. */
export function passes(
  values: Record<string, unknown>,
  date: string | null,
  filters: Filters,
  statuses: string[],
): boolean {
  const day = date?.slice(0, 10) ?? null;
  if (filters.from !== null && (day === null || day < filters.from)) return false;
  if (filters.to !== null && (day === null || day > filters.to)) return false;
  if (filters.weekdays.length > 0) {
    const number = day === null ? null : weekday(day);
    if (number === null || !filters.weekdays.includes(String(number))) return false;
  }
  if (filters.level !== null) {
    const read =
      filters.status === null || filters.status === ANY_STATUS ? statuses : [filters.status];
    if (!read.some((column) => values[column] === filters.level)) return false;
  }
  return true;
}

/** The derived columns holding statuses: every value they have is one of the levels. */
export function statusColumns(
  rows: Record<string, unknown>[],
  derived: string[],
  levels: string[],
): string[] {
  return derived.filter((column) => {
    const found = rows.map((row) => row[column]).filter((v) => v !== null && v !== undefined);
    return found.length > 0 && found.every((v) => typeof v === "string" && levels.includes(v));
  });
}

export interface Part {
  text: string;
  hit: boolean;
}

/** The text cut where the query's words are (case and accents ignored), for highlighting. */
export function highlight(text: string, query: string): Part[] {
  const words = fold(query)
    .split(/\s+/)
    .filter((word) => word !== "");
  if (words.length === 0 || text === "") return [{ text, hit: false }];
  // fold one character at a time, remembering which character each folded unit came from
  const chars = Array.from(text);
  let folded = "";
  const origin: number[] = [];
  chars.forEach((char, i) => {
    const part = fold(char);
    folded += part;
    for (let k = 0; k < part.length; k++) origin.push(i);
  });
  const hit = new Array<boolean>(chars.length).fill(false);
  for (const word of words) {
    for (let at = folded.indexOf(word); at !== -1; at = folded.indexOf(word, at + 1)) {
      for (let k = at; k < at + word.length; k++) hit[origin[k] ?? 0] = true;
    }
  }
  const parts: Part[] = [];
  chars.forEach((char, i) => {
    const last = parts.at(-1);
    if (last !== undefined && last.hit === hit[i]) last.text += char;
    else parts.push({ text: char, hit: hit[i] ?? false });
  });
  return parts;
}
