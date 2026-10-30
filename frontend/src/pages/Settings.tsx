// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Badge, Card, Group, List, Loader, Stack, Text, Title } from "@mantine/core";

import type { ModuleInfo } from "../api/client";
import { useModules } from "../api/queries";

function ModuleCard({ module }: { module: ModuleInfo }) {
  const ok = module.problems.length === 0;
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Text fw={500}>{module.name ?? module.id}</Text>
        <Badge color={ok ? "green" : "red"}>{ok ? "loaded" : "doesn't load"}</Badge>
      </Group>
      <Text size="sm" c="dimmed">
        {module.id}
        {module.version != null && ` · version ${String(module.version)}`}
        {module.kind != null && ` · ${module.kind}`}
      </Text>
      {!ok && (
        <List size="sm" c="red">
          {module.problems.map((problem) => (
            <List.Item key={problem}>{problem}</List.Item>
          ))}
        </List>
      )}
    </Card>
  );
}

export function Settings() {
  const query = useModules();
  return (
    <Stack>
      <Title order={2}>Settings</Title>
      <Title order={3}>Modules</Title>
      {query.isPending && <Loader />}
      {query.isError && (
        <Alert color="red" title="Can't list the modules">
          {query.error.message}
        </Alert>
      )}
      {query.isSuccess && (
        <>
          {query.data.problems.length > 0 && (
            <Alert color="red" title="App config problems">
              <List size="sm">
                {query.data.problems.map((problem) => (
                  <List.Item key={problem}>{problem}</List.Item>
                ))}
              </List>
            </Alert>
          )}
          {query.data.modules.length === 0 && <Text>No modules in the app config.</Text>}
          {query.data.modules.map((module) => (
            <ModuleCard key={module.id} module={module} />
          ))}
        </>
      )}
    </Stack>
  );
}
