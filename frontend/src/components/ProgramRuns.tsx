// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Button, Group, Loader, Modal, Stack, Table, Text, TextInput } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { startRun, type RunList } from "../api/client";
import { useRuns } from "../api/queries";
import { formatDateTime } from "../lib/format";
import { describePosition, weekMonday } from "../lib/weeks";

/** A program module's runs on Settings (D-109): each run's start and end, today's run and week,
 * and a new run started on an ISO week (its row goes to the Runs tab, as if typed there). */
export function ProgramRuns({ module }: { module: string }) {
  const query = useRuns(module);
  const [open, setOpen] = useState(false);
  if (query.isPending) return <Loader size="sm" />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't read the runs">
        {query.error.message}
      </Alert>
    );
  }
  const data = query.data;
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>
        Runs
      </Text>
      <Text size="sm">Today: {describePosition(data)}</Text>
      {data.runs.length > 0 && (
        <Table withTableBorder={false} verticalSpacing={2}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Run</Table.Th>
              <Table.Th>Start week</Table.Th>
              <Table.Th>From</Table.Th>
              <Table.Th>To (week {data.weeks})</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.runs.map((run) => (
              <Table.Tr key={run.number}>
                <Table.Td>{run.number}</Table.Td>
                <Table.Td>{run.start_week}</Table.Td>
                <Table.Td>{formatDateTime(run.start)}</Table.Td>
                <Table.Td>{formatDateTime(run.end)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {data.issues.map((issue) => (
        <Text key={`${String(issue.row)}-${issue.message}`} size="sm" c="orange">
          {issue.row !== null ? `Runs, row ${String(issue.row)}: ` : "Runs: "}
          {issue.message}
        </Text>
      ))}
      <Group>
        <Button
          size="xs"
          variant="light"
          disabled={data.offline}
          title={data.offline ? "The workbook can't be reached: read-only" : undefined}
          onClick={() => {
            setOpen(true);
          }}
        >
          Start a new run…
        </Button>
      </Group>
      {open && (
        <StartRun
          module={module}
          data={data}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </Stack>
  );
}

/** The Log page's line under the date (D-109): the run and week the record will belong to,
 * read-only, as the app and the sheet compute them from the date. */
export function RunOfDay({ module, date }: { module: string; date: string }) {
  const query = useRuns(module, date);
  if (!query.isSuccess) return null;
  const data = query.data;
  const text =
    data.current === null && data.runs.length === 0
      ? "No run has started yet: start one in Settings."
      : describePosition(data);
  return (
    <Text size="sm" c={data.current === null ? "orange" : "dimmed"}>
      {text.charAt(0).toUpperCase() + text.slice(1)}
    </Text>
  );
}

function StartRun({
  module,
  data,
  onClose,
}: {
  module: string;
  data: RunList;
  onClose: () => void;
}) {
  const [week, setWeek] = useState(data.next_week);
  const queryClient = useQueryClient();
  const start = useMutation({
    mutationFn: () => startRun(module, week.trim()),
    onSuccess: () => {
      // the runs, and the Log page's run line of any day, are read again
      void queryClient.invalidateQueries({ queryKey: ["runs", module] });
      // every record's run and week may change: read them again
      void queryClient.invalidateQueries({ queryKey: ["records", module] });
      void queryClient.invalidateQueries({ queryKey: ["view", module] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      onClose();
    },
  });
  const monday = weekMonday(week);
  const number = Math.max(0, ...data.runs.map((r) => r.number)) + 1;
  return (
    <Modal opened onClose={onClose} title="Start a new run">
      <Stack>
        <TextInput
          label="Start week"
          description="An ISO week, like 2026-W47: week 1 starts on its Monday"
          value={week}
          error={week.trim() !== "" && monday === null ? "Not a week like 2026-W47" : undefined}
          onChange={(event) => {
            setWeek(event.currentTarget.value);
          }}
        />
        {monday !== null && (
          <Text size="sm">
            Week 1 of run {number} starts on Monday {formatDateTime(monday)}.
          </Text>
        )}
        {start.isError && (
          <Alert color="red" title="Not started">
            {start.error.message}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={monday === null}
            loading={start.isPending}
            onClick={() => {
              start.mutate();
            }}
          >
            Start run {number}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
