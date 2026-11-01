// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Badge,
  Button,
  Group,
  MultiSelect,
  ScrollArea,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import type { ComboboxData } from "@mantine/core";

import type { Issue, ModuleInfo, Records } from "../api/client";
import { entityOf, keyOf, type EntityDef } from "../forms/schema";
import { asText } from "../forms/values";
import { csvOf, download } from "../lib/csv";
import { formatDateTime } from "../lib/format";
import { fieldColumns } from "../lib/columns";
import { fold, matches } from "../lib/search";

interface Row {
  values: Record<string, unknown>; // stored and derived
  issues: Issue[]; // the data issues of its rows
  matched?: string[]; // while searching: the hidden columns where the query was found
}

interface Column {
  id: string;
  label: string;
  group: string | null; // the section, for the picker
  type: string; // the field's type; "derived" for a derived value
}

const DERIVED = "Computed";
const MATCHED = "_matched"; // the "Matched in" column, shown while searching
const SEARCHED = ["text", "choice", "date", "grade"];
// the viewport less the app header and the page's padding
const TABLE_HEIGHT =
  "calc(100dvh - var(--app-shell-header-height, 0px) - 2 * var(--mantine-spacing-md))";

const STATUS_COLOURS: Record<string, string> = {
  GOOD: "green",
  WATCH: "yellow",
  LOW: "red",
  "NEEDS ATTENTION": "red",
  "WORTH NOTING": "yellow",
};
const SHOWN_FIRST = /(score|status|readiness)$|^log_check$/; // the default columns, with the key

/** An entity's records as a table (06-ui Records, D-081): newest first, sortable, searched
 * without accents, the data issues marked in their cell; the columns are picked (and
 * remembered); the table as shown is exported to CSV. */
export function RecordsTable({ module, data }: { module: ModuleInfo; data: Records }) {
  const entity = useMemo(() => entityOf(module, data.entity) ?? { fields: {} }, [module, data]);
  const columns = useMemo(() => columnsOf(module, entity, data), [module, entity, data]);
  const storageKey = `climblog:columns:${module.id}:${data.entity}`;
  const [shown, setShown] = useState<string[]>(
    () => loadColumns(storageKey) ?? defaultColumns(entity, columns),
  );
  const [query, setQuery] = useState("");
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [sorting, setSorting] = useState<SortingState>(() =>
    keyOf(entity).map((id) => ({ id, desc: true })),
  );

  const rows = useMemo(() => rowsOf(data), [data]);
  const searching = query.trim() !== "";
  const searched = useMemo(() => {
    // every text, choice, grade and date field is searched, shown or not; the hidden ones
    // where the query was found are named in "Matched in"
    const texts = columns.filter((c) => SEARCHED.includes(c.type));
    const hidden = texts.filter((c) => !shown.includes(c.id));
    return rows
      .filter(
        (row) =>
          (!onlyIssues || row.issues.length > 0) &&
          matches(
            texts.flatMap((c) => textsOf(row, c)),
            query,
          ),
      )
      .map((row) => ({ ...row, matched: matchedIn(row, hidden, query) }));
  }, [rows, columns, shown, query, onlyIssues]);

  const defs = useMemo<ColumnDef<Row>[]>(() => {
    const picked: ColumnDef<Row>[] = columns
      .filter((c) => shown.includes(c.id))
      .map((c) => ({
        id: c.id,
        header: c.label,
        accessorFn: (row) => row.values[c.id] ?? undefined,
        sortUndefined: "last",
        cell: ({ row }) => <Cell column={c} row={row.original} />,
      }));
    if (!searching) return picked;
    const matched: ColumnDef<Row> = {
      id: MATCHED,
      header: "Matched in",
      enableSorting: false,
      cell: ({ row }) => (
        <Text size="sm" c="dimmed">
          {(row.original.matched ?? []).join(", ")}
        </Text>
      ),
    };
    return [...picked, matched];
  }, [columns, shown, searching]);
  const table = useReactTable({
    data: searched,
    columns: defs,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const pick = (ids: string[]) => {
    const ordered = columns.map((c) => c.id).filter((id) => ids.includes(id));
    setShown(ordered);
    saveColumns(storageKey, ordered);
  };
  const exportCsv = () => {
    const visible = table.getVisibleLeafColumns().filter((c) => c.id !== MATCHED);
    const header = visible.map((c) => String(c.columnDef.header));
    const body = table.getRowModel().rows.map((r) => visible.map((c) => r.original.values[c.id]));
    download(`${module.id}-${data.entity}.csv`, csvOf(header, body));
  };

  return (
    <Stack>
      <Group align="end">
        <TextInput
          label="Search"
          placeholder="a word in the notes, a date (30/10/2026)…"
          value={query}
          onChange={(event) => {
            setQuery(event.currentTarget.value);
          }}
          w={320}
        />
        <Switch
          label="Only records with data issues"
          checked={onlyIssues}
          onChange={(event) => {
            setOnlyIssues(event.currentTarget.checked);
          }}
        />
        <Button variant="light" onClick={exportCsv}>
          Export CSV
        </Button>
      </Group>
      <MultiSelect
        label="Columns"
        placeholder="Add a column"
        data={pickerData(columns)}
        value={shown}
        onChange={pick}
        searchable
        clearable={false}
      />
      <Text size="sm" c="dimmed">
        {searched.length === rows.length
          ? `${String(rows.length)} shown`
          : `${String(searched.length)} of ${String(rows.length)} shown`}
      </Text>
      {/* At most one screen high, so the horizontal scrollbar stays in view however many
          rows there are, and the header row stays on top */}
      <ScrollArea.Autosize mah={TABLE_HEIGHT} type="auto" offsetScrollbars>
        <Table striped highlightOnHover stickyHeader withTableBorder>
          <Table.Thead>
            {table.getHeaderGroups().map((group) => (
              <Table.Tr key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <Table.Th
                      key={header.id}
                      onClick={header.column.getToggleSortingHandler()}
                      style={{ cursor: "pointer", whiteSpace: "nowrap" }}
                      aria-sort={
                        sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                      }
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sorted === "asc" ? " ▲" : sorted === "desc" ? " ▼" : ""}
                    </Table.Th>
                  );
                })}
              </Table.Tr>
            ))}
          </Table.Thead>
          <Table.Tbody>
            {table.getRowModel().rows.map((row) => (
              <Table.Tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <Table.Td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea.Autosize>
    </Stack>
  );
}

/** A value as the table shows it: dates day first, statuses as badges, a data issue in red. */
function Cell({ column, row }: { column: Column; row: Row }) {
  const value = row.values[column.id];
  const issue = row.issues.find((i) => i.field === column.id);
  let shown: React.ReactNode = value === null || value === undefined ? "" : asText(value);
  if (typeof value === "string" && column.type === "date") shown = formatDateTime(value);
  if (typeof value === "boolean") shown = value ? "Yes" : "No";
  if (typeof value === "string" && value in STATUS_COLOURS) {
    shown = (
      <Badge variant="light" color={STATUS_COLOURS[value]}>
        {value}
      </Badge>
    );
  }
  if (issue === undefined) return shown;
  return (
    <Tooltip label={issue.message} multiline w={280}>
      <Text span c="red" fw={500} aria-label={`Data issue: ${issue.message}`}>
        {shown === "" ? "⚠" : shown}
      </Text>
    </Tooltip>
  );
}

function columnsOf(module: ModuleInfo, entity: EntityDef, data: Records): Column[] {
  const derived = new Set<string>();
  for (const record of data.records)
    for (const name of Object.keys(record.derived)) derived.add(name);
  return [
    ...fieldColumns(module, entity),
    ...[...derived].map((id) => ({
      id,
      label: id.replaceAll("_", " "),
      group: DERIVED,
      type: "derived",
    })),
  ];
}

/** The column picker's choices, grouped by section (fields without one first). */
function pickerData(columns: Column[]): ComboboxData {
  const loose = columns
    .filter((c) => c.group === null)
    .map((c) => ({ value: c.id, label: c.label }));
  const groups = [...new Set(columns.map((c) => c.group).filter((g) => g !== null))];
  return [
    ...loose,
    ...groups.map((group) => ({
      group,
      items: columns.filter((c) => c.group === group).map((c) => ({ value: c.id, label: c.label })),
    })),
  ];
}

/** The searched fields of a row, among those not shown, where a word of the query is. */
function matchedIn(row: Row, columns: Column[], query: string): string[] {
  const words = fold(query)
    .split(/\s+/)
    .filter((word) => word !== "");
  if (words.length === 0) return [];
  return columns
    .filter((c) => {
      const texts = textsOf(row, c).map(fold);
      return words.some((word) => texts.some((text) => text.includes(word)));
    })
    .map((c) => c.label);
}

/** What search reads in a cell: dates as stored and as shown (30/10/2026). */
function textsOf(row: Row, column: Column): string[] {
  const value = asText(row.values[column.id]);
  return column.type === "date" ? [value, formatDateTime(value)] : [value];
}

function defaultColumns(entity: EntityDef, columns: Column[]): string[] {
  const key = keyOf(entity);
  return columns.filter((c) => key.includes(c.id) || SHOWN_FIRST.test(c.id)).map((c) => c.id);
}

function rowsOf(data: Records): Row[] {
  return data.records.map((record) => ({
    values: { ...record.values, ...record.derived },
    issues: data.issues.filter((i) => i.row !== null && record.rows[i.tab] === i.row),
  }));
}

// ---- The columns picked, per module and entity (a convenience: local storage) ----

function loadColumns(key: string): string[] | null {
  try {
    const text = localStorage.getItem(key);
    return text === null ? null : (JSON.parse(text) as string[]);
  } catch {
    return null;
  }
}

function saveColumns(key: string, ids: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    // storage off: the choice lasts until the page is left
  }
}
