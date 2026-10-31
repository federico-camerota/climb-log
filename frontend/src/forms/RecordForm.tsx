// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Badge, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  addRecord,
  ApiError,
  updateRecord,
  type ModuleInfo,
  type Values,
  type Written,
} from "../api/client";
import { useRecord } from "../api/queries";
import { FieldInput } from "./FieldInput";
import { formGroups, scaleOf, type EntityDef, type FormDef } from "./schema";
import { problem, toApi, toInput, unchanged, type InputValue } from "./values";

interface Props {
  module: ModuleInfo;
  formName: string;
  form: FormDef;
  entity: EntityDef;
  recordKey: Values; // e.g. {date: "2026-10-30", session_no: "2"}
}

/** A module form for one record (06-ui Log): created the first time it is saved (the pre-session
 * form), completed later on the same key (the post-session form). */
export function RecordForm(props: Props) {
  const { module, form, recordKey } = props;
  const record = useRecord(module.id, form.entity, recordKey);
  const [saved, setSaved] = useState<Written | null>(null);
  if (record.isPending) return <Loader />;
  if (record.isError) {
    return (
      <Alert color="red" title="Can't read the record">
        {record.error.message}
      </Alert>
    );
  }
  const values = record.data?.record.values ?? null;
  return (
    <Stack>
      {saved !== null && <SavedSummary written={saved} />}
      <Editor
        key={JSON.stringify(values)} // a new read starts the form again (a draft is kept)
        {...props}
        read={values}
        onSaved={setSaved}
        onReload={() => void record.refetch()}
      />
    </Stack>
  );
}

interface EditorProps extends Props {
  read: Values | null; // the record as read; null: none yet
  onSaved: (written: Written) => void;
  onReload: () => void;
}

function Editor({
  module,
  formName,
  form,
  entity,
  recordKey,
  read,
  onSaved,
  onReload,
}: EditorProps) {
  const groups = formGroups(entity, form);
  const fields = groups.flatMap((group) => group.fields);
  const scale = (name: string) => scaleOf(module, entity.fields[name]?.scale);
  const initial = Object.fromEntries(
    fields.map(([name, field]) => [name, toInput(field, scale(name), read?.[name])]),
  );
  const draftKey = `climblog:draft:${module.id}:${formName}:${JSON.stringify(recordKey)}`;
  const [draft] = useState(() => loadDraft(draftKey));
  const [restored, setRestored] = useState(draft !== null);
  const [nothing, setNothing] = useState(false);
  const editor = useForm<Record<string, InputValue>>({
    mode: "controlled",
    initialValues: { ...initial, ...(draft ?? {}) },
    validate: Object.fromEntries(
      fields.map(([name, field]) => [name, (value: InputValue) => problem(field, value)]),
    ),
  });
  useEffect(() => {
    if (editor.isDirty()) saveDraft(draftKey, editor.values);
  }, [editor, draftKey]);

  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (values: Record<string, InputValue>) => {
      const changed = fields.filter(
        ([name, field]) => !unchanged(field, read?.[name], values[name] ?? null),
      );
      const payload = Object.fromEntries(
        changed.map(([name, field]) => [name, toApi(field, values[name] ?? null)]),
      );
      if (read === null) return addRecord(module.id, form.entity, { ...recordKey, ...payload });
      const expected = Object.fromEntries(fields.map(([name]) => [name, read[name] ?? null]));
      return updateRecord(module.id, form.entity, recordKey, payload, expected);
    },
    onSuccess: (written) => {
      dropDraft(draftKey);
      onSaved(written);
      queryClient.setQueryData(["record", module.id, form.entity, recordKey], written);
      void queryClient.invalidateQueries({ queryKey: ["records", module.id, form.entity] });
      void queryClient.invalidateQueries({ queryKey: ["recommendation"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.field !== undefined && error.field in editor.values) {
        editor.setFieldError(error.field, error.message);
      }
    },
  });

  const submit = editor.onSubmit((values) => {
    const same = fields.every(([name, field]) =>
      unchanged(field, read?.[name], values[name] ?? null),
    );
    setNothing(read !== null && same);
    if (!(read !== null && same)) save.mutate(values);
  });
  const error = save.error;
  const conflict = error instanceof ApiError && error.status === 409;

  return (
    <form onSubmit={submit} noValidate>
      <Stack>
        {restored && (
          <Alert color="blue" title="Unsaved changes restored">
            <Group justify="space-between">
              <Text size="sm">Your changes from before were not saved yet.</Text>
              <Button
                size="xs"
                variant="light"
                onClick={() => {
                  dropDraft(draftKey);
                  editor.setValues(initial);
                  editor.resetDirty(initial);
                  setRestored(false);
                }}
              >
                Discard them
              </Button>
            </Group>
          </Alert>
        )}
        {groups.map((group) => (
          <Stack key={group.section ?? ""} gap="xs">
            {group.label !== null && <Title order={4}>{group.label}</Title>}
            {group.fields.map(([name, field]) => (
              <FieldInput
                key={name}
                name={name}
                field={field}
                scale={scale(name)}
                value={editor.getValues()[name] ?? null}
                onChange={(value) => {
                  editor.setFieldValue(name, value);
                }}
                error={editor.errors[name] as string | undefined}
              />
            ))}
          </Stack>
        ))}
        {conflict && (
          <Alert color="orange" title="Changed in the sheet since you opened the form">
            <Stack gap="xs">
              <Text size="sm">{error.message}</Text>
              <Group>
                <Button size="xs" variant="light" onClick={onReload}>
                  Reload the record (your changes are kept)
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}
        {error !== null &&
          !conflict &&
          !(error instanceof ApiError && error.field !== undefined) && (
            <Alert color="red" title="Not saved">
              {error.message}
            </Alert>
          )}
        {nothing && <Text c="dimmed">Nothing changed.</Text>}
        <Group>
          <Button type="submit" loading={save.isPending}>
            {read === null ? "Save" : "Save changes"}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

const STATUS_COLOURS: Record<string, string> = { GOOD: "green", WATCH: "yellow", LOW: "red" };

/** After saving: the record's statuses and log check, as computed from what was saved. */
function SavedSummary({ written }: { written: Written }) {
  const shown = Object.entries(written.record.derived).filter(
    ([name, value]) => value !== null && (name.endsWith("status") || name === "log_check"),
  );
  return (
    <Alert color="green" title="Saved">
      <Group gap="xs">
        {shown.map(([name, value]) => (
          <Badge key={name} variant="light" color={STATUS_COLOURS[String(value)] ?? "gray"}>
            {name.replaceAll("_", " ")}: {String(value)}
          </Badge>
        ))}
      </Group>
    </Alert>
  );
}

// ---- Drafts: in local storage, never the source of truth (06-ui) ----

function loadDraft(key: string): Record<string, InputValue> | null {
  try {
    const text = localStorage.getItem(key);
    return text === null ? null : (JSON.parse(text) as Record<string, InputValue>);
  } catch {
    return null;
  }
}

function saveDraft(key: string, values: Record<string, InputValue>): void {
  try {
    localStorage.setItem(key, JSON.stringify(values));
  } catch {
    // storage off or full: the form still works, without a draft
  }
}

function dropDraft(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // nothing to drop
  }
}
