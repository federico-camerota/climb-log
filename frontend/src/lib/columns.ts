// SPDX-License-Identifier: GPL-3.0-or-later
// The Records table's names for an entity's fields (D-081). A form shows "Note" under its
// section's heading; a table has no headings, so a label several fields share gets its
// section: "Mood (before)" / "Mood (after)" when the phase tells them apart, else the section's
// subject too, "Wellbeing note (before)" / "Physical note (before)".

import type { ModuleInfo } from "../api/client";
import { fieldLabel, scaleOf, type EntityDef, type FieldDef } from "../forms/schema";

export interface FieldColumn {
  id: string;
  label: string;
  group: string | null; // the field's section label, for the column picker
  type: string;
}

/** A section label as subject and qualifier: "Wellbeing · before" → ["Wellbeing", "before"]. */
function parts(entity: EntityDef, field: FieldDef): [string | null, string | null] {
  const label = field.section === undefined ? undefined : entity.sections?.[field.section]?.label;
  if (label === undefined) return [null, null];
  const [subject = label, ...rest] = label.split(" · ");
  return [subject, rest.length > 0 ? rest.join(" · ") : null];
}

/** Each stored field as a column, its label unique within the entity where its section can
 * make it so; ↓ for a lower-is-better scale, as in the forms. */
export function fieldColumns(module: ModuleInfo, entity: EntityDef): FieldColumn[] {
  // `fields` can be missing in a schema the app didn't load from YAML (tests)
  const fields = Object.entries((entity as Partial<EntityDef>).fields ?? {});
  const base = new Map(fields.map(([id, field]) => [id, fieldLabel(id, field)]));
  const sharing = new Map<string, FieldDef[]>();
  for (const [id, field] of fields) {
    const label = base.get(id) ?? id;
    sharing.set(label, [...(sharing.get(label) ?? []), field]);
  }
  return fields.map(([id, field]) => {
    let label = base.get(id) ?? id;
    const group = sharing.get(label) ?? [];
    if (group.length > 1) {
      const qualifiers = group.map((other) => parts(entity, other)[1]);
      const apart = !qualifiers.includes(null) && new Set(qualifiers).size === qualifiers.length;
      const [subject, qualifier] = parts(entity, field);
      if (apart && qualifier !== null) label = `${label} (${qualifier})`;
      else if (subject !== null) {
        const lower = label.charAt(0).toLowerCase() + label.slice(1);
        label = `${subject} ${lower}${qualifier === null ? "" : ` (${qualifier})`}`;
      }
    }
    if (scaleOf(module, field.scale)?.direction === "lower_better") label = `${label} ↓`;
    const section = field.section === undefined ? undefined : entity.sections?.[field.section];
    return { id, label, group: section?.label ?? null, type: field.type };
  });
}
