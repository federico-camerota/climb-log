# SPDX-License-Identifier: GPL-3.0-or-later
"""Accent- and case-insensitive text matching, for Italian notes (D-024)."""

import unicodedata


def fold(text: str) -> str:
    """The text without accents and case: `Perché PIÙ` → `perche piu`."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(query: str, text: str) -> bool:
    """Whether every word of the query appears in the text, ignoring accents and case."""
    folded = fold(text)
    return all(word in folded for word in fold(query).split())
