// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Text } from "@mantine/core";

import type { Records } from "../api/client";
import { formatDateTime } from "../lib/format";

/** When the data shown was read, and a warning when the sheet couldn't be reached (D-055). */
export function DataStatus({ records }: { records: Records }) {
  const asOf = records.as_of === null ? null : formatDateTime(records.as_of);
  return (
    <>
      {records.offline && (
        <Alert color="orange" title="Offline · read-only">
          The workbook can&apos;t be reached: this is the last snapshot
          {asOf === null ? "." : `, read on ${asOf}.`}
        </Alert>
      )}
      {asOf !== null && (
        <Text size="sm" c="dimmed">
          As of {asOf}
        </Text>
      )}
    </>
  );
}
