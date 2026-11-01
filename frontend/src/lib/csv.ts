// SPDX-License-Identifier: GPL-3.0-or-later
// CSV as Excel and LibreOffice open it in an Italian locale (D-079): semicolons, dates
// dd/mm/yyyy, decimal commas, UTF-8 with a byte-order mark.

import { formatDateTime } from "./format";

const BOM = String.fromCharCode(0xfeff); // UTF-8 for Excel
const ISO_DAY = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?$/;

/** One cell: numbers with a decimal comma, ISO dates day first, Yes/No for booleans. */
export function csvCell(value: unknown): string {
  let text: string;
  if (value === null || value === undefined) text = "";
  else if (typeof value === "number") text = String(value).replace(".", ",");
  else if (typeof value === "boolean") text = value ? "Yes" : "No";
  else if (typeof value === "string") text = ISO_DAY.test(value) ? formatDateTime(value) : value;
  else text = JSON.stringify(value);
  return /[";\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** The whole file: a header row, then one line per row. */
export function csvOf(header: string[], rows: unknown[][]): string {
  const lines = [header, ...rows].map((row) => row.map(csvCell).join(";"));
  return `${BOM}${lines.join("\r\n")}\r\n`;
}

/** Offer the text as a file to save. */
export function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
