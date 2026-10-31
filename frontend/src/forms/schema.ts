// SPDX-License-Identifier: GPL-3.0-or-later
// The parts of a module's schema (its YAML as JSON, `GET /api/modules`) that the forms read
// (03-module-framework.md §2.6). The backend has checked the YAML; these types only name what
// is used.

import type { ModuleInfo } from "../api/client";

export interface FieldDef {
  type: string; // date, time, datetime, integer, number, percent, duration, scale, choice, …
  label?: string;
  help?: string;
  section?: string; // "*": a key part repeated on every section tab
  phase?: string; // pre / post / next_day: overrides its section's
  required?: boolean;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  scale?: string;
  choices?: string[];
  multiline?: boolean;
  retired?: boolean;
}

export interface ScaleDef {
  min?: number;
  max?: number;
  direction?: "higher_better" | "lower_better" | "neutral";
  choices?: string[]; // an ordinal scale
}

export interface SectionDef {
  label?: string;
  phase?: string;
}

export interface EntityDef {
  label?: string;
  key?: string[];
  date_field?: string;
  fields: Record<string, FieldDef>;
  sections?: Record<string, SectionDef>;
}

export interface FormDef {
  entity: string;
  phase?: string;
  sections?: string[];
  children?: unknown[]; // repeated child rows (finger-strength sets): not rendered yet
}

interface Schema {
  scales?: Record<string, ScaleDef>;
  entities?: Record<string, EntityDef>;
  forms?: Record<string, FormDef>;
}

function schemaOf(module: ModuleInfo): Schema {
  return module.module_schema ?? {};
}

export function formsOf(module: ModuleInfo): Record<string, FormDef> {
  return schemaOf(module).forms ?? {};
}

export function entityOf(module: ModuleInfo, name: string): EntityDef | undefined {
  return schemaOf(module).entities?.[name];
}

export function scaleOf(module: ModuleInfo, name: string | undefined): ScaleDef | undefined {
  return name === undefined ? undefined : schemaOf(module).scales?.[name];
}

/** The entity's key fields, the date first (`[date]` when it names none). */
export function keyOf(entity: EntityDef): string[] {
  return entity.key ?? [entity.date_field ?? "date"];
}

export interface FieldGroup {
  section: string | null; // null: an entity without sections
  label: string | null;
  fields: [string, FieldDef][];
}

/** The fields a form shows, by section, in YAML order: those of its sections (in its phase,
 * when it has one), plus fields of other sections whose own `phase` is the form's (a session's
 * duration and notes, typed after climbing). Key fields and retired ones are left out. */
export function formGroups(entity: EntityDef, form: FormDef): FieldGroup[] {
  const sections = entity.sections ?? {};
  const keys = new Set(keyOf(entity));
  const wanted = form.sections ?? null;
  const groups = new Map<string | null, FieldGroup>();
  const order = wanted ?? Object.keys(sections);
  for (const s of order) groups.set(s, { section: s, label: sections[s]?.label ?? s, fields: [] });
  for (const [name, field] of Object.entries(entity.fields)) {
    if (keys.has(name) || field.retired === true) continue;
    const section = field.section ?? null;
    const phase = field.phase ?? (section === null ? undefined : sections[section]?.phase);
    const inForm = wanted === null || (section !== null && wanted.includes(section));
    const samePhase = form.phase === undefined || phase === undefined || phase === form.phase;
    const pulled = field.phase !== undefined && field.phase === form.phase; // e.g. duration
    if (!((inForm && samePhase) || pulled)) continue;
    let group = groups.get(section);
    if (group === undefined) {
      group = {
        section,
        label: section === null ? null : (sections[section]?.label ?? section),
        fields: [],
      };
      groups.set(section, group);
    }
    group.fields.push([name, field]);
  }
  return [...groups.values()].filter((g) => g.fields.length > 0);
}

/** A field's label: its own, else its name without the section's prefix and phase
 * (`wb_mood_pre` in section `wb_pre` → "Mood"), with ↓ for a lower-is-better scale. */
export function fieldLabel(name: string, field: FieldDef, scale?: ScaleDef): string {
  let text = field.label;
  if (text === undefined) {
    let words = name.split("_");
    const parts = (field.section ?? "").split("_");
    const prefix = words[0] ?? "";
    const sectioned = field.section !== undefined && field.section !== "*";
    if (words.length > 1 && sectioned && (prefix === parts[0] || prefix.length <= 2)) {
      words = words.slice(1); // wb_mood_pre in wb_pre, rf_good_score in reflect
    }
    const phase = field.phase ?? parts[1];
    words = words.filter((w, i) => !(w === phase && (i === 0 || i === words.length - 1)));
    const joined = words.join(" ");
    text = joined.charAt(0).toUpperCase() + joined.slice(1);
  }
  return scale?.direction === "lower_better" ? `${text} ↓` : text;
}

/** "pre_session" → "Pre session". */
export function formLabel(name: string): string {
  const text = name.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
