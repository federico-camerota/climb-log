// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import { Navigate, useNavigate, useParams } from "react-router";

import {
  addReferenceRow,
  ApiError,
  isLoaded,
  referenceNames,
  updateReferenceRow,
  type ModuleInfo,
  type ReferenceRow,
  type ReferenceTableInfo,
  type Values,
} from "../api/client";
import { useModules, useReferenceRows } from "../api/queries";
import { DataStatus } from "../components/DataStatus";
import { FieldInput } from "../forms/FieldInput";
import { fieldLabel, type FieldDef } from "../forms/schema";
import { asText, problem, toApi, toInput, unchanged, type InputValue } from "../forms/values";

const RETIRED = "retired";
const KEY_WIDTH = 72; // px: the sticky key column, so the next one sticks right after it

/** A program's reference tables (03 §2.5, 06-ui Program, D-112): exercises, ladder rungs,
 * questions… one tab per table, rows added and edited here or typed in the sheet. A row's key
 * never changes in the app (records point at it); a row no longer used is retired, not
 * deleted. */
export function Program() {
  const params = useParams();
  const query = useModules();
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't list the modules">
        {query.error.message}
      </Alert>
    );
  }
  const modules = query.data.modules.filter((m) => isLoaded(m) && referenceNames(m).length > 0);
  const first = modules[0];
  if (first === undefined) {
    return (
      <Stack>
        <Title order={2}>Program</Title>
        <Text>No module has reference tables yet: a program module lists them in its YAML.</Text>
      </Stack>
    );
  }
  const module = modules.find((m) => m.id === (params.module ?? first.id));
  if (module === undefined) {
    return (
      <Stack>
        <Title order={2}>Program</Title>
        <Text>Module &apos;{params.module}&apos; has no reference tables.</Text>
      </Stack>
    );
  }
  const tables = referenceNames(module);
  const table = params.table ?? tables[0] ?? "";
  if (params.module === undefined || params.table === undefined) {
    return <Navigate replace to={`/program/${module.id}/${table}`} />;
  }
  if (!tables.includes(table)) {
    return (
      <Stack>
        <Title order={2}>Program</Title>
        <Text>
          Module &apos;{module.id}&apos; has no table &apos;{table}&apos;.
        </Text>
      </Stack>
    );
  }
  return <ProgramPage modules={modules} module={module} table={table} />;
}

function ProgramPage({
  modules,
  module,
  table,
}: {
  modules: ModuleInfo[];
  module: ModuleInfo;
  table: string;
}) {
  const navigate = useNavigate();
  return (
    <Stack>
      <Title order={2}>Program</Title>
      <Select
        label="Module"
        data={modules.map((m) => ({ value: m.id, label: m.name ?? m.id }))}
        value={module.id}
        onChange={(id) => {
          if (id !== null) void navigate(`/program/${id}`);
        }}
        allowDeselect={false}
        maw={320}
      />
      <Tabs
        value={table}
        onChange={(value) => {
          if (value !== null) void navigate(`/program/${module.id}/${value}`);
        }}
      >
        <Tabs.List>
          {referenceNames(module).map((name) => (
            <Tabs.Tab key={name} value={name}>
              {tableLabel(module, name)}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <ReferenceTable key={`${module.id}/${table}`} module={module} table={table} />
    </Stack>
  );
}

function ReferenceTable({ module, table }: { module: ModuleInfo; table: string }) {
  const query = useReferenceRows(module.id, table);
  const [showRetired, setShowRetired] = useState(false);
  const [editing, setEditing] = useState<ReferenceRow | "new" | null>(null);
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't read the table">
        {query.error.message}
      </Alert>
    );
  }
  const data = query.data;
  const info = data.table;
  const defs = columnDefs(module, info);
  const retired = data.rows.filter((r) => r.values[RETIRED] === true).length;
  const shown = showRetired ? data.rows : data.rows.filter((r) => r.values[RETIRED] !== true);
  const columns = info.columns.filter((c) => c !== RETIRED);
  return (
    <Stack>
      <DataStatus records={data} />
      <Group justify="space-between">
        <Text size="sm">
          {plural(data.rows.length - retired, "row")}
          {retired > 0 && ` · ${String(retired)} retired`}
          {` · ${plural(data.issues.length, "data issue")}`}
        </Text>
        <Group>
          {retired > 0 && (
            <Switch
              label="Show retired"
              checked={showRetired}
              onChange={(event) => {
                setShowRetired(event.currentTarget.checked);
              }}
            />
          )}
          <Button
            size="xs"
            disabled={data.offline}
            title={data.offline ? "The workbook can't be reached: read-only" : undefined}
            onClick={() => {
              setEditing("new");
            }}
          >
            Add row
          </Button>
        </Group>
      </Group>
      {shown.length === 0 ? (
        <Text c="dimmed" size="sm">
          No rows yet: add one here, or type them in the sheet&apos;s {info.tab} tab.
        </Text>
      ) : (
        <ScrollArea type="auto">
          <Table highlightOnHover withTableBorder style={{ minWidth: "max-content" }}>
            <Table.Thead>
              <Table.Tr>
                {columns.map((c, i) => (
                  <Table.Th key={c} style={sticky(i)}>
                    {headerOf(c, defs[c], info)}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.map((row) => {
                const isRetired = row.values[RETIRED] === true;
                return (
                  <Table.Tr
                    key={row.row}
                    onClick={() => {
                      setEditing(row);
                    }}
                    style={{ cursor: "pointer", opacity: isRetired ? 0.55 : undefined }}
                  >
                    {columns.map((c, i) => (
                      <Table.Td key={c} style={sticky(i)}>
                        {cellText(row.values[c])}
                        {i === 1 && isRetired && (
                          <Badge ml={6} size="xs" color="gray" variant="light">
                            retired
                          </Badge>
                        )}
                      </Table.Td>
                    ))}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
      {data.issues.map((issue) => (
        <Text
          key={`${String(issue.row)}-${issue.field ?? ""}-${issue.message}`}
          size="sm"
          c="orange"
        >
          {issue.row !== null ? `${issue.tab}, row ${String(issue.row)}: ` : `${issue.tab}: `}
          {issue.field !== null && issue.row !== null ? `${issue.field}: ` : ""}
          {issue.message}
        </Text>
      ))}
      {editing !== null && (
        <RowEditor
          module={module.id}
          table={table}
          info={info}
          defs={defs}
          row={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </Stack>
  );
}

function RowEditor({
  module,
  table,
  info,
  defs,
  row,
  onClose,
}: {
  module: string;
  table: string;
  info: ReferenceTableInfo;
  defs: Record<string, FieldDef>;
  row: ReferenceRow | null; // null: a new row
  onClose: () => void;
}) {
  const read: Values = row?.values ?? {};
  const [values, setValues] = useState<Record<string, InputValue>>(() =>
    Object.fromEntries(
      info.columns.map((c) => [c, toInput(defs[c] ?? { type: "text" }, undefined, read[c])]),
    ),
  );
  const [touched, setTouched] = useState(false);
  const queryClient = useQueryClient();
  const keyText = asText(read[info.key]);
  const save = useMutation({
    mutationFn: () => {
      if (row === null) {
        const sent = Object.fromEntries(
          info.columns
            .map((c) => [c, toApi(defs[c] ?? { type: "text" }, values[c] ?? null)] as const)
            .filter(([, v]) => v !== null),
        );
        return addReferenceRow(module, table, sent);
      }
      const changed = info.columns.filter(
        (c) =>
          c !== info.key && !unchanged(defs[c] ?? { type: "text" }, read[c], values[c] ?? null),
      );
      const sent = Object.fromEntries(
        changed.map((c) => [c, toApi(defs[c] ?? { type: "text" }, values[c] ?? null)]),
      );
      const expected = Object.fromEntries(changed.map((c) => [c, read[c] ?? null]));
      return updateReferenceRow(module, table, keyText, sent, expected);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["reference", module, table], data);
      onClose();
    },
  });
  const apiProblems = save.error instanceof ApiError ? save.error.problems : [];
  const errorOf = (column: string): string | undefined => {
    const found = apiProblems.find((p) => p.field === column);
    if (found !== undefined) return found.message;
    if (!touched) return undefined;
    return problem(defs[column] ?? { type: "text" }, values[column] ?? null) ?? undefined;
  };
  const set = (column: string) => (value: InputValue) => {
    setValues((v) => ({ ...v, [column]: value }));
  };
  const weeks = new Set(info.week_columns);
  const plain = info.columns.filter((c) => !weeks.has(c) && c !== RETIRED);
  const blocking = info.columns.some(
    (c) => problem(defs[c] ?? { type: "text" }, values[c] ?? null) !== null,
  );
  const keyBlank = row === null && asText(values[info.key]).trim() === "";
  const title = row === null ? `New row · ${info.label}` : `${info.label} · ${keyText}`;
  return (
    <Modal opened onClose={onClose} title={title} size="lg">
      <Stack>
        {plain.map((c) =>
          c === info.key && row !== null ? (
            <TextInput
              key={c}
              label={fieldLabel(c, defs[c] ?? { type: "text" })}
              value={keyText}
              readOnly
              description="The key can't change: records point at it"
            />
          ) : (
            <FieldInput
              module={module}
              key={c}
              name={c}
              field={defs[c] ?? { type: "text" }}
              value={values[c] ?? null}
              onChange={set(c)}
              error={errorOf(c)}
            />
          ),
        )}
        {info.week_columns.length > 0 && (
          <>
            <Text size="sm" fw={500}>
              {info.per_week_label ?? "Per week"}
            </Text>
            <SimpleGrid cols={{ base: 2, sm: 3 }}>
              {info.week_columns.map((c, i) => (
                <FieldInput
                  module={module}
                  key={c}
                  name={c}
                  field={{ ...(defs[c] ?? { type: "text" }), label: `W${String(i + 1)}` }}
                  value={values[c] ?? null}
                  onChange={set(c)}
                  error={errorOf(c)}
                />
              ))}
            </SimpleGrid>
          </>
        )}
        <Switch
          label="Retired: kept for the records that use it, not offered for new ones"
          checked={values[RETIRED] === "Yes"}
          onChange={(event) => {
            set(RETIRED)(event.currentTarget.checked ? "Yes" : "No");
          }}
        />
        {save.isError && (
          <Alert color="red" title="Not saved">
            {save.error.message}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            onClick={() => {
              setTouched(true);
              if (!blocking && !keyBlank) save.mutate();
            }}
          >
            {row === null ? "Add" : "Save"}
          </Button>
        </Group>
        {touched && keyBlank && (
          <Text size="sm" c="red">
            A new row needs its {info.key}.
          </Text>
        )}
      </Stack>
    </Modal>
  );
}

/** Every column as a field: the table's own (from the module's YAML), the per-week ones and
 * `retired`. */
function columnDefs(module: ModuleInfo, info: ReferenceTableInfo): Record<string, FieldDef> {
  const tables = module.module_schema?.reference as
    Record<string, { fields?: Record<string, FieldDef>; per_week?: { type?: string } }> | undefined;
  const def = tables?.[info.name];
  const defs: Record<string, FieldDef> = { ...(def?.fields ?? {}) };
  const keyDef = defs[info.key];
  if (keyDef !== undefined) defs[info.key] = { ...keyDef, required: true };
  info.week_columns.forEach((c, i) => {
    defs[c] = { type: def?.per_week?.type ?? "text", label: `W${String(i + 1)}` };
  });
  defs[RETIRED] = { type: "bool", label: "Retired" };
  return defs;
}

function tableLabel(module: ModuleInfo, name: string): string {
  const tables = module.module_schema?.reference as Record<string, { label?: string }> | undefined;
  return tables?.[name]?.label ?? name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
}

function headerOf(column: string, def: FieldDef | undefined, info: ReferenceTableInfo): string {
  const week = info.week_columns.indexOf(column);
  if (week >= 0) return `W${String(week + 1)}`;
  return fieldLabel(column, def ?? { type: "text" });
}

function cellText(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "";
  return asText(value);
}

/** The key column, and the one after it, stay in view while the weeks scroll sideways. */
function sticky(index: number): CSSProperties | undefined {
  if (index > 1) return undefined;
  return {
    position: "sticky",
    left: index === 0 ? 0 : KEY_WIDTH,
    zIndex: 1,
    background: "var(--mantine-color-body)",
    ...(index === 0 ? { minWidth: KEY_WIDTH, maxWidth: KEY_WIDTH } : {}),
  };
}

function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}
