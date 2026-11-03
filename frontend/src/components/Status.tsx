// SPDX-License-Identifier: GPL-3.0-or-later
import { Badge, Text } from "@mantine/core";

import { STATUS_COLOURS } from "../lib/status";

export function Status({ value }: { value: unknown }) {
  if (typeof value !== "string" || value === "") return <Text c="dimmed">–</Text>;
  const colour = STATUS_COLOURS[value];
  return colour === undefined ? (
    <Text>{value}</Text>
  ) : (
    <Badge variant="light" color={colour}>
      {value}
    </Badge>
  );
}
