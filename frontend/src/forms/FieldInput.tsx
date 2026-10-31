// SPDX-License-Identifier: GPL-3.0-or-later
import { Button, Group, Input, Select, Textarea, TextInput } from "@mantine/core";
import { DateInput, TimeInput } from "@mantine/dates";

import { fieldLabel, type FieldDef, type ScaleDef } from "./schema";
import { isScale, scaleColour, type InputValue } from "./values";

interface Props {
  name: string;
  field: FieldDef;
  scale?: ScaleDef;
  value: InputValue;
  onChange: (value: InputValue) => void;
  error?: string;
}

/** The input for one field, by its type (03 §2.6, 06-ui Log). Notes are Italian (D-024). */
export function FieldInput({ name, field, scale, value, onChange, error }: Props) {
  const label = fieldLabel(name, field, scale);
  const common = { label, description: field.help, error, required: field.required === true };
  const text = typeof value === "string" ? value : "";
  const set = (next: string | null) => {
    onChange(next ?? "");
  };
  if (isScale(field, scale)) {
    return (
      <ScaleInput
        {...common}
        scale={scale ?? {}}
        value={typeof value === "number" ? value : null}
        onChange={onChange}
      />
    );
  }
  switch (field.type) {
    case "date":
      return (
        <DateInput
          {...common}
          valueFormat="DD/MM/YYYY"
          placeholder="dd/mm/yyyy"
          value={text || null}
          onChange={set}
          clearable={field.required !== true}
        />
      );
    case "time":
      return (
        <TimeInput
          {...common}
          value={text.slice(0, 5)}
          onChange={(e) => {
            set(e.currentTarget.value);
          }}
        />
      );
    case "choice":
    case "scale": // an ordinal scale: its named steps
      return (
        <Select
          {...common}
          data={field.choices ?? scale?.choices ?? []}
          value={text || null}
          onChange={set}
          clearable
          searchable
        />
      );
    case "bool":
      return (
        <Select {...common} data={["Yes", "No"]} value={text || null} onChange={set} clearable />
      );
    case "text":
      return field.multiline === true ? (
        <Textarea
          {...common}
          value={text}
          onChange={(e) => {
            set(e.currentTarget.value);
          }}
          autosize
          minRows={2}
          lang="it"
          spellCheck
        />
      ) : (
        <TextInput
          {...common}
          value={text}
          onChange={(e) => {
            set(e.currentTarget.value);
          }}
          lang="it"
          spellCheck
        />
      );
    default: {
      // numbers (decimal commas accepted), durations (90 or 1:30), grades, references
      const hint = { duration: "min or h:mm", grade: "e.g. 6b+" }[field.type];
      const numeric = ["integer", "number", "percent", "duration"].includes(field.type);
      return (
        <TextInput
          {...common}
          value={text}
          onChange={(e) => {
            set(e.currentTarget.value);
          }}
          placeholder={hint}
          inputMode={numeric ? "decimal" : undefined}
          rightSection={field.unit}
        />
      );
    }
  }
}

interface ScaleProps {
  label: string;
  description?: string;
  error?: string;
  required: boolean;
  scale: ScaleDef;
  value: number | null;
  onChange: (value: number | null) => void;
}

/** A 1–10 scale as buttons; the chosen one again clears it. */
function ScaleInput({ label, description, error, required, scale, value, onChange }: ScaleProps) {
  const min = scale.min ?? 1;
  const max = scale.max ?? 10;
  const steps = Array.from({ length: Math.floor(max - min) + 1 }, (_, i) => min + i);
  return (
    <Input.Wrapper label={label} description={description} error={error} required={required}>
      <Group gap={4} role="group" aria-label={label}>
        {steps.map((step) => (
          <Button
            key={step}
            size="compact-md"
            w={36}
            px={0}
            color={scaleColour(step, scale)}
            variant={step === value ? "filled" : "light"}
            aria-pressed={step === value}
            onClick={() => {
              onChange(step === value ? null : step);
            }}
          >
            {step}
          </Button>
        ))}
      </Group>
    </Input.Wrapper>
  );
}
