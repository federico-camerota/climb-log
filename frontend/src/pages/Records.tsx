// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Loader, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";

import type { ModuleInfo, Values } from "../api/client";
import { useRecords } from "../api/queries";
import { DataStatus } from "../components/DataStatus";
import { EditRecord } from "../components/EditRecord";
import { IssuesPanel } from "../components/IssuesPanel";
import { RecordsTable } from "../components/RecordsTable";
import { WithModule } from "../components/WithModule";
import { entityOf, keyOf } from "../forms/schema";

function Summary({ module, entity }: { module: ModuleInfo; entity: string }) {
  const query = useRecords(module.id, entity);
  const [open, setOpen] = useState<Values | null>(null); // the key of the record being edited
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't read the records">
        {query.error.message}
      </Alert>
    );
  }
  const { records, issues } = query.data;
  const parts = keyOf(entityOf(module, entity) ?? { fields: {} });
  // the open record as now read (its issues follow a save; gone once deleted)
  const current = records.find((r) => parts.every((p) => r.values[p] === open?.[p]));
  const ownIssues =
    current === undefined
      ? []
      : issues.filter((i) => i.row !== null && current.rows[i.tab] === i.row);
  return (
    <Stack gap="xs">
      <DataStatus records={query.data} />
      <Text>
        {records.length} {records.length === 1 ? "record" : "records"} · {issues.length} data{" "}
        {issues.length === 1 ? "issue" : "issues"}
      </Text>
      {!query.data.offline && records.length > 0 && (
        <Text size="sm" c="dimmed">
          Click a record to edit or delete it.
        </Text>
      )}
      <IssuesPanel module={module} entity={entity} issues={issues} />
      <RecordsTable
        key={`${module.id}:${entity}`}
        module={module}
        data={query.data}
        onOpen={
          query.data.offline
            ? undefined // the snapshot is read-only
            : (values) => {
                setOpen(Object.fromEntries(parts.map((p) => [p, values[p]])));
              }
        }
      />
      <EditRecord
        module={module}
        entity={entity}
        recordKey={open !== null && current !== undefined ? open : null}
        issues={ownIssues}
        onClose={() => {
          setOpen(null);
        }}
      />
    </Stack>
  );
}

export function Records() {
  return (
    <Stack>
      <Title order={2}>Records</Title>
      <WithModule base="/records" perEntity>
        {({ module, entity }) => <Summary module={module} entity={entity} />}
      </WithModule>
    </Stack>
  );
}
