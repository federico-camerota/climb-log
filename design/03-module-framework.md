# 03 · Module framework

Everything the app tracks is defined by **module definition files** (YAML) in `modules/`.
The app generates the following from them:
- the spreadsheet tabs and columns (and keeps them in sync),
- the logging forms,
- derived values (scores, statuses, flags),
- the module's dashboard,
- the metrics available in the analysis explorer.

The Climbing Journal, Fear of Falling and Shoulder Program are three modules. A future
program (e.g. finger strength, a trip, a project route) is a new YAML file.

> Design principle: **config for the common case, plugins for the exceptions.** The YAML
> vocabulary covers fields, simple formulas, threshold statuses, per-week programs and a
> library of standard widgets. Anything beyond that (e.g. "two consecutive tries" ladder
> logic, or a bespoke chart) is a named Python rule or React widget that the YAML references.

---

## 1. Concepts

| Concept | Meaning | Storage |
|---|---|---|
| **Module** | A self-contained tracker (journal or program) | one workbook (local or Google) |
| **Entity** | A kind of record, e.g. `session`, `rest_day`, `fall`, `checkin` | one tab, one row per record |
| **Field** | An input column: type, scale, direction, choices | one column |
| **Derived field** | Computed per record from fields (score, status) | computed by the app; also a generated formula column in the sheet (§2.2b) |
| **Reference table** | Static-ish data the program uses: exercises × weeks, ladder rungs, fear-map scenarios | one tab, editable |
| **Settings** | Tunable parameters (thresholds, start date) | `_settings` tab (key/value) |
| **Form** | How an entity is entered: sections, order, which phase (pre/post) | config only |
| **View** | The module dashboard: list of widgets bound to metrics | config only |
| **Rule** | Cross-record logic: flags, recommendations | config (simple) or plugin |
| **Program** | Optional block: start date, weeks, phases, light weeks; enables `week` | config + settings |

Every entity has a `date` (or datetime) and a **key**. The key is either natural
(`key: [date, session_no]`, typed by hand naturally) or a generated `id` (only for
entities with many records per day, such as falls; may be left blank by hand). The date is how modules join
for cross-module analysis and the "Today" flow.

**Split entities**: an entity can be stored across several tabs, one per section
(`sections.<name>.tab`). Each tab repeats the key columns. The app presents and edits it
as one record and joins the tabs on the key (used by the Journal session, D-006).

**Modules stay separate**: each module is its own workbook with its own data source.
Cross-module features (Today flow, correlations, shared/prefilled fields) only *read*
across modules. A record is always stored in exactly one module.

---

## 2. Module file shape

```yaml
module: shoulder                  # stable id (never change)
name: Shoulder program
version: 3                        # bump when you change the definition
kind: program                     # journal | program
description: 12-week shoulder capacity plan
status_levels: [GREEN, YELLOW, RED]  # best → worst: the order of `worst_of`

program:                          # only for kind: program
  start_date: {setting: start_date}
  weeks: 12
  phases:
    - {name: "Block 1 · Calm and control", weeks: [1, 4], note: "RPE 5-6"}
    - {name: "Block 2 · Build strength",   weeks: [5, 8], note: "RPE 7"}
    - {name: "Block 3 · Endurance and transfer", weeks: [9, 12], note: "RPE 6-7"}
  light_weeks: [4, 8, 12]

settings:
  start_date: {type: date, default: 2026-10-13, label: Program start date}
  yellow_min: {type: number, default: 3}
  red_min:    {type: number, default: 5}

scales:                           # reusable scale definitions
  pain:  {min: 0, max: 10, direction: lower_better}
  freq:  {type: ordinal, choices: [Rarely, Sometimes, Often], direction: lower_better}

entities:
  checkin:
    label: Check-in
    tab: checkins                 # sheet tab name
    date_field: date
    fields:
      date:            {type: date, required: true}
      activity:        {type: choice, choices: [Climbing indoor, Climbing outdoor, Hangboard, Session A, Session B, Rest day]}
      primer_done:     {type: bool}
      trap_fatigue:    {type: scale, scale: pain, label: Upper-trap fatigue}
      pain_during:     {type: scale, scale: pain, label: Front-shoulder pain during}
      pain_next_am:    {type: scale, scale: pain, label: Front-shoulder pain next morning, phase: next_day}
      pec_fatigue:     {type: scale, scale: pain}
      shrug_flare:     {type: choice, scale: freq}
      red_flag:        {type: bool, label: Red-flag symptom?}
      notes:           {type: text, multiline: true}
    derived:
      pain_max: "max(pain_during, pain_next_am)"
      status:
        when:
          - {if: "red_flag", then: RED}
          - {if: "pain_max >= settings.red_min", then: RED}
          - {if: "pain_max >= settings.yellow_min", then: YELLOW}
          - {if: "notnull(pain_max)", then: GREEN}
    rules:
      review_flag:   {plugin: shoulder.review_flag}   # needs previous rows → plugin or prev()
```

### 2.1 Field types
| type | Spreadsheet cell | Form control | Notes |
|---|---|---|---|
| `date`, `datetime`, `time` | ISO date / datetime | date picker | typed by hand: ISO or day-first (`24/10/2026`), never month-first (04 §3b) |
| `number` | number | numeric input | `min`, `max`, `step`, `unit` |
| `integer` | number | stepper | |
| `scale` | number | 1–10 (or other) segmented slider | references `scales:`; carries `direction` |
| `choice` | text | select / chips | `choices` or an ordinal `scale` (one of the two), `allow_other`, `choice_map` (legacy value → choice); read ignoring case and surrounding spaces |
| `multichoice` | `a; b; c` text | chips | |
| `bool` | `Yes`/`No` | toggle | accepts Y/N, TRUE/FALSE, Sì/Si, 1/0 on read, any case |
| `text` | text | input / textarea | `multiline`, searchable by default |
| `grade` | text | grade picker | `systems: [french, gym]`; the system is auto-detected among them (D-017) and parsed to a numeric index (D-047): French `6a` = 30, one step per letter or `+`; gym = the number; a slash grade `6a/6a+` sits halfway. `uiaa`, `yds`, `font`, `v` are not supported yet (load error) |
| `duration` | minutes (number) | h:mm input | |
| `ref` | id/key text | lookup select | references a reference-table key (e.g. ladder rung `A3`) |
| `percent` | number 0–100 | slider | |

Common field options: `label`, `help`, `required`, `default`, `phase` (`pre`, `post`,
`next_day`, `any`; drives the Today flow), `section` (form grouping), `retired: true`,
`renamed_from: old_key`, `hidden_in_form`, `searchable`, `optional: true` (a field you may
leave blank: its form still counts as done on Today, D-080; not with `required`).
`default` is what a blank cell means. `default: next` on an integer key field (set numbers)
makes a blank cell the row's position among the rows with the same other key parts, in sheet
order (D-050); it needs other key parts and an entity on one tab.

### 2.1b Field templates, conditional fields, child entities
- **Templates** are reusable field groups, e.g. the body-part list `soreness` (fingers,
  forearms, elbows, shoulders, neck/traps, wrists, skin), expanded wherever they are used
  (`ph_pre_`, `ph_post_`, rest-day `body_`). **Adding a body part is one line in the template**.
  Formulas refer to `fields(tag=soreness)`, not to named fields, so readiness, status, the
  log check and the body heatmap pick it up automatically. `since: <date>` marks when a field
  started being tracked: records before that date are not considered incomplete because of
  it, and charts start the series at that date.
- **Conditional fields**: `visible_if: "session_type == 'Max hangs'"` shows a field in
  forms only when the condition holds. In the sheet the column always exists. For hand
  entry it is simply left blank, and validation ignores it when the condition is false.
- **Child entities** (one-to-many): `parent: {entity: session, key: [...]}` declares, for
  example, many `set` rows per finger-strength session. The child tab repeats the parent key
  columns, so hand entry needs no ids. A child tab may **fix** part of the parent key
  (`parent: {key: [date], fixed: {session_type: Max hangs}}`): on `Hang sets` the session type
  is implied by the tab and isn't typed. Derived fields can use
  `parent.x` (a stored field of the parent row) and, on the parent, `children(set)` (one item
  per child row, for `count`) and `children(set).x` (the child rows' stored or derived values)
  with `count/sum/max/mean/min` (§2.3, D-045). A child row
  without a parent is a data issue with a one-click fix; its `parent.x` values are blank. In the formula compiler, children
  aggregates become `MAXIFS/SUMIFS/COUNTIFS` on the key columns.

**Rules checked at load (D-042):**
- *Templates*: `templates: {name: {field: …}}` at module level. A field entry
  `prefix_: {template: name, section: …, phase: …}` is replaced, in place, by the template's
  fields with keys `prefix_<field>`; it may set only `section` and `phase` (the template's
  fields cannot set `section`). Templates cannot use templates; an expanded key that collides
  with another field is an error. The loader returns the module with templates expanded.
  `template_from_reference` (fields from reference-table rows, e.g. 20Q) waits for M5.
- *Sections and tabs*: an entity has either one `tab` or sections that all have a `tab`
  (split). Sections without tabs only group fields in forms. In a split entity every non-key
  field names a section, the entity has a natural `key`, and `anchor_tab` (default: the first
  section's tab) is one of its tabs. Key fields are on every tab; `section: "*"` is allowed only
  on them. Tab names are unique across the module's entities (case-insensitive), are not
  `_meta`, `_settings`, `Summary` or `README`, and follow spreadsheet rules (1–31 characters,
  none of `[]:*?/\`).
- *Children*: one level only (a child cannot have children). The parent has a natural key;
  `parent.key` + `parent.fixed` are exactly that key; each `parent.key` field is in the child's
  key; `fixed` values must be valid choices.
- *Evolution*: key and required fields cannot be `retired`; `renamed_from` must not be a current
  field, and two fields cannot claim the same old key.
- *Conditions*: `visible_if` is an expression (§2.2) on the entity's own fields and settings that
  gives yes/no; it cannot use the field it belongs to. Comparing a choice field with a value that
  is not one of its choices is an error (`session_type == 'Max hang'`).

### 2.2 Derived fields: the expression language
A small, **safe** expression language evaluated per record (parsed with Python `ast` and
an allow-list; no `eval`; code in `climblog/expr/`, D-043):

- arithmetic `+ - * /` and unary `-`; comparisons `== != < <= > >=` (one per comparison:
  write `a < b and b < c`); `and/or/not`; `x if cond else y`; numbers, `'text'`, `True`/`False`
- field references (`pain_during`), `settings.x`; other records: `prev(x, n)`, `parent.x`,
  `children(e)` / `children(e).x`, `last(e.x, before=d)` (§2.3); `program.week`,
  `program.phase` (M5)
- functions: `mean(...)`, `min(...)`, `max(...)`, `sum(...)`, `count(...)` (aggregates; the
  first four take `missing_as=`), `round(x, n)` (halves away from zero, like the sheets),
  `concat(...)`, `flip(x)` (maps a scale value to its "higher is better" orientation:
  `scale.max + scale.min − x`, i.e. `11 − x` on 1–10, for a value on a lower-is-better scale;
  a value on a higher-is-better or neutral scale is left as it is, and values of mixed
  directions are an error), `flip_all(fields(...))` (each field turned by its own scale, D-056),
  `month(date)` (`2026-10`), `incomplete(Name=condition, ...)` (the names whose condition does
  not hold, `"Physical, Reflect"`, blank when all hold; the journal's Log check),
  `coalesce(...)`, `notnull(x)`, `all_present(...)`, `days_between(a, b)`,
  `weekday(date)` (`Mon` … `Sun`), `worst_of(a, b, ...)` (statuses, below)
- group helpers: `fields(section=pre, tag=soreness, type=scale)` returns the list of matching
  stored fields (each selector takes a name or a list, `section=[wb_pre, wb_post]`; all
  selectors must match), so formulas don't need to name every field (adding a soreness field
  updates them automatically). A list can be passed to the aggregates, `all_present`, `count`
  and `flip_all`. A record leaves out a field dated before its `since:`, and a `retired` field
  where it is blank (so old scores keep counting it, new records don't need it)
- `flip` needs to know the scale: its argument is a scale field, or `min/max/mean/round/coalesce`
  of values on one scale (`flip(max(fields(tag=soreness)))`); otherwise the module doesn't load

A **derived entry** is one of these shapes (D-044):

| Shape | Example | Result |
|---|---|---|
| expression | `pain_max: "max(pain_during, pain_next_am)"`, or `{expr: ..., require: ...}` | the expression's value |
| `bands:` thresholds | below | the label of the first band with `value ≤ le`, else the `else` label |
| `when:` cases | `{if: "red_flag", then: RED}`, …, `{else: GREEN}` | the label of the first true `if`, else the `else` label |
| `map_from:` | `{map_from: status, map: {RED: "Do not progress…", …}}` | the text for the value of a status or choice |
| deferred | `{plugin: ...}`, `{per_reference_group: ...}` | not computed yet (see below) |

```yaml
wellbeing_pre_status:
  bands_of: "min(sleep_quality, mood, energy)"
  require: "all_present(sleep_quality, mood, energy)"
  bands:
    - {le: settings.low_max,   label: LOW}
    - {le: settings.watch_max, label: WATCH}
    - {else: GOOD}
```

- `le` is a number or an expression (`settings.low_max`); `label`, `then` and `else` are
  labels, not expressions. `else` comes last; without it, no match gives a blank.
- **Statuses.** A `bands:` or `when:` result is a status on a level list, best first:
  the module's `status_levels:` (e.g. `[GOOD, WATCH, LOW]`, `[GREEN, YELLOW, RED]`), or another
  `*_levels` list named by `levels:` (`levels: reflect_levels`). Every label must be in that
  list, so a typo (`WACTH`) stops the module from loading. A result that is a message rather
  than a status says `type: text` (shoulder `review_flag`); its labels are then its only values.
- `worst_of(a, b, ...)` takes statuses on one level list and gives the worst (last in the list).
  Comparing a status with a label that is not in its list is an error (`overall_status == 'LOWW'`).
- An entry can read other derived values; they are computed first (the order follows what
  each entry reads, not the YAML order). A cycle is an error.
- **Deferred until their issue**: entries using `program.` or `reference.` (M5), `plugin:`
  entries, `per_reference_group`, and `fields(...)`
  in an entity with fields from a reference table (`template_from_reference`, M5). They are
  accepted but neither checked nor computed, and so is every entry that reads one of them.

Missing-value semantics follow the original sheets (D-043); a blank cell is "blank":

| Case | Result |
|---|---|
| arithmetic, `round`, `flip`, `days_between`, `weekday` with a blank input; division by 0 | blank |
| `<`, `<=`, `>`, `>=` with a blank | false (`pain_max >= settings.red_min` doesn't fire when nothing was logged) |
| `==`, `!=` | blank equals only blank (`quality != 'Skipped'` is true when quality is blank) |
| `and`, `or`, `not`, `if` | only a true value counts: a blank Yes/No counts as No |
| `mean/min/max/sum` | ignore blanks; all blank → blank (not 0) |
| `missing_as: 10` (`min(..., missing_as=10)`, as in the Mental status) | blanks count as 10, but all blank → still blank |
| `count` | number of filled values |
| `concat` | a blank adds nothing |
| `worst_of` | ignores blank statuses; all blank → blank (an empty section doesn't hide the others) |
| `require:` not true | blank |
| `bands:` with a blank `bands_of` | blank (not the lowest band, not the `else` label) |
| `when:` with no true `if` and no `else` | blank |
| `map_from:` with a blank or unmapped value | blank |

Expressions are checked when the module loads: unknown fields, settings and functions (with a
"did you mean" suggestion), type mismatches (`notes + 1`, `mood == 'x'`), and the position of
the problem in the text. In a derived entry, `require` and `if` must give yes/no, `bands_of`
and `le` a number, and every expression a single value (not a list of fields); `map` keys must
be values of the `map_from` status or choice, and a derived key cannot be a stored field. The check also gives each expression's result type, used for the
sheet column's number format (§2.2b), and the names it reads, which order the derived fields.

### 2.2b Derived fields are also compiled to spreadsheet formulas (D-018)
So the sheets stay informative **without the app** (e.g. hand-logging in Google Sheets
away from home), every derived field is, by default, also **compiled into a formula
column** in the sheet:

- The expression language is deliberately limited to constructs with a formula
  translation: `mean→AVERAGE`, `min/max→MIN/MAX`, `flip(x)→(max+min−x)`,
  `bands→IFS/nested IF`, `when→IFS`, `worst_of→` a nested IF over the status order,
  `all_present→COUNT(...)=n`, `weekday→TEXT/WEEKDAY`, `days_between→` subtraction,
  `prev(x)→` lookup of the row with the latest earlier date (`MAXIFS` + `INDEX/MATCH`),
  references to another section tab of a split entity → `INDEX/MATCH` on the key.
  Missing-value semantics are compiled as `IF(cell="", …)`, as in the legacy formulas.
- Target dialect: the common subset of **Google Sheets and Excel/LibreOffice**
  (no `LET`/`LAMBDA`, no ARRAYFORMULA), with per-row formulas.
- Settings referenced by formulas (`settings.low_max`) become references to the `_settings`
  tab (named ranges where the backend supports them), so changing a threshold in the
  sheet or in the app updates both.
- Per-field control: `sheet_formula: auto` (default), `sheet_formula: false` (app only),
  or `sheet_formula: "=..."` (hand-written override, with `{field}` placeholders).
  **Plugins are app-only** unless they provide an override.
- The **app never reads** formula columns as data. It computes everything itself from the
  raw inputs, and uses the formula results only for a **drift check**: a mismatch (e.g. a
  formula overwritten by hand) is reported as a data issue and repaired on the next schema sync.
  `climblog check` reports two kinds (`storage/drift.py`, D-054): a **changed formula** (the
  cell's formula is not the compiled one, or is gone in a row with data; `sync`, as
  `--apply` puts it back), compared as spreadsheets rewrite formulas on save (LibreOffice drops
  needless quotes around tab names and writes `TRUE()`); and a **different value** (the value
  the sheet last computed differs from the app's; `info`). Values are compared only where the
  sheet has one: openpyxl keeps no computed values, so after an app write there are none until
  the workbook is opened and saved in Excel or LibreOffice, and a blank cell can't be told
  from one not computed yet.
- **Dialect rules found in the mock-up** (`mockups/sheet-tabs.md`): in `.xlsx`, functions
  newer than Excel 2007 (`MAXIFS`, `MINIFS`, `IFS`, `XLOOKUP`, `CONCAT`, …) must be emitted with
  the `_xlfn.` prefix, or they show `#NAME?`. The Google API takes the plain name, so the
  compiler has a per-backend emitter. Every computed column gets an explicit number format
  derived from its result type (integer, decimal, text, date), because a date difference
  otherwise inherits the date format. Composite-key lookups (`children(...)`, references to
  another section tab, session checks) compile to `COUNTIFS`/`MAXIFS` on a hidden numeric
  `auto:_key` column (D-031), not to text keys (locale-dependent date formats) or `SUMPRODUCT`.
- Parity testing becomes stronger: the compiled formulas are evaluated by LibreOffice
  (headless) or read back from Google, and compared with the Python results on the same fixtures.

**How it compiles** (`climblog/modules/formulas.py`, D-053):
- Each value is compiled to its formula and the condition under which it is blank, kept apart,
  so the blank rules of D-043 cost one test at the top (`IF(COUNT(D3,E3,F3)=0,"",ROUND(11-
  AVERAGE(D3,E3,F3),1))`) instead of a wrapper around every part. Aggregates of plain cells use
  the native functions (they skip blanks and text); others add up `IF(x<>"",x,0)` terms.
  Every formula is blank until the row has a date, so the buffer rows show nothing.
- A stored field reads as the app reads it: a blank cell takes its `default:`, a Yes/No cell is
  yes for `Yes`, `Y`, `true`, `Sì`, `Si`, `1` or TRUE (any case), as are Yes/No settings.
- **Placement**: a derived field goes on the tab of what it reads on its record, or on the
  anchor tab when that is several tabs; a derived value is read from its own `auto:` column.
- **`auto:_key`** (hidden) = `INT(date)*10` + the code of the second key part: an integer (blank
  = its default) or a closed choice's position, 1-based (as in the mock-ups). A child's is its
  parent's (the key columns it repeats, plus `fixed`). Every tab of a split entity, a parent or a
  child gets one, and so does an entity using `prev`. Rows are looked up on it with
  `INDEX/MATCH`: fields on another section tab, `parent.x`; `prev(x)` takes the largest key below
  the row's; `children(e)` are `COUNTIFS`/`SUMIFS`/`MAXIFS`/… on the child's key column; soft-
  deleted rows are left out (`deleted` blank). `last(e.x, before=d)` takes the latest row dated
  before `d` (`until=d`: on or before), ordered by `auto:_key`, which an entity read by `last`
  gets when its key has more than the date (D-076). `window(e.x, days=n, until=d)` inside
  `count` (with or without `equals=`), `sum`, `min`, `max` and `mean` is `COUNTIFS`/`SUMIFS`/…
  on the date column (from `d - n` to `d`) and `deleted` blank.
- **App only** (no column, listed by `climblog module validate` as notes): plugins and entries
  of later milestones (unless they have a hand-written `sheet_formula`), `sheet_formula: false`,
  `prev(x, n)` with n > 1, `prev` on a child or with a choice in the key (the app orders it by
  name), keys of more than a date and one part, a second key part that is not an integer or a
  closed choice of at most 9 values, settings named like a cell (`a1`), `missing_as` or other
  values mixed with `children(...)`, and every entry reading one of these.
- `month(d)` is `YEAR(d)&"-"&RIGHT("0"&MONTH(d),2)` (no `TEXT()`, whose codes depend on the
  locale); `incomplete(...)` is `MID(IF(NOT(c1),", Wellbeing","")&…,3,999)`.
- Known limits: a key part of 10 or more collides in `auto:_key`; legacy values mapped by
  `choice_map` are not mapped in formulas; `concat` writes decimals as the sheet's locale does.
- `round` in the app works on 15 significant digits as the sheets do, so a mean of
  5.824999999999999 (5.825 on paper) rounds to 5.83 in both.
- **Parity test** (`tests/test_formula_parity.py`): fictional workbooks with random rows from
  fixed seeds (blanks, second sessions, sets, missing section rows) are recalculated by
  LibreOffice headless and every formula cell must equal the app's value. It runs when a
  working `soffice` is found (`CLIMBLOG_SOFFICE`, e.g. `snap run libreoffice`, with
  `CLIMBLOG_SOFFICE_TMP=build/lo-parity` for a snap) and is skipped otherwise, CI included
  (D-057): run it locally before a PR that changes formulas, expressions or sync.
  `CLIMBLOG_REQUIRE_SOFFICE=1` turns the skip into a failure. Hand-written formulas are not
  compared.

### 2.3 Cross-record rules
- **Declarative** (covers most cases; D-045):
  - `prev(x)`, `prev(x, n)`: `x` in the *n*-th previous record of the same entity, ordered by
    date, then key fields, then row. It is the previous *record*: if `x` is blank there, the
    result is blank (as the legacy sheets look at the row above). No previous record → blank;
    a record without a date has no previous record and is nobody's previous record. `x` can be
    a stored field or a derived value, but not the entry's own value (`prev(streak)` inside
    `streak` is not supported yet: its type would depend on itself).
  - `parent.x`, `children(e)`, `children(e).x`: the parent row and the child rows (§2.1b).
    Children are matched on the parent key columns they repeat and on `fixed`; no children →
    an empty list (`count` 0, `max`/`sum` blank).
  - `last(e.x, before=d)`: `x` in the latest record of entity `e` dated strictly before `d`
    (e.g. days since the last climb on the rest-day tab:
    `days_between(last(session.date, before=date), date)`). None → blank. `last(e.x, until=d)`:
    dated on or before `d`. Records of one day are ordered by key (a day's second session is
    later than its first).
  - `window(e.x, days=n, until=d)`: `x` in every record of `e` dated from `n` days before `d` to
    `d` itself (`days=14`: 15 calendar days, as the legacy `>= TODAY()-14`), for an aggregate:
    `count(window(session.overall_status, days=14, until=date), equals='LOW')`, `max(window(…))`.
    `count(…, equals=v)` counts the values equal to `v` (D-076).
  - What they read: `prev` and `children(e).x` read stored and derived values; `parent.x` and
    `last(e.x, ...)` and `window(e.x, ...)` read stored fields only. So child entities are
    computed before their parents, and an entity's rows in date order
    (`climblog/modules/compute.py`). The recommendation, computed after every entity, reads
    derived values too.
- **Recommendation** (`recommendation:`, D-071, D-076): the next-session advice for a day, so the
  app and the sheet's Summary tab share one definition (no plugin).
  ```yaml
  recommendation:
    label: Suggested next session
    values:                       # derived entries of the day asked: `date` (TODAY() in the sheet)
      latest_status: "last(session.overall_status, until=date)"
      low_sessions: "count(window(session.overall_status, days=14, until=date), equals='LOW')"
    rules:                        # the first that holds; the last may leave out `if`
      - {if: "latest_status == 'LOW' or low_sessions >= 2", headline: RECOVER, message: rest…}
      - {message: Fill in the remaining tabs…}
    reasons: {low_sessions: LOW sessions in the last 14 days}   # shown with it, in order
  ```
  `values` are ordinary derived entries (`expr`, `when`, `bands`, …) that read the records with
  `last` and `window` (stored and derived values); `rules[].if` reads them and `date`. The app
  answers `GET /api/recommendation?date=` (`modules/recommend.py`); the sheet formulas come from
  `recommendation_formulas` (each value, `headline`, and `text` = "RECOVER — …", as the legacy
  cell), checked by `tests/test_recommend_parity.py` with LibreOffice, also against the legacy
  Summary formulas.
- **Plugin**: `{plugin: module.rule_name}`, a Python function
  `(records: DataFrame, ctx) -> Series | list[Flag]`. Example: fall-ladder advancement
  (two consecutive falls on the same rung with BERP ≥ 3, fear ≤ 5, soft catch).

### 2.4 Program block
Enables `program.week` (from `start_date`), `program.phase`, `program.is_light_week` on
every record, week-based widgets, and **prescriptions** via a reference table keyed by
item × week. The program can be restarted (new start date = new *run*). Every record
stores `run` so you can compare run 1 and run 2 of the same program.

### 2.5 Reference tables
```yaml
reference:
  exercises:
    tab: plan
    key: id
    fields:
      id: {type: text}
      name: {type: text}
      session: {type: choice, choices: [Primer, A, B]}
      load_rule: {type: text}
    per_week: prescription        # adds columns w1..wN of type text
```
They are seeded by the importer (or from a `seed:` block / CSV) and editable in the app
or the sheet. Entities refer to them with `ref` fields (`exercise_id`, `rung`).

### 2.6 Forms and the Today flow
```yaml
forms:
  pre_session:  {entity: session, sections: [session_info, wellbeing_pre, physical_pre, mental_pre], phase: pre}
  post_session: {entity: session, sections: [wellbeing_post, physical_post, mental_post, feel, reflect], phase: post}
```
The **Today** page asks each active module "what is due for this date?" and builds one
flow. For example: Journal pre-session, then Shoulder primer checkbox, then (after climbing)
Journal post-session, Fear falls for today, and Shoulder check-in. The next morning a
reminder card asks for "pain next morning" (`phase: next_day`).
**Shared fields** avoid duplicate entry: a field may declare
`from: journal.session.hardest_grade` and is prefilled (editable) from the same-day record
of another module.

### 2.7 Views (dashboards)
A view is a list of widgets from a **widget library**, each bound to metrics:

```yaml
views:
  overview:
    - {widget: kpi,       metric: checkin.status, agg: latest, label: Today}
    - {widget: line,      metrics: [checkin.pain_during, checkin.pain_next_am], x: date, rolling: 7}
    - {widget: weekbars,  metric: checkin.status, agg: count_by_value}
    - {widget: program_grid, reference: exercises, entity: exercise_log}
    - {widget: before_after, reference: retests}
```

Planned widget library: `kpi`, `status_strip`, `line` (with rolling mean, bands for
thresholds), `bars`/`weekbars`, `stacked`, `heatmap_calendar`, `box_by` (distribution by
weekday/type/…), `scatter` (with trend line), `radar`, `delta_table`, `table`,
`text_feed` (notes/reflections), `ladder` (rung progress), `program_grid` (prescribed vs
done), `before_after`. Custom widgets are registered by name in the frontend.

Every numeric/scale field and derived numeric field is automatically a **metric** in the
analysis explorer (see `05-analytics.md`). No view config is needed for that.

---

## 3. Evolving a module (the flexibility contract)

| Change | What you do | What the app does |
|---|---|---|
| Add a field | add a line under `fields:` | appends a column to the tab (header + validation); old rows blank |
| Remove a field | set `retired: true` | hides it from forms/views; **column and data kept**; still visible in history and exports |
| Rename a field | new key + `renamed_from: old` | renames the header in the sheet; data preserved |
| Change choices | edit `choices` | old values still valid on read and shown as "legacy" values; optional value mapping `choice_map:` |
| Change scale range | new scale + new field (recommended) | avoids mixing incomparable values; an explicit `rescale:` transform is possible |
| Change a threshold | edit in Settings UI (writes `_settings`) | instant recompute |
| Change a formula | edit `derived:` | recomputed for all history in the app; formula columns regenerated in the sheet on sync |
| New program | new YAML file + `climblog module init` | creates the workbook/tabs locally or in Google |

`climblog check [MODULE...]` (D-051) diffs each configured YAML against its workbook and
lists the differences, changing nothing: `sync` ones (a missing tab, column or system column,
a pending `renamed_from` rename, `_meta` missing or behind the YAML version) are what schema
sync applies (`climblog check --apply`, D-052), `info` ones need no change (a column the YAML
doesn't know, a setting without a `_settings` row), `error` ones need a person (a workbook of
another module, `_meta` newer than the YAML, unreadable header rows, both the old and the new
column of a rename). It exits with 1 unless only `info` is left. Retired fields need no column;
formula columns are checked like the others, and drifted formulas are reported (D-054). It
will also run on startup (#25).
`climblog check --apply` syncs each module, then checks again: it creates the workbook if the
configured file doesn't exist, missing tabs and columns, `_settings` rows (with the defaults)
and `_meta`, applies renames, and rewrites the dropdowns. A module with an `error` difference
is not synced. Sync applies only **additive** changes. It never deletes columns or data.
Destructive operations (dropping a column) are a separate explicit command. For a local
module, `--apply` replaces `climblog module init` (in the table above).

The `version` of the module and the schema it was synced with are stored in `_meta`, so
the app can tell that the sheet was last synced with v2 while the YAML is now v3.

## 4. Validation of the YAML itself
Module files are read as YAML 1.2 (ruamel.yaml: an unquoted `No` stays text) and validated
against a pydantic meta-schema at load (`climblog/modules/`, D-041). Unknown keys are errors.
Problems are reported together, with file, line, column and path, in two passes: first every
shape problem (unknown keys, wrong types), then, once the shape is valid, every reference
problem (unknown scale, key field that does not exist), e.g.
`shoulder.yaml:42:7 entities.checkin.fields.trap_fatigue.scale: unknown scale 'pian' (known: pain, rpe)`.

- `climblog module validate FILE...` checks files and prints the problems (exit code 1 if any).
- `climblog module schema` prints the JSON Schema. It is committed as `modules/module.schema.json`
  (a test keeps it current); a first line `# yaml-language-server: $schema=<path to it>` gives
  autocompletion and inline errors in VS Code (YAML extension).
- Blocks of later milestones (`program`, `reference`, `forms`, `views`, `aggregates`, `rules`)
  are accepted as they are until their issue adds the checks; `recommendation` is checked
  (D-076).
  Templates, split and child entities are checked (§2.1b), and so are derived fields (§2.2),
  except the deferred ones.

## 5. Future: editing modules from the UI
Phase 2 option: a "Module editor" page (add/retire fields, edit choices and thresholds)
that writes the YAML. Until then, YAML is edited by hand, with validation and a clear diff
preview before a sync touches the sheet.
