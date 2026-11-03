// SPDX-License-Identifier: GPL-3.0-or-later
// A date range and filters (lib/explore Scope): Over time's and each correlation tab's own.
import { Group, MultiSelect, SegmentedControl, SimpleGrid } from "@mantine/core";
import { DateInput } from "@mantine/dates";

import type { FilterInfo } from "../api/client";
import { RANGES, type Scope } from "../lib/explore";

interface Props {
  scope: Scope;
  onChange: (change: Partial<Scope>) => void;
}

/** 7 / 30 / 90 days, all, or custom dates. */
export function RangePicker({ scope, onChange }: Props) {
  return (
    <Group align="end">
      <SegmentedControl
        aria-label="Range"
        data={RANGES}
        value={scope.range}
        onChange={(value) => {
          onChange({ range: value });
        }}
      />
      {scope.range === "custom" && (
        <>
          <DateInput
            label="From"
            valueFormat="DD/MM/YYYY"
            value={scope.start}
            onChange={(value) => {
              onChange({ start: value });
            }}
          />
          <DateInput
            label="To"
            valueFormat="DD/MM/YYYY"
            value={scope.end}
            onChange={(value) => {
              onChange({ end: value });
            }}
          />
        </>
      )}
    </Group>
  );
}

/** A picker for each choice field that filters the metrics shown (several values: any). */
export function FilterPickers({ scope, onChange, filters }: Props & { filters: FilterInfo[] }) {
  if (filters.length === 0) return null;
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
      {filters.map((f) => (
        <MultiSelect
          key={f.id}
          label={`Only ${f.label.toLowerCase()}`}
          placeholder="All"
          clearable
          data={f.choices}
          value={scope.filters[f.id] ?? []}
          onChange={(value) => {
            const next = Object.fromEntries(
              Object.entries(scope.filters).filter(([id]) => id !== f.id),
            );
            onChange({ filters: value.length > 0 ? { ...next, [f.id]: value } : next });
          }}
        />
      ))}
    </SimpleGrid>
  );
}
