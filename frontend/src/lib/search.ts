// SPDX-License-Identifier: GPL-3.0-or-later
// Search that ignores case and accents (D-024): "cosi" finds "così", "PIU" finds "più".

/** The text in lower case, without accents. */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Whether every word of the query is somewhere in the texts. */
export function matches(texts: string[], query: string): boolean {
  const words = fold(query)
    .split(/\s+/)
    .filter((word) => word !== "");
  const haystack = fold(texts.join("\n"));
  return words.every((word) => haystack.includes(word));
}
