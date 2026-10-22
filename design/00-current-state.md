# 00 · Current state: the three workbooks

Analysis of the spreadsheets as of 2026-10-20. This is the **parity checklist**: every
input and every computed value listed here must be reproducible by the app.

Data volume at analysis time: Journal 2 sessions + 1 rest day; Shoulder 4 check-ins +
~13 exercise log entries; Fear of Falling empty (only an example row). Notes are written
in Italian.

---

## 1. `Climbing_Journal.xlsx`

### Structure
- Header on row 4, data rows 5–304 (300-row capacity), group labels on row 3
  (PRE-SESSION / POST-SESSION / AUTOMATIC).
- **Row-linked tabs**: the date is typed only on `Session`; every other session tab copies
  `Session!A{row}`. A session is "the same row on every tab". Fragile: inserting/sorting a
  row on one tab silently corrupts the others.
- Formula-driven `Summary – Recent`, `Summary – Trends` (with charts) and `Log Search`.

### Input tabs and fields

**Session** — date, venue, indoor/outdoor {Indoor, Outdoor, Home wall}, session type
{Climbing, Hangboard, Strength, Endurance / ARC, Active rest}, partners, duration (min),
hardest grade tried (free text, e.g. `7a`), notes.
Auto: overall status, log check (which tabs are incomplete), weekday, month, days since previous.

**Wellbeing** (1–10) — pre: sleep hours (decimal), sleep quality, mood, energy, note;
post: fatigue ↓, mood, recovery feel, note.

**Physical** (1–10 ↓, soreness) — fingers, forearms, shoulders, wrists, skin; each pre and
post; pre note, post note.

**Mental** (1–10) — pre: life stress ↓, confidence, motivation, anxiety ↓, note;
during/post: focus, commitment to falls, fear response ↓, confidence on routes, approach
mindset, note.

**Session Feel** — outcome {Excellent – exceeded plan, Good – as planned, Ok – mixed,
Poor – struggled, Incomplete – cut …}, stuck to plan? {Yes – fully, Mostly, Partially,
No – changed a lot}, enjoyment, satisfaction, effort/energy used (1–10, informational),
note.

**Wins & Reflect** — four prompts each with text + score: what felt good (score), what
felt off (severity ↓), what surprised you (impact), what would you change (priority);
overall session score (1–10); win size {Major send, Solid progress, Small win,
Insight / learning, Effort win}; win to bank (text).

**Rest Days** (independent tab, own date) — rest type {Full rest, Active recovery},
activity {None, Mobility / stretching, Walk / hike, Easy cardio, Yoga,
Massage / self-massage, Other}, sleep hours, sleep quality, mood, energy, motivation to
climb, life stress ↓, fingers/forearms/shoulders/wrists/skin ↓, note.

### Settings (named ranges on `Start Here`)
| Name | Default | Meaning |
|---|---|---|
| `LowMax` | 4 | LOW when lowest (flipped) score ≤ this |
| `WatchMax` | 6 | WATCH when lowest (flipped) score ≤ this |
| `AttnMin` | 8 | Reflect: NEEDS ATTENTION when severity or priority ≥ this |
| `NoteMin` | 6 | Reflect: WORTH NOTING when severity or priority ≥ this |
| `TrendDelta` | 0.5 | Trend arrow threshold (last-4 avg vs previous-4 avg) |

"Flip" for ↓ items is `11 − x`.

### Computed values (rules)
- **Wellbeing pre status**: needs all 3 of sleep quality/mood/energy; `min ≤ LowMax → LOW`,
  `≤ WatchMax → WATCH`, else GOOD. **Post status**: min(11−fatigue, post mood, recovery).
  **Wellbeing status** = worse of pre/post. **Wellbeing score** = mean of the 6 items
  (fatigue flipped), only when all 6 present, rounded to 1 decimal.
- **Physical readiness** = `11 − mean(pre soreness)`; **Physical status** from the
  *max* pre soreness: `≥ 11−LowMax (7) → LOW`, `≥ 11−WatchMax (5) → WATCH`. Post soreness
  is recorded but not scored.
- **Mental score** = mean of the 9 items with ↓ flipped (requires all 9).
  **Mental status** = min over present items (missing treated as 10), same bands.
- **Feel score** = mean(enjoyment, satisfaction); **Feel status** from min of the two.
- **Overall score** = mean of Wellbeing score, Physical readiness, Mental score, Feel score.
  **Overall status** = worst of the four statuses.
- **Reflection status**: severity or priority ≥ AttnMin → NEEDS ATTENTION; ≥ NoteMin →
  WORTH NOTING; else GOOD.
- **Rest-day wellbeing score** = mean(sleep q, mood, energy, motivation, 11−stress);
  body readiness = 11 − mean(soreness); statuses as above; rest-day status = worse of both;
  days since last climb.
- **Log check**: lists incomplete classes (Wellbeing, Physical needs all 10, Mental, Feel, Reflect).
- **Summary – Recent**: last session date / "N days ago", latest overall status, weakest
  class, count of LOW sessions in last 14 days, **suggested next session**:
  - LOW latest or ≥ 2 LOW in 14 days → *RECOVER — rest day or easy technical climbing…*
  - WATCH → *MODERATE — train as planned but cap the intensity…*
  - GOOD → *GREEN LIGHT — good window for quality work…*
  - plus last 4 sessions side by side, top-3 reflections of the last 2 weeks, recent rest days.
- **Summary – Trends**: per class latest status/score, avg last 4 vs previous 4, direction
  (▲/▼/►), LOW count in last 12; monthly averages (last 6 months); charts of the last 12 sessions.
- **Log Search**: keyword over all text fields + filters (date range, type, in/outdoor,
  weekday, status class, status value), newest first, max 40 results.

---

## 2. `Fear_of_Falling_Tracker.xlsx`

12-week program, starting 12 Oct 2026, in three phases: Foundations (W1–4), Variability (W5–8),
Transfer (W9–12). Sessions are labelled `W{n} G1`, `W{n} G2`, `W{n} Sat`, `W{n} Sun`
(4 per week).

- **Fear Map** — 11 scenarios × {priority (Base/Medium/High/High (reasonable)/Highest),
  Week 0 score (pre-filled), Week 8, Week 12 (0–10)}; deltas W0→W8, W8→W12; "where in the
  plan" text.
- **Fall Ladder** — 7 tracks (A Overhang, B Vertical, C Slab outdoors, D Lateral/Pendulum,
  E Pump/Doubt/Clipping, F Belayer, G Combined), 40 rungs total, each with description,
  target week(s), cleared? (Y), date cleared, notes. Per-track progress totals.
- **Session Log** — one row **per fall**: date, session label, rung (e.g. `A3`),
  level L1–L4, predicted % hurt, predicted % out of control, peak fear (0–10),
  BERP (0–4), soft catch (Y/N), what happened / learned.
- **20Q Scores** — per session, Q1–Q20 (1–5, 5 = best, blank = n/a) in 6 categories:
  Stress Q1–5, Technique Q6–10, Terrain Q11–12, Thoughts Q13–16, Belayer Q17–18,
  Commitment Q19–20. Averages per category and overall; weekly category averages.
- **Progress** — weekly manual metrics (falls taken, peak fear high, avg BERP,
  committed attempts, off-wall days, rungs cleared, notes) — *most of these are derivable
  from the Session Log*; weekly category trends from 20Q; weekly review journal
  (4 questions); fear & BERP trend chart.

### Rules (from `Guide`)
- **Advance** (clear rung): BERP ≥ 3 AND peak fear ≤ 5 on **two consecutive tries**, with a
  soft catch.
- **Hold**: BERP 2–3 OR fear 6–7 OR only one good try → repeat rung.
- **Step back**: fear ≥ 8 OR BERP ≤ 1 OR rough catch OR tired → stop; drop one rung next session.

---

## 3. `Shoulder_Program_Tracker_Fixed.xlsx`

12-week plan, start date 13 Oct 2026 (setting on `Start Here`). Blocks: 1 Calm and control
(RPE 5–6, W1–4), 2 Build strength (RPE 7, W5–8), 3 Endurance and transfer (RPE 6–7,
W9–12); weeks 4, 8, 12 are lighter.

- **Plan** — 17 exercises (P1–P3 primer, A1–A7 session A, B1–B7 session B), each with a
  prescription per week (e.g. `3×8`, `3×20 s`, `Skip`, `—`) and a load rule.
- **Session Log** — pre-generated row per exercise per week (204 rows): week, session, ID,
  exercise (lookup), prescribed (lookup), date, actual sets×reps, load kg, RPE (1–10),
  movement quality {Clean, Some shrug/compensation, Stopped early, Skipped},
  pain during (0–10), notes.
- **Check-in** — one row per climbing/training day: date, week (auto from start date),
  activity {Climbing indoor, Climbing outdoor, Hangboard, Session A, Session B, Rest day},
  primer done?, upper-trap fatigue, front-shoulder pain during, front-shoulder pain next
  morning, pec fatigue (0–10, lower better), shrug/elbow flare {Rarely, Sometimes, Often},
  red-flag symptom?, hardest grade attempted, attempts before stopping, main reason stopped
  {Upper traps, Front-shoulder pain, Fingers, Skin or tweak, Other, Did not stop}, notes.
  *Overlaps with the Journal (date, activity, grade).* Grade values are mixed (`7a`, `5b`,
  but also `6`, `5`).
- **Retests** — 14 measures at Start / end W4 / W8 / W12 with change W12 − start.
- **Dashboard / Trends** — per week: log completion %, sessions with primer, averages of
  the four symptom scales, green/yellow/red day counts, review flags; latest vs first week.

### Rules
- **Status**: red flag → RED; `max(pain during, pain next AM) ≥ 5` → RED; `≥ 3` → YELLOW; else GREEN.
- **Action** text per status (do not progress / hold-reduce / progress if quality good).
- **Review flag** (needs the previous rows): red flag → REVIEW NOW; pain ≥ 5 → REVIEW NOW;
  pain ≥ 3 → REVIEW; next-AM pain > previous and ≥ 2 → REVIEW (rising);
  three non-decreasing next-AM values ending ≥ 2 → REVIEW (repeated upward trend); else OK.

---

## 4. Pain points that motivate the app
1. Row-linking across tabs is fragile; capacity is fixed (300 / 144 / 208 rows).
2. Charts are static, fixed windows (last 12 sessions, last 6 months).
3. No cross-workbook analysis (e.g. fear vs sleep, shoulder pain vs session effort).
4. Duplicate entry (Shoulder check-in repeats Journal data; Fear "Progress" re-types
   numbers derivable from the fall log).
5. Program rules (ladder advancement, review flags) are described in text but only partly automated.
6. Changing what is tracked means editing dozens of formulas.
