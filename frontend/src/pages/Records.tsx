// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Loader, Stack, Text, Title } from "@mantine/core";

import type { ModuleInfo } from "../api/client";
import { useRecords } from "../api/queries";
import { DataStatus } from "../components/DataStatus";
import { IssuesPanel } from "../components/IssuesPanel";
import { RecordsTable } from "../components/RecordsTable";
import { WithModule } from "../components/WithModule";

function Summary({ module, entity }: { module: ModuleInfo; entity: string }) {
  const query = useRecords(module.id, entity);
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't read the records">
        {query.error.message}
      </Alert>
    );
  }
  const { records, issues } = query.data;
  return (
    <Stack gap="xs">
      <DataStatus records={query.data} />
      <Text>
        {records.length} {records.length === 1 ? "record" : "records"} · {issues.length} data{" "}
        {issues.length === 1 ? "issue" : "issues"}
      </Text>
      <IssuesPanel issues={issues} />
      <RecordsTable key={`${module.id}:${entity}`} module={module} data={query.data} />
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
