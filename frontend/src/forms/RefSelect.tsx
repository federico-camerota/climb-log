// SPDX-License-Identifier: GPL-3.0-or-later
import { Select } from "@mantine/core";

import { useReferenceRows } from "../api/queries";
import { asText } from "./values";

interface Props {
  module: string;
  table: string; // the reference table the field points at
  label: string;
  description?: string;
  error?: string;
  required: boolean;
  value: string; // the key, as stored
  onChange: (value: string | null) => void;
}

/** A ref field (D-113): one of the table's rows, shown as "A3 · Wall slides" and stored as its
 * key. Retired rows aren't offered, except the one the record already has; a key that is no
 * row (typed by hand in the sheet) is shown as it is, so it can be changed. */
export function RefSelect({ module, table, value, onChange, ...common }: Props) {
  const query = useReferenceRows(module, table);
  const info = query.data?.table;
  const rows = query.data?.rows ?? [];
  const match = (key: string) => key.trim().toLowerCase();
  const options = rows
    .filter(
      (row) =>
        row.values.retired !== true || match(asText(row.values[info?.key ?? ""])) === match(value),
    )
    .map((row) => {
      const key = asText(row.values[info?.key ?? ""]);
      const shown = info?.display != null ? asText(row.values[info.display]) : "";
      const retired = row.values.retired === true ? " (retired)" : "";
      return {
        value: key,
        label: shown === "" ? `${key}${retired}` : `${key} · ${shown}${retired}`,
      };
    });
  const current = options.find((o) => match(o.value) === match(value));
  if (value !== "" && current === undefined) {
    options.push({ value, label: `${value} (not in ${info?.label ?? table})` });
  }
  return (
    <Select
      {...common}
      data={options}
      value={current?.value ?? (value === "" ? null : value)}
      onChange={onChange}
      placeholder={query.isPending ? "Loading…" : undefined}
      error={common.error ?? (query.isError ? query.error.message : undefined)}
      clearable
      searchable
      nothingFoundMessage="No such row"
    />
  );
}
