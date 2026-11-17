// SPDX-License-Identifier: GPL-3.0-or-later
// ISO weeks as a program's runs start on them (`2026-W42`, D-109), as the backend reads them.

const WEEK = /^(\d{4})-W(\d{2})$/;

/** The Monday of an ISO week (`2026-W42` → `2026-10-12`), or null if it isn't one. */
export function weekMonday(text: string): string | null {
  const match = WEEK.exec(text.trim());
  if (match === null) return null;
  const year = Number(match[1]);
  const week = Number(match[2]);
  if (week < 1 || week > weeksIn(year)) return null;
  const monday = new Date(Date.UTC(year, 0, 4 - isoDay(year, 0, 4) + 1 + 7 * (week - 1)));
  return monday.toISOString().slice(0, 10);
}

/** 52 or 53: the ISO week of 28 December, always in the year's last week. */
function weeksIn(year: number): number {
  const day = new Date(Date.UTC(year, 11, 28));
  const thursday = new Date(day);
  thursday.setUTCDate(day.getUTCDate() + 4 - isoDay(year, 11, 28));
  const firstJan = Date.UTC(thursday.getUTCFullYear(), 0, 1);
  return Math.ceil(((thursday.getTime() - firstJan) / 86_400_000 + 1) / 7);
}

/** 1 (Monday) to 7 (Sunday). */
function isoDay(year: number, month: number, day: number): number {
  return new Date(Date.UTC(year, month, day)).getUTCDay() || 7;
}
