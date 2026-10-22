# 04 · Storage: spreadsheets as the source of truth

## 1. Layout conventions (both backends)
- **One workbook per module** (e.g. `climbing-journal.xlsx`, or a Google Sheet). Each
  module's source is configured independently, so the Journal can live on Google while a
  program stays local.
- **One tab per entity / reference table**, plus two system tabs:
  - `_meta`: key/value: `module`, `module_version`, `schema_synced_at`, `app_version`.
  - `_settings`: key/value: module settings (thresholds, start date). Editing here by hand
    works too.
**Hand entry is a first-class path** (D-003, D-013): I sometimes log directly in Google
Sheets without the app, so every tab must be comfortable to fill by hand.

- **Two header rows** (D-014):
  - row 1 = **human label** ("Sleep quality (1–10)", "Fingers ↓"), bold, frozen,
    coloured by section (green = pre, amber = post, as now);
  - row 2 = **field key** (`sleep_quality`) in 9 pt monospace dark grey on a pale tint of the
    group colour, with a thick line underneath separating headers from data (D-029), frozen. The app matches columns
    on these keys, so **column order does not matter** and labels can be reworded freely.
    A cell note explains "do not edit this row".
- Row 3+ = one record per row. No merged cells, no blank spacer rows. **Formulas only in
  app-managed computed columns** (below).
- **Computed columns** (D-018): at the right of each tab, under a grey "AUTOMATIC" header
  group (as in the legacy sheets), one column per derived field, with key `auto:<field>` in
  row 2. Formulas are generated from the YAML (`03-module-framework.md` §2.2b) and return `""`
  while the row's key is empty. Statuses get conditional formatting (GOOD/WATCH/LOW,
  GREEN/YELLOW/RED colours). The columns are protected with a *warning only*, so hand edits
  remain possible but deliberate.
- **Hidden key column** (D-031): tabs with a composite key get a hidden computed column
  `auto:_key` = date serial × 10 + session # (blank = 1), so cross-tab formulas (session
  checks, child counts, maxima) need a single, locale-proof criterion.
- **Pre-filled formula rows**: tabs keep a buffer of empty rows that already contain the
  formulas (default 200), so a row typed by hand in Google Sheets gets its statuses
  immediately. The app writes new records into the **first row with an empty key**
  (not `append`, which would land after the buffer) and tops the buffer up when fewer than 50
  rows are left. Rows with an empty key are ignored on read.
- **`Summary` tab** (generated, formulas only): latest status per class, days since the last
  session, LOW count in 14 days, and the suggested next session, i.e. the small part of the
  legacy "Summary – Recent" that is useful in the sheet. Rich dashboards stay in the app.
- **Natural keys instead of typed ids** where possible (D-015): a record is identified by
  the columns a person would naturally type, usually the **date** (plus an optional
  `session #` for the rare second session on the same day). Entities with several records
  per day and no natural key (e.g. individual falls) get an `id` column that **may be left
  blank** by hand; the app fills it on the next sync.
- Hand-optional system columns at the right: `updated_at`, `deleted` (soft delete).
  Left blank by hand; the app fills them.
- The app writes **data validation** (dropdowns for choices, number ranges for scales,
  date format on date columns), so hand entry in Google/Excel/LibreOffice stays constrained.
  The dropdowns are rewritten on every schema sync, so they always match the YAML.
- An optional `README` tab (generated) explains each tab and its scales, mirroring the
  current "Start Here".

### Journal entity shape (D-006)
**One tab per section**, as in the current workbook: `Session`, `Wellbeing`, `Physical`,
`Mental`, `Session Feel`, `Wins & Reflect`, plus `Rest Days`. Each section tab starts with
`date` (+ optional `session_no`) and holds only that section's fields. The app joins the
tabs on `(date, session_no)`, replacing today's fragile join by row position: tabs can be
sorted or filtered independently, and rows can be in any order.
- The `Session` tab is the anchor. A section row whose date has no `Session` row is reported
  as a data issue ("Wellbeing row for 2026-11-03 has no session"), with a one-click fix that
  creates the session row.
- In the app the session is still edited as one record; the backend splits the write
  across the tabs.
- Constraint: within one journal there is at most one session per day unless `session_no`
  is used (decided in Q2; separate journals are separate workbooks, D-005).

## 2. Local `.xlsx` backend
- Read: `openpyxl` (read-only mode for loading) into a DataFrame per tab.
- Write: load → modify → **atomic save** (write a temp file in the same dir, then `os.replace`).
- **Lock detection**: refuse to write if `~$name.xlsx` (Excel) or `.~lock.name.xlsx#`
  (LibreOffice) exists. The UI shows "close the file in LibreOffice to save". Reads still work.
- **Backups**: before the first write of each app session and then at most every N minutes,
  copy to `backups/<module>/<timestamp>.xlsx`, keeping the last 30 (configurable).
- Change detection: poll `mtime` and reload when it changes and we didn't cause it.
- `.csv` folder backend: a possible cheap extra (one CSV per tab), not planned.

## 3. Google Sheets backend
**One location per journal**: a module lives either in a local file or in a Google Sheet,
never both (no two-way sync). A journal I want to log while away from home lives in Google
Sheets, and the app at home reads/writes that same sheet. Hand entries made on the phone
are picked up by change polling.

- **Auth**: OAuth 2.0 "Desktop app" client. One-time setup: create a Google Cloud project
  and an OAuth client ID, download `client_secret.json`, then run `climblog google login`
  (browser consent). The token is stored at `~/.config/climblog/google-token.json`.
  A service account (sharing the sheet with its email) is an alternative for headless use.
- Scopes: `https://www.googleapis.com/auth/spreadsheets` (+ `drive.metadata.readonly` for
  change detection; or `drive.file` if the app creates the spreadsheets).
- Read: one `values.batchGet` for all tabs of a module, with `valueRenderOption=UNFORMATTED_VALUE`
  and `dateTimeRenderOption=SERIAL_NUMBER`, then convert.
- Write: `values.update` into the first row with an empty key for new records (formula buffer, §1); `values.update` on the row found by key for edits; buffer top-up with `batchUpdate`.
  Writes are queued and retried with backoff (quota is ~60 write req/min/user, ample).
- Concurrency: before updating, re-read the target row and compare `updated_at`. If it
  changed (hand edit on the web), surface a conflict instead of overwriting.
- Backups: periodic export of the spreadsheet as `.xlsx` into the local backups folder
  (Drive export), so a Google-hosted module is also backed up locally.
- Offline: if Google is unreachable, the UI is read-only from cache, and *optionally*
  writes go to a local outbox that is flushed later (M6 nice-to-have).

## 3b. Text and language (Italian notes, D-024)
- UTF-8 end to end; accented letters (à è é ì ò ù), typographic quotes and emoji round-trip
  unchanged through both backends and the snapshot.
- Text fields are written **as raw text** (Sheets `valueInputOption=RAW`; openpyxl
  string cells with the `@` text format on text columns). A note starting with `'` (common
  when typing *po'*, *giovedi'*), `=`, `+` or `-` is therefore stored literally. It is
  never turned into a formula or stripped by the spreadsheet (this also prevents formula injection).
- On read, whitespace is preserved and line breaks in multiline notes are kept.
- Numbers typed by hand with a decimal comma (`7,5`) are accepted and normalised, as Italian
  keyboards and locales produce them.

## 4. Validation and data issues
On every load, each cell is parsed according to its field type. Problems (e.g.
`"7,5"` in a number field, unknown choice, out-of-range scale, duplicate id, unparseable
date) are collected into **data issues** with tab/row/column and shown in the UI with
"fix" links. The record still loads (the bad field is treated as missing).

## 5. Derived values
The YAML is the single source of logic. The app computes derived values in Python, and the
sheet shows the same values through formula columns **generated from the same YAML**
(D-018). The app never reads formula results as input; it compares them with its own
results to detect damaged formulas (drift check) and repairs them on sync.

## 6. Local snapshot (app-side copy of the data)
The app works on a **local snapshot** of each module: the last data read from its source,
stored on disk (`~/.local/share/climblog/snapshots/<module>.parquet`, plus metadata:
source modifiedTime, read time).
- On startup the app loads the snapshot immediately, then refreshes it from the source in the
  background (and on change polling, the Reload button, and after every write).
- All analysis runs on the snapshot, so the app is fast and still usable (read-only) when
  Google is unreachable. The UI shows "data as of HH:MM".
- The snapshot is a cache: deleting it is always safe, and the sheets remain the source of truth.

## 7. Modules and locations (initial setup)
| Module | Location | Purpose |
|---|---|---|
| Climbing journal | Google Sheets | daily use, hand entry when away |
| Shoulder program | Google Sheets | daily use |
| Fear of falling | Google Sheets | daily use |
| **Finger strength** (4th) | local `.xlsx` | real journal (max hangs, finger curls) and the end-to-end test of the local backend, child entities and conditional fields (D-019, D-025) |

Automated tests additionally use throwaway synthetic workbooks in a temp dir; they never touch the real journals.

## 8. Migration from the legacy workbooks
`climblog import-legacy --journal Climbing_Journal.xlsx --fear Fear_of_Falling_Tracker.xlsx --shoulder Shoulder_Program_Tracker_Fixed.xlsx --out data/`

- Reads the legacy layouts (header row 4, row-linked tabs) and maps columns to field keys
  (explicit mapping tables in `importers/`).
- Journal: copies the 6 session tabs into their new section tabs, replacing the row-link
  with the session date in every tab; copies Rest Days; imports thresholds into `_settings`.
- Fear: Fear Map → `fear_map` reference + `fear_map_scores` (scenario × week);
  Fall Ladder → `rungs` reference + `rung_clearances`; Session Log → `falls`
  (skipping the example row); 20Q → `q20`; weekly review journal → `weekly_review`.
  "Progress" weekly totals are **not** imported as data because they are derived from `falls`.
- Shoulder: Plan → `exercises` reference with w1..w12; Session Log → `exercise_log`
  (only rows with a date or any actual data); Check-in → `checkins`; Retests → `retests`.
- Produces an **import report** (counts and skipped rows) and a **parity report**: the
  legacy computed values (read with `data_only=True`, after recalculating with LibreOffice
  headless if the cached values are stale) compared with the app's derived values.
- The legacy files are never modified.
