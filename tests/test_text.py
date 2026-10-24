# SPDX-License-Identifier: GPL-3.0-or-later
"""Accent- and case-insensitive matching for Italian notes (D-024)."""

import pytest

from climblog.text import fold, matches


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Perché PIÙ", "perche piu"), ("città", "citta"), ("po'", "po'"), ("ÀÈÉÌÒÙ", "aeeiou")],
)
def test_fold(text: str, expected: str) -> None:
    assert fold(text) == expected


@pytest.mark.parametrize(
    ("query", "found"),
    [
        ("perche", True),
        ("PIU riposo", True),  # every word, in any order
        ("riposo più", True),
        ("perché caldo", False),  # one word is missing
        ("", True),
    ],
)
def test_matches(query: str, found: bool) -> None:
    assert matches(query, "Perché? Più riposo tra le serie") is found
