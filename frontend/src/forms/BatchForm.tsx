// SPDX-License-Identifier: GPL-3.0-or-later
// A batch form (03 §2.6, D-115): one row per reference row in its filter (the exercises of
// session A, every retest measure), each with its record of the day if logged. The date (and
// the other key parts) come from the Log page; `keep_fields` are typed once above the rows. One
// Save writes every row in one go, all or none; a row left empty is skipped.
import { Alert, Badge, Button, Card, Group, Loader, SimpleGrid, Stack, Text } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  saveBatch,
  type BatchRows,
  type BatchWrite,
  type ModuleInfo,
  type Values,
} from "../api/client";
import { useBatch } from "../api/queries";
import { DataStatus } from "../components/DataStatus";
import { FieldInput } from "./FieldInput";
import { formGroups, scaleOf, type EntityDef, type FieldDef, type FormDef } from "./schema";
import { asText, problem, toApi, toInput, unchanged, type InputValue } from "./values";

interface Props {
  module: ModuleInfo;
  formName: string;
  form: FormDef;
  entity: EntityDef;
  sharedKey: Values; // the key parts but the row's: {date: "2026-11-18"}
}

export function BatchForm({ module, formName, form, entity, sharedKey }: Props) {
  const batch = useBatch(module.id, formName, sharedKey);
  // kept here: a save reads the rows again, which starts the editor again
  const [saved, setSaved] = useState<number | null>(null);
  if (batch.isPending) return <Loader />;
  if (batch.isError) {
    return (
      <Alert color="red" title="Can't read the rows">
        {batch.error.message}
      </Alert>
    );
  }
  return (
    <BatchEditor
      key={JSON.stringify(batch.data)} // a new read (after a save) starts the rows again
      module={module}
      form={form}
      entity={entity}
      sharedKey={sharedKey}
      batch={batch.data}
      saved={saved}
      onSaved={setSaved}
    />
  );
}

type Inputs = Record<string, InputValue>;

function BatchEditor({
  module,
  form,
  entity,
  sharedKey,
  batch,
  saved,
  onSaved,
}: Omit<Props, "formName"> & {
  batch: BatchRows;
  saved: number | null; // the rows written by the last save (0: nothing changed)
  onSaved: (count: number | null) => void;
}) {
  const kept = new Set(batch.shared);
  // the fields typed once (keep_fields that aren't key parts), then each row's own
  const all = formGroups(entity, form).flatMap((group) => group.fields);
  const sharedFields = all.filter(([name]) => kept.has(name));
  const rowFields = all.filter(([name]) => !kept.has(name) && name !== batch.field);
  const scale = (field: FieldDef) => scaleOf(module, field.scale);
  const offline = batch.offline;

  const inputs = (fields: [string, FieldDef][], values: Values | null | undefined): Inputs =>
    Object.fromEntries(
      fields.map(([name, field]) => [name, toInput(field, scale(field), values?.[name])]),
    );
  const firstLogged = batch.rows.find((row) => row.record !== null)?.record?.values;
  const [shared, setShared] = useState<Inputs>(() => inputs(sharedFields, firstLogged));
  const [rows, setRows] = useState<Inputs[]>(() =>
    batch.rows.map((row) => inputs(rowFields, row.record?.values)),
  );
  const [errors, setErrors] = useState<Record<string, string>>({}); // "row:field" → message

  const filled = (values: Inputs) =>
    rowFields.some(([name, field]) => toApi(field, values[name] ?? null) !== null);
  const sharedValues = () =>
    Object.fromEntries(
      sharedFields.map(([name, field]) => [name, toApi(field, shared[name] ?? null)]),
    );

  // what one Save sends: new rows with something typed, stored rows that changed (their own
  // fields, or a field typed once); and each one's label, in the same order, for its errors
  const plan = () => {
    const body: BatchWrite = { new: [], changed: [] };
    const labels: string[] = [];
    const changedLabels: string[] = [];
    batch.rows.forEach((row, i) => {
      const values = rows[i] ?? {};
      const read = row.record?.values ?? null;
      if (read === null) {
        if (!filled(values)) return; // a row left empty is skipped (D-115)
        const own = Object.fromEntries(
          rowFields.map(([name, field]) => [name, toApi(field, values[name] ?? null)]),
        );
        body.new.push({ ...sharedKey, ...sharedValues(), [batch.field]: row.key, ...own });
        labels.push(row.label);
        return;
      }
      const changed = [
        ...rowFields.filter(([n, f]) => !unchanged(f, read[n], values[n] ?? null)),
        ...sharedFields.filter(([n, f]) => !unchanged(f, read[n], shared[n] ?? null)),
      ];
      if (changed.length === 0) return;
      body.changed.push({
        key: { ...sharedKey, [batch.field]: read[batch.field] },
        values: Object.fromEntries(
          changed.map(([n, f]) => [n, toApi(f, (kept.has(n) ? shared[n] : values[n]) ?? null)]),
        ),
        expected: Object.fromEntries(changed.map(([n]) => [n, read[n] ?? null])),
      });
      changedLabels.push(row.label);
    });
    return { body, labels: [...labels, ...changedLabels] };
  };

  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async () => {
      const { body, labels } = plan();
      try {
        return await saveBatch(module.id, form.entity, body);
      } catch (error) {
        if (error instanceof ApiError && error.index !== undefined) {
          const row = labels[error.index] ?? `Row ${String(error.index + 1)}`;
          throw new ApiError(error.status, "", `${row}: ${error.message}`);
        }
        throw error;
      }
    },
    onSuccess: (written) => {
      onSaved(written.keys.length);
      void queryClient.invalidateQueries({ queryKey: ["batch", module.id] });
      void queryClient.invalidateQueries({ queryKey: ["records", module.id, form.entity] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      void queryClient.invalidateQueries({ queryKey: ["recommendation"] });
    },
  });

  const submit = (event: React.SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const found: Record<string, string> = {};
    const anyNew = batch.rows.some((row, i) => row.record === null && filled(rows[i] ?? {}));
    if (anyNew || batch.rows.some((row) => row.record !== null)) {
      for (const [name, field] of sharedFields) {
        const message = problem(field, shared[name] ?? null);
        if (message !== null) found[`shared:${name}`] = message;
      }
    }
    batch.rows.forEach((row, i) => {
      const values = rows[i] ?? {};
      if (row.record === null && !filled(values)) return;
      for (const [name, field] of rowFields) {
        const message = problem(field, values[name] ?? null);
        if (message !== null) found[`${String(i)}:${name}`] = message;
      }
    });
    setErrors(found);
    onSaved(null);
    if (Object.keys(found).length > 0) return;
    const { body } = plan();
    if (body.new.length + body.changed.length === 0) {
      onSaved(0);
      return;
    }
    save.mutate();
  };

  const logged = batch.rows.filter((row) => row.record !== null).length;
  return (
    <form onSubmit={submit} noValidate>
      <Stack>
        {offline && <DataStatus records={batch} />}
        <Text size="sm" c="dimmed">
          {logged} of {batch.rows.length} logged on this day. Rows left empty are not saved.
        </Text>
        {sharedFields.length > 0 && (
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            {sharedFields.map(([name, field]) => (
              <FieldInput
                key={name}
                module={module.id}
                name={name}
                field={field}
                scale={scale(field)}
                value={shared[name] ?? null}
                onChange={(value) => {
                  setShared({ ...shared, [name]: value });
                }}
                error={errors[`shared:${name}`]}
              />
            ))}
          </SimpleGrid>
        )}
        {batch.rows.length === 0 && <Text c="dimmed">No rows: the table has none in use.</Text>}
        {batch.rows.map((row, i) => (
          <Card key={String(row.key)} withBorder padding="sm">
            <Group justify="space-between" mb="xs" gap="xs">
              <Text fw={500}>{row.label}</Text>
              <Group gap="xs">
                {row.hint !== null && (
                  <Text size="sm" c="dimmed">
                    {row.hint}
                  </Text>
                )}
                {row.retired && (
                  <Badge variant="light" color="gray">
                    retired
                  </Badge>
                )}
                {row.record !== null && (
                  <Badge variant="light" color="green">
                    logged
                  </Badge>
                )}
              </Group>
            </Group>
            <SimpleGrid cols={{ base: 2, sm: 4 }}>
              {rowFields.map(([name, field]) => (
                <FieldInput
                  key={name}
                  module={module.id}
                  name={name}
                  field={field}
                  scale={scale(field)}
                  value={rows[i]?.[name] ?? null}
                  onChange={(value) => {
                    setRows(rows.map((r, j) => (j === i ? { ...r, [name]: value } : r)));
                  }}
                  error={errors[`${String(i)}:${name}`]}
                />
              ))}
            </SimpleGrid>
          </Card>
        ))}
        {batch.others.length > 0 && (
          <Stack gap={2}>
            <Text fw={500}>Also logged that day</Text>
            {batch.others.map((record) => (
              <Text key={String(record.values[batch.field])} size="sm" c="dimmed">
                {asText(record.values[batch.field]) || "?"}
                {rowFields
                  .map(([name]) => record.values[name])
                  .filter((v) => v !== null && v !== undefined && v !== "")
                  .map((v) => ` · ${asText(v)}`)
                  .join("")}
              </Text>
            ))}
          </Stack>
        )}
        {save.error !== null && (
          <Alert
            color={save.error instanceof ApiError && save.error.status === 409 ? "orange" : "red"}
            title="Not saved (nothing was written)"
          >
            {save.error.message}
          </Alert>
        )}
        {saved !== null && (
          <Text c={saved === 0 ? "dimmed" : "green"}>
            {saved === 0
              ? "Nothing changed."
              : `Saved ${String(saved)} row${saved === 1 ? "" : "s"}.`}
          </Text>
        )}
        <Group>
          <Button type="submit" loading={save.isPending} disabled={offline}>
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
