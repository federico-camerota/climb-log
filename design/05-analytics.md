# 05 · Analytics and decision support

All analysis runs in the backend on the cached records, in plain Python with scipy for the
distributions (D-087, no pandas). The frontend renders
the results with ECharts. The Explore page has a time-range selector (7 d / 30 d / 90 d / all /
custom) and filters (module-specific choices such as session type, indoor/outdoor) for every
tab (D-095, D-096); dashboard charts show their view's fixed span, the score line with a range
picker and the bars with a zoom slider (D-083, D-091), without filters: to filter, use Explore
(decided after the M1–M4 audit). A "program run" range comes with the programs (M5).

## 0. Small-data honesty
Data starts at 2026-10. Many analyses only become meaningful after weeks or months, so:
- every statistic shows **n**; correlations show a 95% CI and are greyed out under a
  minimum n (setting, default 10);
- "insights" (automatic findings) require n ≥ `insight_min_n` and |effect| above a threshold,
  and are phrased descriptively ("sessions after < 7 h sleep: feel score 6.1 vs 7.3, n = 9 vs 14");
- no causal language.

## 1. Metric layer
Every numeric field and derived numeric field of every entity is a **metric** with an id
like `journal.session.wb_score` (the module as named in the app config); every choice field
is a **filter**. Done (D-090, #97): `analytics/metrics.py`, `GET /api/metrics` (the catalogue:
label, section, unit, range, direction) and a query in the URL, so a view can be bookmarked:

```
GET /api/metrics/query?metric=journal.session.wb_score&metric=shoulder.checkin.pain_next_am
    &start=2026-10-01&end=2026-12-31          # default: the first record … today
    &group=week                               # none | day (default) | week | month
    &agg=mean                                 # mean | min | max | sum | count | latest
    &rolling=4&lag=1
    &filter=journal.session.session_type=Climbing&filter=journal.session.session_type=Hangboard
```

The answer: `points` (start, end, label: `2026-10-30`, `2026-W44`, `2026-10`; a record's key
with `group=none`) and per metric its `values`, the `n` behind each value, the `rolling`
mean and its status `bands` when a dashboard line draws it with bands (the class scores'
LOW/WATCH/GOOD, from the settings; D-095). `group=none` is one point per record (metrics of one entity); day points are the days
with a record, week (from Monday) and month points run without gaps. Cross-module joins are
**by calendar day** (D-088); `lag=k` reads every metric after the first k days later ("pain
next morning" joined to the previous day's session). A filter applies to its entity's metrics.
`program_week` grouping comes with the program modules (M5). A field's values dated before
its `since:` are left out (03 §2.2), as in the formulas and the dashboard.

## 2. Parity analyses (from the current sheets)
- Status board: latest status and score per class, average of the last 4 vs the previous 4,
  trend arrow (`TrendDelta`), LOW count in the last 12. Done (D-083, #77): as the legacy
  formulas, checked against them on LibreOffice (`tests/test_views_parity.py`): the last 12
  sessions up to the day, averages of the values present rounded to one decimal (half away
  from zero), the previous average from 5 sessions on, ▲ when the change ≥ `trend_delta`,
  ▼ when ≤ −`trend_delta`. One difference: a day's second session counts with its own values
  (the legacy MATCH by date read the first one twice).
- Last N sessions side by side (N selectable, not fixed at 4). Done (D-084, #78): 4, 8 or 12,
  with the legacy rows and the latest session's notes.
- Monthly averages (any range, not just 6 months). Done (D-084, #78): 6, 12, 24 or all months,
  as the legacy formulas (checked on LibreOffice): sessions logged, each class's average, the
  overall as the average of the class averages, LOW sessions, rest days and their wellbeing.
- Top reflections of the last 14 days (by score) and reflections needing attention. Done
  (D-084, #78): per prompt the top 3 by score then the newest, as the legacy lists.
- Rest-day log with status and days since the last climb. Done (D-084, #78): the last 14 days,
  newest first, with the averages and the latest rest-day note.
- Log check (incomplete records): per day on Today (D-080) and as a column on Records
  (D-081); a to-do list of every incomplete record is M6.
- Search across all text fields with filters (all modules, highlighted matches, no 40-row cap).
- Shoulder weekly dashboard (completion %, primer, symptom averages, G/Y/R days, review flags).
- Fear: per-track rung progress, Fear Map deltas, 20Q category averages per session and week.

## 3. New analyses

### 3.1 Journal / training
- **Calendar heatmap** (GitHub-style): each day coloured by overall status (any metric:
  backlog);
  rest days and program sessions shown as markers. Click a day to open its records (done,
  D-098).
- **Trend lines with bands**: any metric with a rolling mean and the LOW/WATCH bands shaded.
- **Pre → post deltas**: how a session changes mood, soreness per body part (paired dot
  plot), by session type.
- **Body soreness map**: heatmap of body part × week (pre and post), plus a body silhouette
  for "today".
- Done (D-093, #100), the journal's `progress` view: `pre_post` (mood and each body part's
  soreness before → after: means, change and n over the sessions with both answers, per
  session type) and `body_heatmap` (soreness by body part and week, before sessions, after
  them and on rest days). A body part counts from its `since:` date; a retired one shows while
  the range has values for it. The body silhouette went to the backlog.
- **Training load**:
  - session load = duration × effort (session-RPE method);
  - weekly load, **acute:chronic workload ratio** (7 d / 28 d, EWMA variant),
    **monotony** and **strain** (Foster);
  - sessions per week, climbing days vs rest days, longest streaks.
  - The ACWR is shown as context with zones, not as a hard rule.
  - Done (D-092, #99): the `training_load` widget in the journal's `load` view (Dashboards →
    load): weekly load (a session missing duration or effort counts as 0 and the week says
    so), sessions and days trained, rest days, finger training on a chart of its own (sets x
    effort, other units, not in the ratio; a session without effort is flagged too), ACWR
    from the 28th day on (both averages started at the first 28 days' mean, so a steady load
    reads 1) with zones 0.8 / 1.3 / 1.5, monotony and strain per week, current and longest
    streaks; sessions per week by type as `weekbars`.
- **Recovery patterns**: performance metrics (feel score, overall score, hardest grade) vs
  days since the previous session (box plot), vs rest-day type before it, vs weekday.
- **Grades**: hardest grade over time (numeric index via the grade parser, `climblog/grades.py`:
  French 6a = 30 with one step per letter or `+`, gym = the number; French and gym on separate
  axes, never converted, D-017/D-047), grade pyramid by period, indoor vs outdoor, by venue.
  Done (D-094, #101), in the `progress` view: the hardest grade *tried* per session over time
  (French one series, gym one series per venue, on their own axes), sessions by hardest grade
  tried per month, and by setting and venue (sessions, hardest, median; gym grades always per
  venue). Values typed in the sheet that aren't grades are counted on the card.
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
- Done (D-096, #103), on the Explore page: **Two metrics** (scatter with the least-squares
  line, Spearman and Pearson r with 95% CIs, n, Y read 0–31 days later; under `min_n` greyed
  with a warning), **Matrix** (2–12 metrics, Spearman or Pearson, per day, cells under
  `min_n` empty) and **What goes with a good session** (feel score by default, any score
  picked; each pre-session metric ranked by |r|, the too-few ones last), each over its own date
  range. "Associations, not causes" on every tab; `[analytics] min_n` in the app config
  (default 10). "Predicts" became "goes with": no causal words. After the live
  test: the pair's points can be per record, day, week or month (each a period's means);
  each tab has its own date range and filters (a filter for each choice field of its metrics'
  entities, kept in the URL under the tab's prefix: `pair-`, `matrix-`, `good-`); when the 95% interval includes 0 the words add "could be none"; repeated
  labels are told apart as on Over time.

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
3. Training load: ACWR above the upper zone → suggest moderate (soft signal). Backlog
   (`07-roadmap.md`): the ratio is on the `load` dashboard (D-092), not in the advice yet.
4. Fear program: what is planned this week (target rungs not yet cleared, the rung to repeat
   or step back to).
5. Program schedule: which shoulder session (A/B, prescription for this week) is due.
6. Personal patterns (when enough data): e.g. "your feel score after ≥ 2 rest days averages +0.8".
   M6, with the insights feed.

Output: a headline (RECOVER / MODERATE / GREEN LIGHT), a suggested session content
(e.g. "Shoulder session B (W2 prescription) + Fear rungs A3, F2 indoor"), and reasons with
links (the reasons are done, D-076; links to the records behind them: M6). Logic lives in
config/plugins so it can evolve.

## 5. Exports
- Any chart: PNG/SVG; any table: CSV.
- Period report (week/month/program run) as a printable HTML page.
