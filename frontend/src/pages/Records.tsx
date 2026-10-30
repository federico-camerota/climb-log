// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Loader, Stack, Text, Title } from "@mantine/core";

import { useRecords } from "../api/queries";
import { DataStatus } from "../components/DataStatus";
import { WithModule } from "../components/WithModule";
import { Placeholder } from "./Placeholder";

function Summary({ module, entity }: { module: string; entity: string }) {
  const query = useRecords(module, entity);
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
      <Placeholder text="The records table comes" issue={75} />
    </Stack>
  );
}

export function Records() {
  return (
    <Stack>
      <Title order={2}>Records</Title>
      <WithModule base="/records" perEntity>
        {({ module, entity }) => <Summary module={module.id} entity={entity} />}
      </WithModule>
    </Stack>
  );
}
