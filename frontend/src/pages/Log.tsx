// SPDX-License-Identifier: GPL-3.0-or-later
import { Stack, Title } from "@mantine/core";

import { WithModule } from "../components/WithModule";
import { Placeholder } from "./Placeholder";

export function Log() {
  return (
    <Stack>
      <Title order={2}>Log</Title>
      <WithModule base="/log">{() => <Placeholder text="The forms come" issue={72} />}</WithModule>
    </Stack>
  );
}
