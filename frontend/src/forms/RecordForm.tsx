// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Badge, Button, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDebouncedValue } from "@mantine/hooks";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  addRecord,
  ApiError,
  getRecord,
  type FieldProblem,
  type Issue,
  updateRecord,
  type ModuleInfo,
  type Values,
  type Written,
} from "../api/client";
import { useHidden, useRecord, useRecords } from "../api/queries";
import { ChildRows, type ChildApi } from "./ChildRows";
import { FieldInput } from "./FieldInput";
import { formGroups, scaleOf, type EntityDef, type FormDef } from "./schema";
import { isScale, problem, toApi, toInput, unchanged, type InputValue } from "./values";

// The inputs that hold text as typed (FieldInput's text inputs): a bad value is shown in them.
const TYPED_AS_TEXT = new Set(["text", "integer", "number", "percent", "duration", "grade", "ref"]);

interface Props {
  module: ModuleInfo;
  formName: string;
  form: FormDef;
  entity: EntityDef;
  recordKey: Values; // e.g. {date: "2026-10-30", session_no: "2"}
  // the record's data issues (Records' edit drawer, D-082): each shows under its field, and a
  // bad value typed in a text-like field starts in the input as typed, to be corrected
  issues?: Issue[];
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
  issues = [],
}: EditorProps) {
  const groups = formGroups(entity, form);
  const fields = groups.flatMap((group) => group.fields);
  const scale = (name: string) => scaleOf(module, entity.fields[name]?.scale);
  const initial = Object.fromEntries(
    fields.map(([name, field]) => {
      const typed = issues.find((i) => i.field === name && i.kind === "value")?.value;
      const asTyped =
        typed != null && TYPED_AS_TEXT.has(field.type) && !isScale(field, scale(name));
      return [name, asTyped ? typed : toInput(field, scale(name), read?.[name])];
    }),
  );
  const issueErrors = Object.fromEntries(
    issues.filter((i) => i.field !== null).map((i) => [i.field ?? "", i.message]),
  );
  const draftKey = `climblog:draft:${module.id}:${formName}:${JSON.stringify(recordKey)}`;
  const [draft] = useState(() => loadDraft(draftKey));
  const [restored, setRestored] = useState(draft !== null);
  const [nothing, setNothing] = useState(false);
  const hiddenRef = useRef(new Set<string>()); // the fields hidden now (below), for validation
  const children = useRef(new Map<string, ChildApi>()); // the child rows' blocks (sets)
  const editor = useForm<Record<string, InputValue>>({
    mode: "controlled",
    initialValues: { ...initial, ...(draft ?? {}) },
    // a draft comes back with the errors it had (D-079): the API's are known only on save
    initialErrors: { ...issueErrors, ...(draft === null ? {} : loadDraftErrors(draftKey)) },
    validate: Object.fromEntries(
      fields.map(([name, field]) => [
        name,
        // a hidden field isn't checked: it isn't saved either
        (value: InputValue) => (hiddenRef.current.has(name) ? null : problem(field, value)),
      ]),
    ),
  });

  // `visible_if` (03 §2.1b): the backend says which fields to hide for the values typed so far
  // (debounced); until it first answers, the conditional fields stay hidden
  const conditional = fields.filter(([, field]) => field.visible_if != null).map(([n]) => n);
  const typed = JSON.stringify(
    Object.fromEntries(
      fields.map(([name, field]) => [name, toApi(field, editor.getValues()[name] ?? null)]),
    ),
  );
  const [settled] = useDebouncedValue(typed, 300);
  const answer = useHidden(
    module.id,
    form.entity,
    JSON.parse(settled) as Values,
    conditional.length > 0,
  );
  const hidden = new Set(conditional.length > 0 ? (answer.data ?? conditional) : []);
  useEffect(() => {
    hiddenRef.current = hidden;
  });
  const shownFields = fields.filter(([name]) => !hidden.has(name));

  // `suggest_from_history`: the values typed before in the entity's records, newest first
  const suggesting = fields.filter(([, field]) => field.suggest_from_history === true);
  const history = useRecords(module.id, form.entity, suggesting.length > 0);
  const suggestions = Object.fromEntries(
    suggesting.map(([name]) => [name, pastValues(history.data?.records ?? [], name)]),
  );
  useEffect(() => {
    if (editor.isDirty()) saveDraft(draftKey, editor.values, editor.errors);
  }, [editor, draftKey]);

  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async (values: Record<string, InputValue>): Promise<Written> => {
      const changed = shownFields.filter(
        ([name, field]) => !unchanged(field, read?.[name], values[name] ?? null),
      );
      const payload = Object.fromEntries(
        changed.map(([name, field]) => [name, toApi(field, values[name] ?? null)]),
      );
      const blocks = [...children.current.values()];
      const rows = blocks.filter((block) => block.dirty());
      let written: Written | null = null;
      if (read === null) {
        // the record first: its child rows need it
        written = await addRecord(module.id, form.entity, { ...recordKey, ...payload });
      } else if (changed.length > 0) {
        const expected = Object.fromEntries(fields.map(([name]) => [name, read[name] ?? null]));
        written = await updateRecord(module.id, form.entity, recordKey, payload, expected);
      }
      for (const block of rows) await block.save();
      if (rows.length === 0 && written !== null) return written;
      // the child rows changed the record's derived values (the number of sets): read it again
      const fresh = await getRecord(module.id, form.entity, recordKey);
      if (fresh === null) throw new Error("The record is gone: reload the page");
      return fresh;
    },
    onSuccess: (written) => {
      dropDraft(draftKey);
      onSaved(written);
      queryClient.setQueryData(["record", module.id, form.entity, recordKey], written);
      void queryClient.invalidateQueries({ queryKey: ["records", module.id, form.entity] });
      for (const child of form.children ?? []) {
        void queryClient.invalidateQueries({ queryKey: ["records", module.id, child.entity] });
      }
      void queryClient.invalidateQueries({ queryKey: ["recommendation"] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
    },
    onError: (error) => {
      const [onForm] = splitProblems(error, editor.getValues());
      for (const problem of onForm) editor.setFieldError(problem.field, problem.message);
    },
  });

  // an event handler (not called while rendering): it reads the child rows' blocks
  const submit = (event: React.SubmitEvent<HTMLFormElement>) => {
    editor.onSubmit(onValid)(event);
  };
  function onValid(values: Record<string, InputValue>) {
    const blocks = [...children.current.values()];
    if (!blocks.every((block) => block.validate())) return;
    const same =
      shownFields.every(([name, field]) => unchanged(field, read?.[name], values[name] ?? null)) &&
      !blocks.some((block) => block.dirty());
    setNothing(read !== null && same);
    if (!(read !== null && same)) save.mutate(values);
  }
  const error = save.error;
  const conflict = error instanceof ApiError && error.status === 409;
  // each problem on a field of the form shows under it; the rest (or a problem with no field)
  // in the "Not saved" alert
  const [onForm, elsewhere] = splitProblems(error, editor.getValues());

  // the groups shown; a form's child rows (sets) come before its first "after" group
  const shown = groups
    .map((group) => ({ ...group, fields: group.fields.filter(([n]) => !hidden.has(n)) }))
    .filter((group) => group.fields.length > 0);
  const post = shown.findIndex(
    (group) => group.section !== null && entity.sections?.[group.section]?.phase === "post",
  );
  const setsAt = post === -1 ? shown.length : post;
  const renderGroup = (group: (typeof shown)[number]) => (
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
          suggestions={suggestions[name]}
        />
      ))}
    </Stack>
  );

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
                  editor.clearErrors();
                  setRestored(false);
                }}
              >
                Discard them
              </Button>
            </Group>
          </Alert>
        )}
        {shown.slice(0, setsAt).map(renderGroup)}
        {form.children !== undefined && (
          <ChildRows module={module} form={form} recordKey={recordKey} registry={children} />
        )}
        {shown.slice(setsAt).map(renderGroup)}
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
        {error !== null && !conflict && (onForm.length === 0 || elsewhere.length > 0) && (
          <Alert color="red" title="Not saved">
            {elsewhere.length > 0 ? elsewhere.map((p) => p.message).join("; ") : error.message}
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

/** A field's distinct values in the records, newest first (the records come in sheet order). */
function pastValues(records: { values: Values }[], name: string): string[] {
  const dated = records
    .map((r) => ({
      date: typeof r.values.date === "string" ? r.values.date : "",
      value: r.values[name],
    }))
    .filter(
      (r): r is { date: string; value: string } => typeof r.value === "string" && r.value !== "",
    )
    .sort((a, b) => b.date.localeCompare(a.date));
  return [...new Set(dated.map((r) => r.value))];
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

/** The errors the draft's fields showed (kept apart, so older drafts still load). */
function loadDraftErrors(key: string): Record<string, string> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(`${key}:errors`) ?? "{}");
    if (typeof parsed !== "object" || parsed === null) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string] => {
        return typeof entry[1] === "string";
      }),
    );
  } catch {
    return {};
  }
}

function saveDraft(
  key: string,
  values: Record<string, InputValue>,
  errors: Record<string, unknown>,
): void {
  const shown = Object.entries(errors).filter(([, error]) => typeof error === "string");
  try {
    localStorage.setItem(key, JSON.stringify(values));
    if (shown.length > 0)
      localStorage.setItem(`${key}:errors`, JSON.stringify(Object.fromEntries(shown)));
    else localStorage.removeItem(`${key}:errors`);
  } catch {
    // storage off or full: the form still works, without a draft
  }
}

function dropDraft(key: string): void {
  try {
    localStorage.removeItem(key);
    localStorage.removeItem(`${key}:errors`);
  } catch {
    // nothing to drop
  }
}

/** A failed save's problems: those on a field of the form, and the others. A 422 lists every
 * field at fault (D-079); an older answer names only `field`. */
function splitProblems(
  error: Error | null,
  values: Record<string, unknown>,
): [FieldProblem[], FieldProblem[]] {
  if (!(error instanceof ApiError)) return [[], []];
  const all =
    error.problems.length > 0
      ? error.problems
      : error.field !== undefined
        ? [{ field: error.field, message: error.message }]
        : [];
  return [all.filter((p) => p.field in values), all.filter((p) => !(p.field in values))];
}
