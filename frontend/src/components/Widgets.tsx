// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Badge,
  Card,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useMemo, useState } from "react";

import type { KpiData, LineData, PlannedData, StatusBoardData } from "../api/client";
import { formatDateTime } from "../lib/format";
import { lineOption, RANGES, type Range } from "../lib/lineChart";
import { Chart } from "./Chart";

// Statuses and their colours (the journal's levels; other levels are shown plain).
const STATUS_COLOURS: Record<string, string> = {
  GOOD: "green",
  GREEN: "green",
  WATCH: "yellow",
  YELLOW: "yellow",
  LOW: "red",
  RED: "red",
  "NEEDS ATTENTION": "red",
  "WORTH NOTING": "yellow",
};

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

function shownValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "number") return String(value).replace(".", ",");
  return typeof value === "boolean" ? (value ? "Yes" : "No") : JSON.stringify(value);
}

function number(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : value.toFixed(1).replace(".", ",");
}

/** One number or status (the latest value, or the days since the latest record). */
export function KpiCard({ data }: { data: KpiData }) {
  const value: unknown = data.value;
  let shown;
  if (data.agg === "days_since_latest") {
    shown =
      typeof value === "number" ? (
        <Text fz="xl" fw={600}>
          {value === 0 ? "Today" : `${String(value)} ${value === 1 ? "day" : "days"}`}
        </Text>
      ) : (
        <Text c="dimmed">No records yet</Text>
      );
  } else if (typeof value === "string" && value in STATUS_COLOURS) {
    shown = <Status value={value} />;
  } else {
    shown = (
      <Text fz="xl" fw={600}>
        {typeof value === "string" ? formatDateTime(value) : shownValue(value)}
      </Text>
    );
  }
  return (
    <Card withBorder>
      <Text size="sm" c="dimmed">
        {data.label}
      </Text>
      {shown}
    </Card>
  );
}

const ARROWS = {
  up: { text: "▲ Improving", colour: "green" },
  down: { text: "▼ Declining", colour: "red" },
  flat: { text: "► Stable", colour: "gray" },
};

/** Per class: latest status and score, the last averages compared, the direction, LOWs. */
export function StatusBoard({ data }: { data: StatusBoardData }) {
  const n = data.compare_last;
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {data.label ?? "Status board"}
      </Title>
      <Table.ScrollContainer minWidth={640}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Class</Table.Th>
              <Table.Th>Latest status</Table.Th>
              <Table.Th>Latest score</Table.Th>
              <Table.Th>Avg last {n}</Table.Th>
              <Table.Th>Avg previous {n}</Table.Th>
              <Table.Th>Change</Table.Th>
              <Table.Th>Direction</Table.Th>
              <Table.Th>LOW (last {data.window})</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.rows.map((row) => {
              const arrow = row.direction == null ? null : ARROWS[row.direction];
              return (
                <Table.Tr key={row.label}>
                  <Table.Td fw={500}>{row.label}</Table.Td>
                  <Table.Td>
                    <Status value={row.status} />
                  </Table.Td>
                  <Table.Td>{number(row.score)}</Table.Td>
                  <Table.Td>{number(row.average_last)}</Table.Td>
                  <Table.Td>{number(row.average_previous)}</Table.Td>
                  <Table.Td>{row.change == null ? "–" : signed(row.change)}</Table.Td>
                  <Table.Td>
                    {arrow === null ? (
                      <Text c="dimmed">–</Text>
                    ) : (
                      <Text c={arrow.colour}>{arrow.text}</Text>
                    )}
                  </Table.Td>
                  <Table.Td>{row.low}</Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="xs" c="dimmed" mt="xs">
        Direction compares the average of the last {n} sessions with the {n} before (it needs{" "}
        {n + 1} or more sessions); a change smaller than the trend threshold in Settings is stable.
      </Text>
    </Card>
  );
}

function signed(value: number): string {
  const text = Math.abs(value).toFixed(1).replace(".", ",");
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

/** Metrics over the sessions with the status bands, a range picker and the rolling mean. */
export function LineCard({ data, today }: { data: LineData; today: string }) {
  const [range, setRange] = useState<Range>("last");
  const [rolling, setRolling] = useState(false);
  const option = useMemo(
    () => lineOption(data, range, rolling, today),
    [data, range, rolling, today],
  );
  const ranges = RANGES.map((r) =>
    r.value === "last" ? { ...r, label: `Last ${String(data.last)}` } : r,
  );
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={4}>{data.label ?? "Trend"}</Title>
        <Group>
          {data.rolling != null && (
            <Switch
              label={`Mean of ${String(data.rolling)}`}
              checked={rolling}
              onChange={(event) => {
                setRolling(event.currentTarget.checked);
              }}
            />
          )}
          <SegmentedControl
            aria-label="Range"
            size="xs"
            data={ranges}
            value={range}
            onChange={setRange}
          />
        </Group>
      </Group>
      {data.points.length === 0 ? (
        <Text c="dimmed">No sessions yet.</Text>
      ) : (
        <Chart option={option} label={data.label ?? "Trend"} />
      )}
    </Card>
  );
}

const NAMES: Record<string, string> = {
  heatmap_calendar: "Calendar",
  side_by_side: "Last sessions side by side",
  text_feed: "Reflections",
  table: "Table",
  monthly: "Monthly averages",
};

/** A widget the app doesn't draw yet. */
export function PlannedCard({ data }: { data: PlannedData }) {
  return (
    <Card withBorder>
      <Stack gap={4}>
        <Text fw={500}>{data.label ?? NAMES[data.kind] ?? data.kind}</Text>
        <Text size="sm" c="dimmed">
          Not drawn yet: {data.why}.
        </Text>
      </Stack>
    </Card>
  );
}
