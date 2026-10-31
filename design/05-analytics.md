# 05 · Analytics and decision support

All analysis runs in the backend on cached DataFrames (pandas/scipy). The frontend renders
the results with ECharts. Every chart has a time-range selector (7 d / 30 d / 90 d /
program run / all / custom) and filters (module-specific choices such as session type,
indoor/outdoor, venue, weekday).

## 0. Small-data honesty
Data starts at 2026-10. Many analyses only become meaningful after weeks or months, so:
- every statistic shows **n**; correlations show a 95% CI and are greyed out under a
  minimum n (setting, default 10);
- "insights" (automatic findings) require n ≥ `insight_min_n` and |effect| above a threshold,
  and are phrased descriptively ("sessions after < 7 h sleep: feel score 6.1 vs 7.3, n = 9 vs 14");
- no causal language.

## 1. Metric layer
Every numeric field and derived numeric field of every entity is a **metric** with an id
like `journal.session.wb_score`. A metric query:

```json
{ "metrics": ["journal.session.wb_score", "shoulder.checkin.pain_next_am"],
  "range": {"from": "2026-10-01", "to": "2026-12-31"},
  "group": "day | week | month | program_week | none",
  "agg": "mean | min | max | sum | count | latest",
  "rolling": 7,
  "filters": {"journal.session.session_type": ["Climbing"]} }
```

Cross-module joins are **by date** (and optionally with a lag: "pain next morning" joined to
the previous day's session). That is all the explorer needs.

## 2. Parity analyses (from the current sheets)
- Status board: latest status and score per class, average of the last 4 vs the previous 4,
  trend arrow (`TrendDelta`), LOW count in the last 12.
- Last N sessions side by side (N selectable, not fixed at 4).
- Monthly averages (any range, not just 6 months).
- Top reflections of the last 14 days (by score) and reflections needing attention.
- Rest-day log with status and days since the last climb.
- Log check (incomplete records) is shown as a to-do list.
- Search across all text fields with filters (all modules, highlighted matches, no 40-row cap).
- Shoulder weekly dashboard (completion %, primer, symptom averages, G/Y/R days, review flags).
- Fear: per-track rung progress, Fear Map deltas, 20Q category averages per session and week.

## 3. New analyses

### 3.1 Journal / training
- **Calendar heatmap** (GitHub-style): each day coloured by overall status or any metric;
  rest days and program sessions shown as markers. Click a day to open its records.
- **Trend lines with bands**: any metric with a rolling mean and the LOW/WATCH bands shaded.
- **Pre → post deltas**: how a session changes mood, soreness per body part (paired dot
  plot), by session type.
- **Body soreness map**: heatmap of body part × week (pre and post), plus a body silhouette
  for "today".
- **Training load**:
  - session load = duration × effort (session-RPE method);
  - weekly load, **acute:chronic workload ratio** (7 d / 28 d, EWMA variant),
    **monotony** and **strain** (Foster);
  - sessions per week, climbing days vs rest days, longest streaks.
  - The ACWR is shown as context with zones, not as a hard rule.
- **Recovery patterns**: performance metrics (feel score, overall score, hardest grade) vs
  days since the previous session (box plot), vs rest-day type before it, vs weekday.
- **Grades**: hardest grade over time (numeric index via the grade parser, `climblog/grades.py`:
  French 6a = 30 with one step per letter or `+`, gym = the number; French and gym on separate
  axes, never converted, D-017/D-047), grade pyramid by period, indoor vs outdoor, by venue.
- **Venue/partner view**: sessions and average feel by venue/partner.
- **Wins timeline**: banked wins by size, filterable, for a motivation feed.
- **Reflection themes**: frequency of words/keywords in "what felt off" / "what to change"
  (simple tokenisation with an Italian+English stopword list; a word cloud is optional, a
  bar chart is preferred).

### 3.2 Correlation explorer (cross-module)
- Pick X and Y metrics (any module), an optional **lag** (Y at day+k), and grouping.
  The result is a scatter plot with a regression line, Pearson and Spearman r, CI and n.
- **Correlation matrix** heatmap for a chosen set of metrics (Spearman default), with
  cells hidden under the minimum n.
- **"What predicts a good session?"**: ranked list of single-metric associations with the
  overall or feel score (pre-session metrics only, so it is usable *before* climbing).
  Later, an optional regularised regression (statsmodels/sklearn) once n ≥ ~40.

### 3.3 Fear of Falling
- Fall log: peak fear and BERP per fall over time; **predicted vs actual** (predicted
  % hurt / % out of control vs peak fear: calibration of expectations, Q16 territory).
- Fear vs BERP scatter coloured by rung track; soft-catch rate.
- Ladder view: tracks as rows, rungs as cells (cleared / in progress / target week passed),
  with the plan's target week overlaid.
- **Rung advancement assistant** (plugin): after each fall entry, evaluate the
  Advance/Hold/Step-back rule for that rung and propose "mark A3 cleared" or "next session: drop to A2".
- Fear Map radar (W0 vs W8 vs W12), deltas table.
- 20Q: category radar per week; category trends; lowest-scoring questions recently.
- Weekly metrics (falls taken, peak fear max, avg BERP, committed attempts, rungs cleared)
  **derived automatically** from the fall log and journal.
- Cross-module: journal mental metrics (commitment to falls, fear response) vs fear-program
  metrics, to show transfer over time.

### 3.4 Shoulder
- Program grid: exercise × week, prescribed vs done, colour by movement quality; completion %.
- Symptom trends: the four scales with the status bands; G/Y/R days per week.
- Review-flag timeline with reasons.
- Load progression per exercise (kg / sets×reps parsed to total reps or time under tension).
- Retests: before/after table and slope chart.
- Cross-module: next-morning pain vs the previous day's journal session load, type,
  hardest grade and post shoulder soreness (lagged join).

### 3.5 Finger strength
- **Max hangs**: top added load (kg) over time, **split by protocol**
  (edge mm × grip × arms × hang time), because loads are only comparable within one protocol.
  (No % body weight: body weight is not logged for now, D-025.)
  The protocol in use is detected automatically, and old protocols can be shown faded.
- **Finger curls** (single-handed block, left and right logged separately): top load and estimated
  1RM (Epley) per hand over time; **left/right imbalance %** with a ±10% reference band; volume per session.
- Sets per week by session type; spacing between sessions; failed sets.
- Readiness (fingers/forearms/shoulders before) vs performance in that session; readiness and
  performance by **time of day** (optional start time); on days with both parts, how the first
  part affects readiness and loads in the second (D-032).
- Cross-module: finger readiness vs the climbing journal's finger soreness the day after;
  finger-strength sessions in the climbing journal's calendar and in the training-load totals
  (session RPE × an estimated duration, or set count).

### 3.6 Text (Italian notes)
- Search is **case- and accent-insensitive** (`perche` finds *perché*, `giovedi` finds
  *giovedì* and *giovedi'*), using Unicode normalisation + casefolding, with matches
  highlighted in the original text.
- Keyword/theme analysis uses Italian (and English) stopwords and the Snowball Italian
  stemmer (`piedi`/`piede`, `stanco`/`stanchezza` grouped), so the charts reflect your actual themes.

## 4. Next-session recommendation
Combines the module rules into one card. **The most conservative signal wins**, and every
input is listed as a reason:

1. Journal readiness rule (parity): RECOVER / MODERATE / GREEN LIGHT from the latest overall
   status and LOW sessions in the last 14 days, declared in the module YAML (D-071; done,
   D-076: `recommendation:` in `modules/journal.yaml`, `GET /api/recommendation?date=` gives each
   module's advice with its reasons). Combining several modules' advice comes with the second
   one (M5): each block already says its headline, so "the most conservative wins" can order
   them.
2. Shoulder: latest status / review flag (RED or REVIEW NOW → recover / avoid provocative climbing).
3. Training load: ACWR above the upper zone → suggest moderate (soft signal).
4. Fear program: what is planned this week (target rungs not yet cleared, the rung to repeat
   or step back to).
5. Program schedule: which shoulder session (A/B, prescription for this week) is due.
6. Personal patterns (when enough data): e.g. "your feel score after ≥ 2 rest days averages +0.8".

Output: a headline (RECOVER / MODERATE / GREEN LIGHT), a suggested session content
(e.g. "Shoulder session B (W2 prescription) + Fear rungs A3, F2 indoor"), and reasons with
links. Logic lives in config/plugins so it can evolve.

## 5. Exports
- Any chart: PNG/SVG; any table: CSV.
- Period report (week/month/program run) as a printable HTML page.
