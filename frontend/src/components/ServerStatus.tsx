// SPDX-License-Identifier: GPL-3.0-or-later
import { Badge } from "@mantine/core";

import { useHealth } from "../api/queries";

/** Shows whether the backend answers, and which version is running. */
export function ServerStatus() {
  const health = useHealth();
  if (health.isPending) return <Badge color="gray">Connecting…</Badge>;
  if (health.isError) return <Badge color="red">Server unreachable</Badge>;
  return <Badge color="green">Server OK · v{health.data.version}</Badge>;
}
