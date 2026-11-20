// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Anchor,
  Group,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router";

import type { ModuleInfo, Values } from "../api/client";
import { useRecords } from "../api/queries";
import { RunOfDay } from "../components/ProgramRuns";
import { WithModule } from "../components/WithModule";
import { BatchForm } from "../forms/BatchForm";
import { RecordForm } from "../forms/RecordForm";
import {
  batchField,
  entityOf,
  fieldLabel,
  formLabel,
  formsOf,
  keyOf,
  type EntityDef,
} from "../forms/schema";
import { asText } from "../forms/values";
import { formatDateTime } from "../lib/format";
import { weekSpan, weekText } from "../lib/weeks";

export function Log() {
  return (
    <Stack>
      <Title order={2}>Log</Title>
      <WithModule base="/log">{({ module }) => <LogForm module={module} />}</WithModule>
    </Stack>
  );
}

/** The module's form named in the URL (`/log/journal/post_session?date=2026-10-30&session_no=2`),
 * the first one when it names none; the record's key comes from the query (date: today). */
function LogForm({ module }: { module: ModuleInfo }) {
  const { form: formName } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  // a repeated form's "Save and add another" (D-115): the kept values, and a new round
  const [another, setAnother] = useState<{ kept: Values; round: number; saved: string } | null>(
    null,
  );
  const forms = formsOf(module);
  const names = Object.keys(forms);
  const first = names[0];
  if (first === undefined) return <Text>Module &apos;{module.id}&apos; has no forms.</Text>;
  if (formName === undefined) {
    return (
      <Navigate
        replace
        to={{ pathname: `/log/${module.id}/${first}`, search: params.toString() }}
      />
    );
  }
  const form = forms[formName];
  if (form === undefined) {
    return (
      <Text>
        Module &apos;{module.id}&apos; has no form &apos;{formName}&apos;.
      </Text>
    );
  }
  const entity = entityOf(module, form.entity);
  const picker = (
    <SegmentedControl
      data={names.map((name) => ({ value: name, label: formLabel(name) }))}
      value={formName}
      onChange={(name) => {
        setAnother(null);
        void navigate({ pathname: `/log/${module.id}/${name}`, search: params.toString() });
      }}
    />
  );
  if (entity === undefined) return <Stack>{picker}</Stack>;

  const [dateField = "date", ...parts] = keyOf(entity);
  // a batch form's rows fill one key part each (the exercise, D-115): not asked here
  const rowField = batchField(entity, form);
  const others = parts.filter((name) => name !== rowField);
  // a plan's records are dated by a week, typed 2026-W47 (D-110)
  const byWeek = entity.fields[dateField]?.type === "week";
  const today = dayjs().format("YYYY-MM-DD");
  const date = params.get(dateField) ?? (byWeek ? weekText(today) : today);
  const span = byWeek ? weekSpan(date) : null;
  const recordKey: Record<string, string> = { [dateField]: date };
  for (const name of others) {
    // `default: next` (a meal's number): blank, the next number when saved (D-050, D-107)
    const fallback = entity.fields[name]?.default;
    recordKey[name] = params.get(name) ?? (fallback === "next" ? "" : asText(fallback));
  }
  // a choice key part decides the record (and its child rows): the form waits for it
  const unpicked = others
    .filter((name) => entity.fields[name]?.choices !== undefined && recordKey[name] === "")
    .map((name) => {
      const field = entity.fields[name];
      return field === undefined ? name : fieldLabel(name, field);
    });
  const setKey = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(name, value);
    setParams(next, { replace: true });
  };

  return (
    <Stack>
      {picker}
      <Group align="end">
        {byWeek ? (
          <TextInput
            label="Week"
            placeholder="2026-W47"
            value={date}
            error={span === null ? "Not a week like 2026-W47" : undefined}
            description={
              span === null
                ? undefined
                : `Mon ${formatDateTime(span[0])} – Sun ${formatDateTime(span[1])}`
            }
            onChange={(event) => {
              setKey(dateField, event.currentTarget.value.trim());
            }}
            w={200}
          />
        ) : (
          <DateInput
            label="Date"
            valueFormat="DD/MM/YYYY"
            value={date}
            onChange={(value) => {
              if (value !== null) setKey(dateField, value);
            }}
          />
        )}
        {others.map((name) => {
          const field = entity.fields[name];
          if (field?.choices !== undefined) {
            // a key part that is a choice (a finger session's type): picked from its choices
            return (
              <Select
                key={name}
                label={fieldLabel(name, field)}
                data={field.choices}
                value={recordKey[name] || null}
                placeholder="Pick one"
                allowDeselect={false}
                onChange={(value) => {
                  if (value !== null) setKey(name, value);
                }}
                w={200}
              />
            );
          }
          return field === undefined ? null : (
            <TextInput
              key={name}
              label={fieldLabel(name, field)}
              value={recordKey[name]}
              placeholder={field.default === "next" ? "next" : undefined}
              onChange={(event) => {
                setKey(name, event.currentTarget.value);
              }}
              w={160}
            />
          );
        })}
      </Group>
      {module.kind === "program" && (byWeek ? span !== null : true) && (
        <RunOfDay module={module.id} date={span?.[0] ?? date} />
      )}
      {form.repeat === true && rowField === undefined && (
        <DayRecords
          module={module}
          formName={formName}
          entity={form.entity}
          def={entity}
          date={date}
          saved={another?.saved ?? null}
        />
      )}
      {byWeek && span === null ? (
        <Text c="dimmed">Type the week first, like 2026-W47.</Text>
      ) : unpicked.length > 0 ? (
        <Text c="dimmed">Pick the {unpicked.join(" and ").toLowerCase()} first.</Text>
      ) : rowField !== undefined ? (
        <BatchForm
          key={`${formName}:${JSON.stringify(recordKey)}`}
          module={module}
          formName={formName}
          form={form}
          entity={entity}
          sharedKey={recordKey}
        />
      ) : (
        <RecordForm
          key={`${formName}:${JSON.stringify(recordKey)}:${String(another?.round ?? 0)}`}
          module={module}
          formName={formName}
          form={form}
          entity={entity}
          recordKey={recordKey}
          onCreated={(key) => {
            const next = new URLSearchParams(params);
            for (const [name, value] of Object.entries(key)) next.set(name, asText(value));
            setParams(next, { replace: true });
          }}
          kept={another?.kept}
          onAnother={
            form.repeat === true
              ? (kept, saved) => {
                  // the next record: the key parts kept stay, the others start again (the
                  // next number); the kept fields start with their values (D-115)
                  const next = new URLSearchParams(params);
                  for (const name of others) {
                    if (!(form.keep_fields ?? []).includes(name)) next.delete(name);
                  }
                  setParams(next, { replace: true });
                  setAnother({ kept, round: (another?.round ?? 0) + 1, saved });
                }
              : undefined
          }
        />
      )}
    </Stack>
  );
}

/** A repeated form's records of the day (D-115): "On this day: Drill try 1 · 2 · 3", each a
 * link to its form; and what the last "Save and add another" saved. */
function DayRecords({
  module,
  formName,
  entity,
  def,
  date,
  saved,
}: {
  module: ModuleInfo;
  formName: string;
  entity: string;
  def: EntityDef;
  date: string;
  saved: string | null;
}) {
  const records = useRecords(module.id, entity);
  const [dateField = "date", ...rest] = keyOf(def);
  const mine = (records.data?.records ?? []).filter((r) => asText(r.values[dateField]) === date);
  const label = def.label ?? entity;
  return (
    <Stack gap={2}>
      {saved !== null && (
        <Text size="sm" c="green">
          Saved {saved}. Here is the next one.
        </Text>
      )}
      <Text size="sm" c="dimmed">
        On this day: {mine.length === 0 && `no ${label.toLowerCase()} yet`}
        {mine.map((r, i) => {
          const search = new URLSearchParams({ [dateField]: date });
          for (const name of rest) search.set(name, asText(r.values[name]));
          const number = rest.map((name) => asText(r.values[name])).join(" ");
          return (
            <span key={search.toString()}>
              {i > 0 && " · "}
              <Anchor component={Link} to={`/log/${module.id}/${formName}?${search.toString()}`}>
                {label} {number}
              </Anchor>
            </span>
          );
        })}
      </Text>
    </Stack>
  );
}
