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
| `date`, `datetime`, `time` | ISO date / datetime | date picker | |
| `number` | number | numeric input | `min`, `max`, `step`, `unit` |
| `integer` | number | stepper | |
| `scale` | number | 1–10 (or other) segmented slider | references `scales:`; carries `direction` |
| `choice` | text | select / chips | `choices` or an ordinal `scale` (one of the two), `allow_other`, `choice_map` (legacy value → choice) |
| `multichoice` | `a; b; c` text | chips | |
| `bool` | `Yes`/`No` | toggle | accepts Y/N, TRUE/FALSE on read |
| `text` | text | input / textarea | `multiline`, searchable by default |
| `grade` | text | grade picker | `systems: [french, gym]` (any of `french`, `uiaa`, `yds`, `font`, `v`, `gym`); the system is auto-detected among them (D-017) and parsed to a numeric index |
| `duration` | minutes (number) | h:mm input | |
| `ref` | id/key text | lookup select | references a reference-table key (e.g. ladder rung `A3`) |
| `percent` | number 0–100 | slider | |

Common field options: `label`, `help`, `required`, `default`, `phase` (`pre`, `post`,
`next_day`, `any`; drives the Today flow), `section` (form grouping), `retired: true`,
`renamed_from: old_key`, `hidden_in_form`, `searchable`.

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
  `parent.x` and, on the parent, `children(set).x` with `count/sum/max/mean`. A child row
  without a parent is a data issue with a one-click fix. In the formula compiler, children
  aggregates become `MAXIFS/SUMIFS/COUNTIFS` on the key columns.

### 2.2 Derived fields: the expression language
A small, **safe** expression language evaluated per record (parsed with Python `ast` and
an allow-list; no `eval`):

- arithmetic `+ - * /`, comparisons, `and/or/not`, literals
- field references (`pain_during`), `settings.x`, `program.week`, `program.phase`
- functions: `mean(...)`, `min(...)`, `max(...)`, `sum(...)`, `count(...)`,
  `round(x, n)`, `concat(...)`, `flip(field)` (maps a scale value to its "higher is better" orientation:
  `scale.max + scale.min − x`, i.e. `11 − x` on 1–10), `coalesce(...)`, `notnull(x)`,
  `all_present(...)`, `days_between(a, b)`, `weekday(date)`
- group helpers: `fields(section=pre, tag=soreness)` returns the list of matching fields,
  so formulas don't need to name every field (adding a soreness field updates them automatically)
- `when:` lists for categorical results (first match wins), and
  `bands:` for thresholds:

```yaml
wellbeing_pre_status:
  bands_of: "min(sleep_quality, mood, energy)"
  require: "all_present(sleep_quality, mood, energy)"
  bands:
    - {le: settings.low_max,   label: LOW}
    - {le: settings.watch_max, label: WATCH}
    - {else: GOOD}
```

- `worst_of(a, b, ...)` over statuses, using the status order declared in
  `status_levels:` (e.g. `[GOOD, WATCH, LOW]`, `[GREEN, YELLOW, RED]`).

Missing-value semantics follow the original sheets: `mean` ignores blanks, `require`
makes the result blank unless the inputs are present, and `min` can use
`missing_as: 10` (as in the Mental status).

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

### 2.3 Cross-record rules
- **Declarative** (covers most cases): `prev(field, n)` returns the value of the *n*-th
  previous record of the same entity ordered by date; `window(field, days=14).count(status == LOW)`;
  `since_last(entity, date_field)` (e.g. days since last climb from the rest-day tab).
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

On startup, `climblog check` (also run automatically) diffs each YAML against its sheet
and reports or applies **additive** changes. It never deletes columns or data.
Destructive operations (dropping a column) are a separate explicit command.

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
- Blocks of later milestones (`program`, `reference`, `forms`, `views`, `aggregates`,
  `recommendation`) and the expressions in `derived` are accepted as they are until their
  issue adds the checks; templates, split and child entities are checked in M1 (#8).

## 5. Future: editing modules from the UI
Phase 2 option: a "Module editor" page (add/retire fields, edit choices and thresholds)
that writes the YAML. Until then, YAML is edited by hand, with validation and a clear diff
preview before a sync touches the sheet.
