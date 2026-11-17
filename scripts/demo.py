# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: RUF001  (the journal's choices use en dashes, as in "Good - as planned")
"""A fictional demo set that looks like real use, for live demos and screenshots (D-034, D-108).

Writes a folder with a workbook per module and an app config pointing to them:

- `journal.xlsx`: 26 weeks up to `--end` (enough for the training-load ratio and a few
  correlations), about three sessions a week (now and then two on one day), rest days in
  between, scores (and a bit of the sleep) that drift with a slow "form" curve and a few bad
  days, grades that rise slowly (sport in French grades, bouldering in Font), and short
  `[ESEMPIO]` notes. Fields with a `since:` are blank before it, as in a real journal; the
  default end lies after the latest `since:` so every field has a few weeks of values.
- `protein.xlsx`: 2-5 meals a day around the daily target, a few days not logged.
- `finger-strength.xlsx`: about two sessions a week, max hangs and finger curls in turn, with
  their sets and slowly rising loads.
- `config.toml`: the three modules, with backups and snapshots inside the folder, so serving
  the demo never touches the app's real data folders.

Every value is invented. Written through the app's own writer, so the workbooks are exactly
what logging in the app produces (formulas, Summary tab, `_settings`).

    uv run python scripts/demo.py OUT_DIR [--end 2026-12-18] [--weeks 26] [--seed 3]
    uv run climblog serve --config OUT_DIR/config.toml --port 8100
"""

import argparse
import datetime as dt
import math
import random
from pathlib import Path
from typing import Any

from climblog.modules import load_module
from climblog.modules.schema import Module
from climblog.storage import RecordWriter, XlsxBackend, sync_module

MODULES = Path(__file__).parent.parent / "modules"
FILES = {  # module → (definition, workbook)
    "journal": ("journal.yaml", "journal.xlsx"),
    "protein": ("protein.yaml", "protein.xlsx"),
    "finger_strength": ("finger-strength.yaml", "finger-strength.xlsx"),
}
END = dt.date(2026, 12, 18)

VENUES = {  # venue → setting
    "[ESEMPIO] Palestra Nord": "Indoor",
    "[ESEMPIO] Falesia del Lago": "Outdoor",
    "[ESEMPIO] Home wall": "Home wall",
}
TYPES = ["Climbing", "Climbing", "Climbing", "Hangboard", "Strength", "Endurance / ARC"]
FRENCH = ["6a", "6a+", "6b", "6b+", "6c", "6c+", "7a", "7a+", "7b"]
FONT = ["6A", "6A+", "6B", "6B+", "6C", "6C+", "7A", "7A+", "7B"]
SEND_TYPES = {
    "Sport": ["Onsight", "Redpoint / send", "Redpoint / send", "Top rope / repeat"],
    "Bouldering": ["Flash", "Redpoint / send", "Redpoint / send"],
}
BODY = [
    "fingers", "forearms", "elbows", "shoulders", "neck_traps", "wrists", "skin",
    "upper_back", "lower_back", "core", "hips_glutes", "knees_ankles", "legs",
]  # fmt: skip
GOOD = ["[ESEMPIO] Piedi precisi sul tetto", "[ESEMPIO] Lettura della via", "[ESEMPIO] Più su"]
OFF = ["[ESEMPIO] Dita stanche", "[ESEMPIO] Troppa fretta", "[ESEMPIO] Paura sulla placca"]
CHANGE = ["[ESEMPIO] Più riposo tra i tentativi", "[ESEMPIO] Riscaldamento più lungo"]
NOTES = ["[ESEMPIO] Bene", "[ESEMPIO] Un po' stanco dal lavoro", "[ESEMPIO] Così così", None]
MEALS: dict[str, tuple[int, list[str | None]]] = {  # meal → (typical grams, what)
    "Breakfast": (28, ["[ESEMPIO] Yogurt greco e avena", "[ESEMPIO] Uova e pane"]),
    "Lunch": (40, ["[ESEMPIO] Pasta e tonno", "[ESEMPIO] Riso e pollo", "[ESEMPIO] Legumi"]),
    "Dinner": (45, ["[ESEMPIO] Salmone e patate", "[ESEMPIO] Tofu e verdure"]),
    "Snack": (20, ["[ESEMPIO] Shake proteico", "[ESEMPIO] Ricotta", None]),
}
FINGER_NOTES = ["[ESEMPIO] Prese buone", "[ESEMPIO] Pelle secca", "[ESEMPIO] Ultima serie dura"]


def scale(rng: random.Random, centre: float, spread: float = 1.2) -> int:
    """A 1-10 score around `centre`."""
    return max(1, min(10, round(rng.gauss(centre, spread))))


def grades(rng: random.Random, kind: str, level: float) -> dict[str, Any]:
    """The hardest grade tried and (mostly) the hardest send of a climbing session. `level` is
    the index in the grade ladder the climber is at; the send is never harder than the try."""
    discipline = "Bouldering" if kind == "Bouldering" else "Sport"
    ladder = FONT if discipline == "Bouldering" else FRENCH
    tried = max(0, min(len(ladder) - 1, round(rng.gauss(level, 0.7))))
    values: dict[str, Any] = {"hardest_grade": ladder[tried], "tried_discipline": discipline}
    if rng.random() < 0.8:
        values["hardest_send"] = ladder[max(0, tried - rng.choice([0, 1, 1, 2]))]
        values["send_discipline"] = discipline
        values["send_type"] = rng.choice(SEND_TYPES[discipline])
    return values


def session(rng: random.Random, day: dt.date, n: int, form: float, level: float) -> dict[str, Any]:
    """One session: `form` (about 4-9) moves every score; soreness goes the other way."""
    sore = 11 - form
    session_type = rng.choice(TYPES)
    venue = rng.choices(list(VENUES), weights=[6, 3, 1])[0]
    setting = VENUES[venue]
    values: dict[str, Any] = {
        "date": day.isoformat(),
        "session_no": n,
        "venue": venue,
        "setting": setting,
        "session_type": session_type,
        "duration_min": rng.choice([60, 75, 90, 105, 120]),
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
    if session_type in ("Climbing", "Endurance / ARC"):  # no grade on a hangboard day
        boulder = setting == "Home wall" or (setting == "Indoor" and rng.random() < 0.5)
        bump = 0.5 * (form - 6.8) - (1.5 if session_type == "Endurance / ARC" else 0)
        values |= grades(rng, "Bouldering" if boulder else "Sport", level + bump)
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


def journal(rng: random.Random, start: dt.date, end: dt.date) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    days = (end - start).days
    for offset in range(days + 1):
        day = start + dt.timedelta(days=offset)
        # a slow curve between about 5 and 8.5, with an odd bad day
        form = 6.8 + 1.6 * math.sin(offset / 9) - (2.5 if rng.random() < 0.08 else 0)
        level = 3 + 2 * offset / max(days, 1)  # 6b+/6B+ → 7a/7A over the weeks
        roll = rng.random()
        if roll < 0.42:
            records.append(("session", session(rng, day, 1, form, level)))
            if rng.random() < 0.1:
                records.append(("session", session(rng, day, 2, form - 0.5, level)))
        elif roll < 0.7:
            records.append(("rest_day", rest_day(rng, day, form)))
    return records


def protein(rng: random.Random, start: dt.date, end: dt.date) -> list[tuple[str, dict[str, Any]]]:
    records: list[tuple[str, dict[str, Any]]] = []
    for offset in range((end - start).days + 1):
        if rng.random() < 0.1:  # a day not logged
            continue
        day = (start + dt.timedelta(days=offset)).isoformat()
        meals = ["Breakfast", "Lunch", "Dinner"]
        meals[1:1] = ["Snack"] * rng.choice([0, 1, 1, 2])
        if rng.random() < 0.1:
            meals.remove("Dinner")  # logged only part of the day
        for n, meal in enumerate(meals, start=1):
            grams, what = MEALS[meal]
            values = {"date": day, "meal_no": n, "meal": meal, "what": rng.choice(what)}
            values["protein_g"] = max(5, round(rng.gauss(grams, grams * 0.25)))
            records.append(("meal", values))
    return records


def fingers(rng: random.Random, start: dt.date, end: dt.date) -> list[tuple[str, dict[str, Any]]]:
    """Max hangs and finger curls in turn, on two days a week (Tuesday, Friday), now and then
    skipped; loads rise over the weeks."""
    records: list[tuple[str, dict[str, Any]]] = []
    days = (end - start).days
    hangs = True
    for offset in range(days + 1):
        day = start + dt.timedelta(days=offset)
        if day.weekday() not in (1, 4) or rng.random() < 0.15:
            continue
        progress = offset / max(days, 1)
        form = 6.8 + 1.6 * math.sin(offset / 9)
        date = day.isoformat()
        kind = "Max hangs" if hangs else "Finger curls"
        hangs = not hangs
        records.append(
            (
                "session",
                {
                    "date": date,
                    "session_type": kind,
                    "start_time": rng.choice(["07:30", "18:30", "19:00"]),
                    "pre_fingers": scale(rng, 10 - form),
                    "pre_forearms": scale(rng, 10 - form),
                    "pre_shoulders": scale(rng, 9 - form),
                    "session_rpe": scale(rng, 7.5),
                    "notes": rng.choice([*FINGER_NOTES, None]),
                    "wb_mood_pre": scale(rng, form),
                    "wb_energy_pre": scale(rng, form),
                    "wb_fatigue_post": scale(rng, 12 - form),
                    "wb_mood_post": scale(rng, form + 0.5),
                },
            )
        )
        if kind == "Max hangs":
            added = 10 + 6 * progress + 0.4 * (form - 6.8)
            for n in range(1, rng.choice([4, 5, 5, 6]) + 1):
                kg = round((added + rng.gauss(0, 0.5)) * 2) / 2
                records.append(
                    (
                        "hang_set",
                        {
                            "date": date,
                            "set_no": n,
                            "edge_mm": 20,
                            "grip": "Half crimp",
                            "arms": "Two arms",
                            "hang_s": 10,
                            "added_kg": kg,
                            "rest_s": 180,
                            "rpe": scale(rng, 7 + n / 3),
                            "completed": rng.random() > 0.08,
                        },
                    )
                )
        else:
            right = 30 + 7 * progress
            for n in range(1, rng.choice([3, 4, 4]) + 1):
                records.append(
                    (
                        "curl_set",
                        {
                            "date": date,
                            "set_no": n,
                            "load_left_kg": round(right * 0.95 * 2) / 2,  # left a bit weaker
                            "reps_left": rng.choice([5, 6, 6, 7]),
                            "load_right_kg": round(right * 2) / 2,
                            "reps_right": rng.choice([5, 6, 6, 7]),
                            "rest_s": 120,
                            "rpe": scale(rng, 7 + n / 3),
                            "completed": True,
                        },
                    )
                )
    return records


GENERATORS = {"journal": journal, "protein": protein, "finger_strength": fingers}

CONFIG = """\
# The fictional demo set written by scripts/demo.py: every value is invented.
# uv run climblog serve --config {folder}/config.toml --port 8100

[backups]
folder = "backups"

[snapshots]
folder = "snapshots"
{modules}"""


def write(folder: Path, end: dt.date, seed: int, weeks: int = 26) -> dict[str, int]:
    """The workbooks and config in `folder` (new or empty), with the records up to `end`; how
    many records each module got."""
    folder.mkdir(parents=True, exist_ok=True)
    start = end - dt.timedelta(weeks=weeks)
    counts: dict[str, int] = {}
    for offset, (name, (definition, workbook)) in enumerate(FILES.items()):
        module = load_module(MODULES / definition)
        repo = XlsxBackend(folder / workbook)
        sync_module(module, repo)
        records = GENERATORS[name](random.Random(seed + offset), start, end)
        RecordWriter(module, repo).add_many([(e, tracked(module, e, r)) for e, r in records])
        counts[name] = len(records)
    modules = "".join(
        f'\n[modules.{name}]\ndefinition = "{(MODULES / definition).resolve()}"\n'
        f'workbook = "{workbook}"\n'
        for name, (definition, workbook) in FILES.items()
    )
    (folder / "config.toml").write_text(
        CONFIG.format(folder=folder, modules=modules), encoding="utf-8"
    )
    return counts


def tracked(module: Module, entity: str, values: dict[str, Any]) -> dict[str, Any]:
    """The values without the fields not tracked yet on the record's day (`since:`, 03 §2.2):
    the app's form doesn't ask for them, so a real journal has them blank."""
    day = dt.date.fromisoformat(values["date"])
    fields = module.entities[entity].fields
    return {
        name: value
        for name, value in values.items()
        if (since := getattr(fields.get(name), "since", None)) is None or day >= since
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="the folder to write (new or empty)")
    parser.add_argument("--end", type=dt.date.fromisoformat, default=END)
    parser.add_argument("--weeks", type=int, default=26)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} is not empty: give a new folder")
    counts = write(args.out, args.end, args.seed, args.weeks)
    for name, count in counts.items():
        print(f"{name}: {count} fictional records up to {args.end}")
    print(f"serve it: uv run climblog serve --config {args.out}/config.toml --port 8100")


if __name__ == "__main__":
    main()
