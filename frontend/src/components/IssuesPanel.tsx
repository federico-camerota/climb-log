// SPDX-License-Identifier: GPL-3.0-or-later
import { Accordion, Alert, Button, Group, Modal, Stack, Table, Text } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { adoptRow, deleteRow, type Issue, type ModuleInfo } from "../api/client";
import { entityOf } from "../forms/schema";

// Rows that are no record, which can be deleted on their own (D-082).
const DELETABLE = new Set(["left_out", "orphan", "orphan_child"]);

interface Props {
  module: ModuleInfo;
  entity: string;
  issues: Issue[];
}

/** Every data issue of the entity's tabs, also those of rows that are no record (an orphan
 * section row, a row without a date): where it is and what is wrong (D-046). A row that is no
 * record can be deleted, an orphan section row given its record (D-082); a record's own issues
 * are fixed in its form (click the row in the table). */
export function IssuesPanel({ module, entity, issues }: Props) {
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<Issue | null>(null);
  const main = entityOf(module, entity)?.label ?? entity;
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ["records", module.id, entity] });
    void queryClient.invalidateQueries({ queryKey: ["today"] });
    void queryClient.invalidateQueries({ queryKey: ["recommendation"] });
  };
  const remove = useMutation({
    mutationFn: (issue: Issue) => deleteRow(module.id, entity, issue.tab, issue.row ?? 0),
    onSuccess: () => {
      setDeleting(null);
      done();
    },
  });
  const adopt = useMutation({
    mutationFn: (issue: Issue) => adoptRow(module.id, entity, issue.tab, issue.row ?? 0),
    onSuccess: done,
  });
  if (issues.length === 0) return null;
  const sorted = [...issues].sort(
    (a, b) => a.tab.localeCompare(b.tab) || (a.row ?? 0) - (b.row ?? 0),
  );
  return (
    <>
      <Accordion variant="contained">
        <Accordion.Item value="issues">
          <Accordion.Control>
            <Text c="red">
              {issues.length} data {issues.length === 1 ? "issue" : "issues"}
            </Text>
          </Accordion.Control>
          <Accordion.Panel>
            {adopt.isError && (
              <Alert color="red" title="Not done" mb="sm">
                {adopt.error.message}
              </Alert>
            )}
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Tab</Table.Th>
                  <Table.Th>Row</Table.Th>
                  <Table.Th>Column</Table.Th>
                  <Table.Th>Problem</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sorted.map((issue, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{issue.tab}</Table.Td>
                    <Table.Td>{issue.row ?? ""}</Table.Td>
                    <Table.Td>{issue.field ?? ""}</Table.Td>
                    <Table.Td>{issue.message}</Table.Td>
                    <Table.Td>
                      {issue.row !== null && (
                        <Group gap="xs" wrap="nowrap">
                          {issue.kind === "orphan" && (
                            <Button
                              size="compact-xs"
                              variant="light"
                              loading={adopt.isPending && adopt.variables === issue}
                              onClick={() => {
                                adopt.mutate(issue);
                              }}
                            >
                              Create the {main.toLowerCase()}
                            </Button>
                          )}
                          {DELETABLE.has(issue.kind) && (
                            <Button
                              size="compact-xs"
                              variant="light"
                              color="red"
                              onClick={() => {
                                remove.reset();
                                setDeleting(issue);
                              }}
                            >
                              Delete row
                            </Button>
                          )}
                        </Group>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
      <Modal
        opened={deleting !== null}
        onClose={() => {
          setDeleting(null);
        }}
        title={`Delete ${deleting?.tab ?? ""} row ${String(deleting?.row ?? "")}?`}
      >
        <Stack>
          <Text size="sm">
            The row is marked in the sheet's <code>deleted</code> column, so the app ignores it;
            clearing that cell brings it back.
          </Text>
          {remove.isError && (
            <Alert color="red" title="Not deleted">
              {remove.error.message}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setDeleting(null);
              }}
            >
              Cancel
            </Button>
            <Button
              color="red"
              loading={remove.isPending}
              onClick={() => {
                if (deleting !== null) remove.mutate(deleting);
              }}
            >
              Delete row
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
