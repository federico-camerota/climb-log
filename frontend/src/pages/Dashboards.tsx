// SPDX-License-Identifier: GPL-3.0-or-later
import { Stack, Title } from "@mantine/core";

import { WithModule } from "../components/WithModule";
import { Placeholder } from "./Placeholder";

export function Dashboards() {
  return (
    <Stack>
      <Title order={2}>Dashboards</Title>
      <WithModule base="/dashboards">
        {() => <Placeholder text="The module's dashboard comes" issue={77} />}
      </WithModule>
    </Stack>
  );
}
