# SPDX-License-Identifier: GPL-3.0-or-later
"""Climbing grades: French (`6b+`) and gym (plain numbers), with a numeric index (D-017, D-047).

The system is detected per value among those a field allows; grades are never converted from
one system to the other, so charts keep them on separate axes.

French index: one step per letter or `+`, `(digit - 1) * 6 + {a: 0, b: 2, c: 4} + plus`, so
6a = 30, 6a+ = 31, 6b = 32, 7a = 36. Gym index: the number itself. A slash grade (`6a/6a+`)
sits halfway between its two grades.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

System = Literal["french", "gym"]
SUPPORTED: tuple[System, ...] = ("french", "gym")

_FRENCH = re.compile(r"(?P<digit>[1-9])(?P<letter>[abc])(?P<plus>\+?)", re.IGNORECASE)
_GYM = re.compile(r"\d+(?:[.,]\d+)?")
_LETTER_STEPS = {"a": 0, "b": 2, "c": 4}
_MAX_SLASH_STEPS: dict[System, float] = {"french": 2, "gym": 1}
_EXAMPLES: dict[System, str] = {
    "french": "a French grade (e.g. 6b+)",
    "gym": "a gym grade (a number)",
}


class GradeError(ValueError):
    """A value that is not a grade of the field's systems. `reason` follows the value."""

    def __init__(self, text: str, reason: str) -> None:
        self.reason = reason
        self.message = f"{text!r} {reason}"
        super().__init__(self.message)


@dataclass(frozen=True)
class Grade:
    system: System
    index: float  # comparable only within one system
    text: str  # as typed, trimmed; French letters in lower case


def parse_grade(text: str, systems: Sequence[str]) -> Grade:
    """The grade written in `text`, of one of `systems`. Raises `GradeError`."""
    text = text.strip()
    allowed = [system for system in SUPPORTED if system in systems]
    parts = [part.strip() for part in text.split("/")]
    if len(parts) == 1:
        grade = _single(parts[0], allowed)
        if grade is None:
            raise GradeError(text, f"is not {_expected(allowed)}")
        return grade
    if len(parts) != 2:
        raise GradeError(text, f"is not {_expected(allowed)}")

    low, high = (_single(part, allowed) for part in parts)
    if low is None or high is None:
        raise GradeError(text, f"is not {_expected(allowed)}, or two close ones like 6a/6a+")
    if low.system != high.system:
        raise GradeError(text, "mixes a French and a gym grade")
    if low.index >= high.index:
        raise GradeError(text, "has the harder grade first")
    if high.index - low.index > _MAX_SLASH_STEPS[low.system]:
        raise GradeError(text, "has its two grades too far apart")
    return Grade(low.system, (low.index + high.index) / 2, f"{low.text}/{high.text}")


def _single(text: str, allowed: list[System]) -> Grade | None:
    if "french" in allowed and (found := _FRENCH.fullmatch(text)):
        digit, letter, plus = int(found["digit"]), found["letter"].lower(), found["plus"]
        index = (digit - 1) * 6 + _LETTER_STEPS[letter] + len(plus)
        return Grade("french", index, f"{digit}{letter}{plus}")
    if "gym" in allowed and _GYM.fullmatch(text):
        number = text.replace(",", ".")
        value = float(number) if "." in number else int(number)
        return Grade("gym", value, text) if value > 0 else None
    return None


def _expected(allowed: list[System]) -> str:
    return " or ".join(_EXAMPLES[system] for system in allowed)
