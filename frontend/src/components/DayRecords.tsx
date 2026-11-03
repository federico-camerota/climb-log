// SPDX-License-Identifier: GPL-3.0-or-later
// A calendar day's records in a drawer (D-098, 05-analytics §3.1 "click a day to open its
// records"): each record read-only (statuses, scores, its fields by form section), with an
// Edit button that opens the Records page's edit drawer.
import { Alert, Button, Card, Drawer, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router";

import type { ModuleInfo, Values } from "../api/client";
import { useRecords } from "../api/queries";
import { entityOf, fieldLabel, formGroups, formLabel, keyOf, scaleOf } from "../forms/schema";
import { EditRecord } from "./EditRecord";
import { Status } from "./Status";

interface Props {
  module: ModuleInfo;
  entities: string[]; // the calendar's entity, then its extra one (rest days)
  date: string | null; // null: closed
  onClose: () => void;
}

interface Editing {
  entity: string;
  key: Values;
}

export function DayRecords({ module, entities, date, onClose }: Props) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const queryClient = useQueryClient();
  const title = date === null ? "" : dayjs(date).format("ddd DD/MM/YYYY");
  return (
    <>
      <Drawer opened={date !== null} onClose={onClose} position="right" size="lg" title={title}>
        {date !== null && (
          <Stack>
            {entities.map((entity) => (
              <EntityDay
                key={entity}
                module={module}
                entity={entity}
                date={date}
                onEdit={(key) => {
                  setEditing({ entity, key });
                }}
              />
            ))}
            <Group>
              <Button component={Link} to={`/log/${module.id}?date=${date}`} variant="light">
                Log this day
              </Button>
            </Group>
          </Stack>
        )}
      </Drawer>
      {editing !== null && (
        <EditOne
          module={module}
          editing={editing}
          onClose={() => {
            setEditing(null);
            // the calendar and the other cards show the change
            void queryClient.invalidateQueries({ queryKey: ["view", module.id] });
          }}
        />
      )}
    </>
  );
}

/** The edit drawer for one record, with its own data issues (as on the Records page). */
function EditOne({
  module,
  editing,
  onClose,
}: {
  module: ModuleInfo;
  editing: Editing;
  onClose: () => void;
}) {
  const query = useRecords(module.id, editing.entity);
  const def = entityOf(module, editing.entity);
  const parts = def === undefined ? [] : keyOf(def);
  const current = query.data?.records.find((r) =>
    parts.every((p) => r.values[p] === editing.key[p]),
  );
  const issues =
    current === undefined
      ? []
      : (query.data?.issues ?? []).filter((i) => i.row !== null && current.rows[i.tab] === i.row);
  return (
    <EditRecord
      module={module}
      entity={editing.entity}
      recordKey={editing.key}
      issues={issues}
      onClose={onClose}
    />
  );
}

/** One entity's records of the day. */
function EntityDay({
  module,
  entity,
  date,
  onEdit,
}: {
  module: ModuleInfo;
  entity: string;
  date: string;
  onEdit: (key: Values) => void;
}) {
  const query = useRecords(module.id, entity);
  const def = entityOf(module, entity);
  if (def === undefined) return null;
  const name = def.label ?? formLabel(entity);
  if (query.isPending) return <Loader size="sm" />;
  if (query.isError) {
    return (
      <Alert color="red" title={`Can't read the ${name.toLowerCase()} records`}>
        {query.error.message}
      </Alert>
    );
  }
  const [dateField = "date", ...others] = keyOf(def);
  const found = query.data.records.filter((r) => String(r.values[dateField]).startsWith(date));
  if (found.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        {name}: none that day.
      </Text>
    );
  }
  const groups = formGroups(def, { entity });
  return (
    <>
      {found.map((record) => {
        const key: Values = Object.fromEntries(
          keyOf(def).map((p) => [p, record.values[p] ?? null]),
        );
        const heading = [name, ...others.map((p) => shown(record.values[p]))].join(" ");
        const statuses = Object.entries(record.derived).filter(
          ([k, v]) => k.includes("status") && typeof v === "string" && v !== "",
        );
        const scores = Object.entries(record.derived).filter(
          ([k, v]) => k.endsWith("score") && typeof v === "number",
        );
        return (
          <Card key={heading} withBorder>
            <Group justify="space-between" mb="xs">
              <Title order={5}>{heading}</Title>
              {!query.data.offline && (
                <Button
                  size="xs"
                  variant="light"
                  onClick={() => {
                    onEdit(key);
                  }}
                >
                  Edit
                </Button>
              )}
            </Group>
            {statuses.length > 0 && (
              <Group gap="xs" mb="xs">
                {statuses.map(([k, v]) => (
                  <Group key={k} gap={4} wrap="nowrap">
                    <Text size="xs">{formLabel(k)}</Text>
                    <Status value={v} />
                  </Group>
                ))}
              </Group>
            )}
            {scores.length > 0 && (
              <Text size="sm" mb="xs">
                {scores.map(([k, v]) => `${formLabel(k)} ${shown(v)}`).join(" · ")}
              </Text>
            )}
            <Stack gap={6}>
              {groups.map((group) => {
                const filled = group.fields.filter(([f]) => !blank(record.values[f]));
                if (filled.length === 0) return null;
                const short = filled.filter(([, field]) => field.multiline !== true);
                const long = filled.filter(([, field]) => field.multiline === true);
                return (
                  <div key={group.section ?? "fields"}>
                    {group.label !== null && (
                      <Text size="xs" c="dimmed" fw={500}>
                        {group.label}
                      </Text>
                    )}
                    {short.length > 0 && (
                      <Text size="sm">
                        {short
                          .map(
                            ([f, field]) =>
                              `${fieldLabel(f, field, scaleOf(module, field.scale))} ${shown(record.values[f])}`,
                          )
                          .join(" · ")}
                      </Text>
                    )}
                    {long.map(([f, field]) => (
                      <Text key={f} size="sm" style={{ whiteSpace: "pre-wrap" }}>
                        <b>{fieldLabel(f, field)}:</b> {shown(record.values[f])}
                      </Text>
                    ))}
                  </div>
                );
              })}
            </Stack>
          </Card>
        );
      })}
    </>
  );
}

function blank(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function shown(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "number") return String(value).replace(".", ",");
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map(shown).join(", ");
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
