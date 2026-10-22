// SPDX-License-Identifier: GPL-3.0-or-later
import { AppShell, Group, Text, Title } from "@mantine/core";

import { ServerStatus } from "./components/ServerStatus";

export function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={3}>climb-log</Title>
          <ServerStatus />
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Text c="dimmed">Nothing here yet.</Text>
      </AppShell.Main>
    </AppShell>
  );
}
