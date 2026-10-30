// SPDX-License-Identifier: GPL-3.0-or-later
// Dates as the app shows them: dd/mm/yyyy (06-ui).

/** `2026-10-30T09:05:00` → `30/10/2026 09:05` (the API's local times, shown as they are). */
export function formatDateTime(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso);
  if (match === null) return iso;
  const [, year, month, day, hour, minute] = match;
  const date = `${day ?? ""}/${month ?? ""}/${year ?? ""}`;
  return hour === undefined ? date : `${date} ${hour}:${minute ?? ""}`;
}
