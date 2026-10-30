// SPDX-License-Identifier: GPL-3.0-or-later
import { Stack, Title } from "@mantine/core";

import { Placeholder } from "./Placeholder";

export function Today() {
  return (
    <Stack>
      <Title order={2}>Today</Title>
      <Placeholder text="The due forms, log check and recommendation come" issue={74} />
    </Stack>
  );
}
