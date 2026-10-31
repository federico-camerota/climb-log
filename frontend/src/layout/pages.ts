// SPDX-License-Identifier: GPL-3.0-or-later
/** The sidebar's pages (06-ui, D-073); the module is chosen inside each page. */
export const PAGES = [
  { path: "/", label: "Today" },
  { path: "/log", label: "Log" },
  { path: "/records", label: "Records" },
  { path: "/dashboards", label: "Dashboards" },
  { path: "/settings", label: "Settings" },
] as const;
