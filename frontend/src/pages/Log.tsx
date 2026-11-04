// SPDX-License-Identifier: GPL-3.0-or-later
import { Group, SegmentedControl, Select, Stack, Text, TextInput, Title } from "@mantine/core";
import { DateInput } from "@mantine/dates";
import dayjs from "dayjs";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router";

import type { ModuleInfo } from "../api/client";
import { WithModule } from "../components/WithModule";
import { RecordForm } from "../forms/RecordForm";
import { entityOf, fieldLabel, formLabel, formsOf, keyOf } from "../forms/schema";
import { asText } from "../forms/values";

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
        void navigate({ pathname: `/log/${module.id}/${name}`, search: params.toString() });
      }}
    />
  );
  if (entity === undefined) return <Stack>{picker}</Stack>;

  const [dateField = "date", ...others] = keyOf(entity);
  const date = params.get(dateField) ?? dayjs().format("YYYY-MM-DD");
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
        <DateInput
          label="Date"
          valueFormat="DD/MM/YYYY"
          value={date}
          onChange={(value) => {
            if (value !== null) setKey(dateField, value);
          }}
        />
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
      {unpicked.length > 0 ? (
        <Text c="dimmed">Pick the {unpicked.join(" and ").toLowerCase()} first.</Text>
      ) : (
        <RecordForm
          key={`${formName}:${JSON.stringify(recordKey)}`}
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
        />
      )}
    </Stack>
  );
}
