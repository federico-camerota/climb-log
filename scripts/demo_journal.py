# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001  (the journal's choices use en dashes, as in "Good - as planned")
"""A fictional climbing journal that looks like real use, for screenshots and demos (D-034).

Every value is invented: 26 weeks up to a day (enough for the training-load ratio and a few
correlations), about three sessions a week (now and then two on one day), rest days in
between, scores (and a bit of the sleep) that drift with a slow "form" curve and a few bad
days, and short `[ESEMPIO]` notes. Written through the app's own writer, so the workbook is
exactly what logging in the app produces (formulas, Summary tab, `_settings`).

    uv run python scripts/demo_journal.py OUT.xlsx [--end 2026-10-30] [--weeks 26] [--seed 3]
"""

import argparse
import datetime as dt
import math
import random
from pathlib import Path
from typing import Any

from climblog.modules import load_module
from climblog.storage import RecordWriter, XlsxBackend, sync_module

JOURNAL = Path(__file__).parent.parent / "modules" / "journal.yaml"
VENUES = ["[ESEMPIO] Palestra Nord", "[ESEMPIO] Falesia del Lago", "[ESEMPIO] Home wall"]
TYPES = ["Climbing", "Climbing", "Climbing", "Hangboard", "Strength", "Endurance / ARC"]
GRADES = ["6b", "6b+", "6c", "6c+", "7a", "7a/7a+"]
BODY = ["fingers", "forearms", "elbows", "shoulders", "neck_traps", "wrists", "skin"]
GOOD = ["[ESEMPIO] Piedi precisi sul tetto", "[ESEMPIO] Lettura della via", "[ESEMPIO] Più su"]
OFF = ["[ESEMPIO] Dita stanche", "[ESEMPIO] Troppa fretta", "[ESEMPIO] Paura sulla placca"]
CHANGE = ["[ESEMPIO] Più riposo tra i tentativi", "[ESEMPIO] Riscaldamento più lungo"]
NOTES = ["[ESEMPIO] Bene", "[ESEMPIO] Un po' stanco dal lavoro", "[ESEMPIO] Così così", None]


def scale(rng: random.Random, centre: float, spread: float = 1.2) -> int:
    """A 1-10 score around `centre`."""
    return max(1, min(10, round(rng.gauss(centre, spread))))


def session(rng: random.Random, day: dt.date, n: int, form: float) -> dict[str, Any]:
    """One session: `form` (about 4-9) moves every score; soreness goes the other way."""
    sore = 11 - form
    values: dict[str, Any] = {
        "date": day.isoformat(),
        "session_no": n,
        "venue": rng.choice(VENUES),
        "setting": "Indoor" if rng.random() < 0.75 else "Outdoor",
        "session_type": rng.choice(TYPES),
        "duration_min": rng.choice([60, 75, 90, 105, 120]),
        "hardest_grade": rng.choice(GRADES),
        "notes": rng.choice(NOTES),
        "wb_sleep_hours": max(5.0, min(9.0, round(rng.gauss(5.4 + 0.25 * form, 0.6) * 2) / 2)),
        "wb_sleep_quality": scale(rng, form),
        "wb_mood_pre": scale(rng, form),
        "wb_energy_pre": scale(rng, form),
        "wb_fatigue_post": scale(rng, sore + 1),
        "wb_mood_post": scale(rng, form + 0.5),
        "wb_recovery_feel": scale(rng, form),
        "mn_life_stress": scale(rng, sore - 1),
        "mn_confidence": scale(rng, form),
        "mn_motivation": scale(rng, form + 0.5),
        "mn_anxiety": scale(rng, sore - 1),
        "mn_focus": scale(rng, form),
        "mn_fall_commitment": scale(rng, form - 0.5),
        "mn_fear_response": scale(rng, sore - 0.5),
        "mn_route_confidence": scale(rng, form),
        "mn_approach": scale(rng, form),
        "feel_outcome": rng.choice(
            ["Good – as planned", "Ok – mixed", "Excellent – exceeded plan"]
        ),
        "feel_plan": rng.choice(["Yes – fully", "Mostly", "Partially"]),
        "feel_enjoyment": scale(rng, form + 0.5),
        "feel_satisfaction": scale(rng, form),
        "feel_effort": scale(rng, 6.5),
        "rf_good": rng.choice(GOOD),
        "rf_good_score": scale(rng, form),
        "rf_off": rng.choice(OFF),
        "rf_off_severity": scale(rng, sore),
        "rf_surprise": rng.choice(GOOD),
        "rf_surprise_impact": scale(rng, form - 1),
        "rf_change": rng.choice(CHANGE),
        "rf_change_priority": scale(rng, sore),
        "rf_session_score": scale(rng, form),
        "rf_win_size": rng.choice(["Solid progress", "Small win", "Insight / learning"]),
        "rf_win": rng.choice(GOOD),
    }
    for part in BODY:
        values[f"ph_pre_{part}"] = scale(rng, sore - 1, 1.3)
        values[f"ph_post_{part}"] = scale(rng, sore, 1.3)
    return values


def rest_day(rng: random.Random, day: dt.date, form: float) -> dict[str, Any]:
    values: dict[str, Any] = {
        "date": day.isoformat(),
        "rest_type": rng.choice(["Full rest", "Active recovery"]),
        "activity": rng.choice(["None", "Mobility / stretching", "Walk / hike", "Yoga"]),
        "sleep_hours": rng.choice([7, 7.5, 8, 8.5]),
        "sleep_quality": scale(rng, form + 0.5),
        "mood": scale(rng, form + 0.5),
        "energy": scale(rng, form),
        "motivation": scale(rng, form + 1),
        "life_stress": scale(rng, 11 - form - 1),
        "note": rng.choice(NOTES),
    }
    for part in BODY:
        values[f"body_{part}"] = scale(rng, 11 - form - 1.5, 1.3)
    return values


def write(path: Path, end: dt.date, seed: int, weeks: int = 26) -> int:
    """The workbook at `path` (new), with the records up to `end`; how many were written."""
    module = load_module(JOURNAL)
    repo = XlsxBackend(path)
    sync_module(module, repo)
    rng = random.Random(seed)
    records: list[tuple[str, dict[str, Any]]] = []
    start = end - dt.timedelta(weeks=weeks)
    for offset in range((end - start).days + 1):
        day = start + dt.timedelta(days=offset)
        # a slow curve between about 5 and 8.5, with an odd bad day
        form = 6.8 + 1.6 * math.sin(offset / 9) - (2.5 if rng.random() < 0.08 else 0)
        roll = rng.random()
        if roll < 0.42:
            records.append(("session", session(rng, day, 1, form)))
            if rng.random() < 0.1:
                records.append(("session", session(rng, day, 2, form - 0.5)))
        elif roll < 0.7:
            records.append(("rest_day", rest_day(rng, day, form)))
    RecordWriter(module, repo).add_many(records)
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="the workbook to write (must not exist)")
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 10, 30))
    parser.add_argument("--weeks", type=int, default=26)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"{args.out} exists: give a new file")
    count = write(args.out, args.end, args.seed, args.weeks)
    print(f"{args.out}: {count} fictional records up to {args.end}")


if __name__ == "__main__":
    main()
