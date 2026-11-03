// SPDX-License-Identifier: GPL-3.0-or-later
// A form's child rows (06-ui Log, D-101): the finger-strength session's sets. The rows of the
// child entity that belongs to the session (its `parent.fixed` matches the session's key: hang
// sets for Max hangs) are listed, each editable or removable; "+ set" adds a row copying the
// previous row's `copy_previous` fields. They are saved with the session (`RecordForm`).
import { Alert, Button, Card, Group, Loader, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useRef, useState, type RefObject } from "react";

import {
  addRecord,
  deleteRecord,
  updateRecord,
  type ModuleInfo,
  type Records,
  type Values,
} from "../api/client";
import { useRecords } from "../api/queries";
import { FieldInput } from "./FieldInput";
import {
  entityOf,
  keyOf,
  scaleOf,
  type ChildFormDef,
  type EntityDef,
  type FieldDef,
  type FormDef,
} from "./schema";
import { asText, problem, toApi, toInput, unchanged, type InputValue } from "./values";

/** What the form needs from a child block when it saves. */
export interface ChildApi {
  entity: string;
  dirty: () => boolean;
  validate: () => boolean; // false: a row has a problem (shown under its field)
  save: () => Promise<void>;
}

export type ChildRegistry = RefObject<Map<string, ChildApi>>;

interface Props {
  module: ModuleInfo;
  form: FormDef;
  recordKey: Values; // the parent record's key, as the form has it (text)
  registry: ChildRegistry;
}

/** The child forms that apply to this record: those whose entity's `parent.fixed` matches it. */
export function ChildRows({ module, form, recordKey, registry }: Props) {
  const children = (form.children ?? []).filter((child) => {
    const fixed = entityOf(module, child.entity)?.parent?.fixed ?? {};
    return Object.entries(fixed).every(([name, value]) => recordKey[name] === value);
  });
  return (
    <>
      {children.map((child) => (
        <ChildBlock
          key={child.entity}
          module={module}
          child={child}
          recordKey={recordKey}
          registry={registry}
        />
      ))}
    </>
  );
}

function ChildBlock({
  module,
  child,
  recordKey,
  registry,
}: {
  module: ModuleInfo;
  child: ChildFormDef;
  recordKey: Values;
  registry: ChildRegistry;
}) {
  const def = entityOf(module, child.entity);
  const query = useRecords(module.id, child.entity);
  if (def?.parent === undefined) return null;
  if (query.isPending) return <Loader size="sm" />;
  if (query.isError) {
    return (
      <Alert color="red" title={`Can't read the ${(def.label ?? child.entity).toLowerCase()}s`}>
        {query.error.message}
      </Alert>
    );
  }
  const parentKey = def.parent.key;
  const number = keyOf(def).find((k) => !parentKey.includes(k)); // set_no
  const mine = query.data.records
    .filter((r) => parentKey.every((k) => asText(r.values[k]) === asText(recordKey[k])))
    .sort((a, b) => Number(a.values[number ?? ""] ?? 0) - Number(b.values[number ?? ""] ?? 0));
  return (
    <ChildEditor
      // a new read (after a save) starts the rows again
      key={JSON.stringify(mine.map((r) => r.values))}
      module={module}
      child={child}
      def={def}
      records={mine}
      recordKey={recordKey}
      registry={registry}
    />
  );
}

interface Row {
  id: number; // local, for React
  key: Values | null; // the stored row's key; null: a new row
  read: Values | null;
  values: Record<string, InputValue>;
  removed: boolean;
}

function ChildEditor({
  module,
  child,
  def,
  records,
  recordKey,
  registry,
}: {
  module: ModuleInfo;
  child: ChildFormDef;
  def: EntityDef;
  records: Records["records"];
  recordKey: Values;
  registry: ChildRegistry;
}) {
  const keys = keyOf(def);
  const parentKey = def.parent?.key ?? [];
  const number = keys.find((k) => !parentKey.includes(k));
  const fields = Object.entries(def.fields).filter(
    ([name, field]) => !keys.includes(name) && field.retired !== true,
  );
  const scale = (field: FieldDef) => scaleOf(module, field.scale);
  const label = def.label ?? child.entity;
  const blank = () =>
    Object.fromEntries(fields.map(([name, field]) => [name, toInput(field, scale(field), null)]));
  const [rows, setRows] = useState<Row[]>(() =>
    records.map((r, i) => ({
      id: i,
      key: Object.fromEntries(keys.map((k) => [k, r.values[k] ?? null])),
      read: r.values,
      values: Object.fromEntries(
        fields.map(([name, field]) => [name, toInput(field, scale(field), r.values[name])]),
      ),
      removed: false,
    })),
  );
  const [errors, setErrors] = useState<Record<number, Record<string, string>>>({});
  const nextId = useRef(records.length);

  const filled = (row: Row) =>
    fields.some(([name, field]) => toApi(field, row.values[name] ?? null) !== null);
  const changed = (row: Row) =>
    fields.filter(([name, field]) => !unchanged(field, row.read?.[name], row.values[name] ?? null));
  const name = (row: Row, i: number) =>
    row.key !== null && number !== undefined
      ? `${label} ${asText(row.key[number])}`
      : `New ${label.toLowerCase()} (${String(i + 1)})`;

  // the form calls these on save: they read the rows as they are then
  const latest = useRef(rows);
  useEffect(() => {
    latest.current = rows;
  });
  useEffect(() => {
    const map = registry.current;
    map.set(child.entity, {
      entity: child.entity,
      dirty: () =>
        latest.current.some((row) =>
          row.key === null ? !row.removed && filled(row) : row.removed || changed(row).length > 0,
        ),
      validate: () => {
        const found: Record<number, Record<string, string>> = {};
        for (const row of latest.current) {
          if (row.removed || (row.key === null && !filled(row))) continue;
          for (const [field, def_] of fields) {
            const message = problem(def_, row.values[field] ?? null);
            if (message !== null) (found[row.id] ??= {})[field] = message;
          }
        }
        setErrors(found);
        return Object.keys(found).length === 0;
      },
      save: async () => {
        const parent = Object.fromEntries(parentKey.map((k) => [k, recordKey[k] ?? null]));
        for (const [i, row] of latest.current.entries()) {
          try {
            if (row.key !== null && row.removed) {
              await deleteRecord(module.id, child.entity, row.key);
            } else if (row.key === null && !row.removed && filled(row)) {
              const values = Object.fromEntries(
                fields.map(([f, field]) => [f, toApi(field, row.values[f] ?? null)]),
              );
              await addRecord(module.id, child.entity, { ...parent, ...values });
            } else if (row.key !== null && changed(row).length > 0) {
              const payload = Object.fromEntries(
                changed(row).map(([f, field]) => [f, toApi(field, row.values[f] ?? null)]),
              );
              const expected = Object.fromEntries(fields.map(([f]) => [f, row.read?.[f] ?? null]));
              await updateRecord(module.id, child.entity, row.key, payload, expected);
            }
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            throw new Error(`${name(row, i)}: ${message}`, { cause: error });
          }
        }
      },
    });
    return () => {
      map.delete(child.entity);
    };
  });

  const add = () => {
    const previous = [...rows].reverse().find((row) => !row.removed);
    const copied = Object.fromEntries(
      (child.copy_previous ?? [])
        .filter((f) => previous !== undefined && f in previous.values)
        .map((f) => [f, previous?.values[f] ?? null]),
    );
    setRows([
      ...rows,
      {
        id: nextId.current++,
        key: null,
        read: null,
        values: { ...blank(), ...copied },
        removed: false,
      },
    ]);
  };

  return (
    <Stack gap="xs">
      <Title order={4}>{label}s</Title>
      {rows.length === 0 && <Text c="dimmed">None yet.</Text>}
      {rows.map((row, i) => (
        <Card key={row.id} withBorder padding="sm" style={{ opacity: row.removed ? 0.5 : 1 }}>
          <Group justify="space-between" mb="xs">
            <Text fw={500} td={row.removed ? "line-through" : undefined}>
              {name(row, i)}
            </Text>
            <Button
              size="xs"
              variant="subtle"
              color={row.removed ? "blue" : "red"}
              onClick={() => {
                setRows(
                  row.key === null
                    ? rows.filter((r) => r.id !== row.id) // a new row: just dropped
                    : rows.map((r) => (r.id === row.id ? { ...r, removed: !r.removed } : r)),
                );
              }}
            >
              {row.removed ? "Keep" : "Remove"}
            </Button>
          </Group>
          {!row.removed && (
            <SimpleGrid cols={{ base: 2, sm: 4 }}>
              {fields.map(([field, def_]) => (
                <FieldInput
                  key={field}
                  name={field}
                  field={def_}
                  scale={scale(def_)}
                  value={row.values[field] ?? null}
                  onChange={(value) => {
                    setRows(
                      rows.map((r) =>
                        r.id === row.id ? { ...r, values: { ...r.values, [field]: value } } : r,
                      ),
                    );
                  }}
                  error={errors[row.id]?.[field]}
                />
              ))}
            </SimpleGrid>
          )}
        </Card>
      ))}
      <Group>
        <Button variant="light" size="xs" onClick={add}>
          + {label.toLowerCase()}
        </Button>
      </Group>
    </Stack>
  );
}
