// SPDX-License-Identifier: GPL-3.0-or-later
import { Accordion, Table, Text } from "@mantine/core";

import type { Issue } from "../api/client";

/** Every data issue of the entity's tabs, also those of rows that are no record (an orphan
 * section row, a row without a date): where it is and what is wrong (D-046). */
export function IssuesPanel({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return null;
  const sorted = [...issues].sort(
    (a, b) => a.tab.localeCompare(b.tab) || (a.row ?? 0) - (b.row ?? 0),
  );
  return (
    <Accordion variant="contained">
      <Accordion.Item value="issues">
        <Accordion.Control>
          <Text c="red">
            {issues.length} data {issues.length === 1 ? "issue" : "issues"}
          </Text>
        </Accordion.Control>
        <Accordion.Panel>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Tab</Table.Th>
                <Table.Th>Row</Table.Th>
                <Table.Th>Column</Table.Th>
                <Table.Th>Problem</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sorted.map((issue, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{issue.tab}</Table.Td>
                  <Table.Td>{issue.row ?? ""}</Table.Td>
                  <Table.Td>{issue.field ?? ""}</Table.Td>
                  <Table.Td>{issue.message}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
}
