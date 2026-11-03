// SPDX-License-Identifier: GPL-3.0-or-later
// Cards of the widget library v1 (#98, D-091): each draws the backend's numbers with ECharts.
import { Card, Group, Stack, Table, Text, Title } from "@mantine/core";
import { useMemo } from "react";

import type {
  BarsData,
  BoxByData,
  ScatterData,
  StackedData,
  TrainingLoadData,
  WeekbarsData,
} from "../api/client";
import {
  barsOption,
  boxOption,
  decimal,
  loadOption,
  scatterOption,
  shortDate,
  stackedOption,
  weekbarsOption,
  zoneOf,
} from "../lib/charts";
import { Chart } from "./Chart";

function ChartCard({
  title,
  empty,
  children,
  footer,
}: {
  title: string;
  empty: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {title}
      </Title>
      {empty ? <Text c="dimmed">Nothing logged yet.</Text> : children}
      {!empty && footer}
    </Card>
  );
}

export function BarsCard({ data }: { data: BarsData }) {
  const option = useMemo(() => barsOption(data), [data]);
  const title = data.label ?? data.metric;
  const n = data.n.reduce((a, b) => a + b, 0);
  return (
    <ChartCard
      title={title}
      empty={n === 0}
      footer={
        <Text size="xs" c="dimmed">
          {data.agg} of {data.metric}; n = {n}
        </Text>
      }
    >
      <Chart option={option} label={title} />
    </ChartCard>
  );
}

export function WeekbarsCard({ data }: { data: WeekbarsData }) {
  const option = useMemo(() => weekbarsOption(data), [data]);
  const title = data.label ?? "Per week";
  return (
    <ChartCard title={title} empty={data.stacks.length === 0}>
      <Chart option={option} label={title} />
    </ChartCard>
  );
}

export function StackedCard({ data }: { data: StackedData }) {
  const option = useMemo(() => stackedOption(data), [data]);
  const title = data.label ?? data.series.map((s) => s.label).join(" + ");
  const empty = data.series.every((s) => s.values.every((v) => v === null));
  return (
    <ChartCard title={title} empty={empty}>
      <Chart option={option} label={title} />
    </ChartCard>
  );
}

export function BoxByCard({ data }: { data: BoxByData }) {
  const option = useMemo(() => boxOption(data), [data]);
  const title = data.label ?? `${data.metric} by ${data.by}`;
  return (
    <ChartCard
      title={title}
      empty={data.boxes.length === 0}
      footer={
        <Text size="xs" c="dimmed">
          Boxes from the first to the third quartile with the median; whiskers to the furthest
          values within 1.5 × the box; dots beyond.
        </Text>
      }
    >
      <Chart option={option} label={title} />
    </ChartCard>
  );
}

export function ScatterCard({ data }: { data: ScatterData }) {
  const option = useMemo(() => scatterOption(data), [data]);
  const title = data.label ?? `${data.y_label} vs ${data.x_label}`;
  const lag = data.lag === 0 ? "" : `; ${data.y_label} ${String(data.lag)} day(s) later`;
  const trend = data.trend
    ? `; trend: ${decimal(data.trend.slope)} per unit of ${data.x_label}`
    : "";
  return (
    <ChartCard
      title={title}
      empty={data.n === 0}
      footer={
        <Text size="xs" c="dimmed">
          n = {data.n}
          {lag}
          {trend}
        </Text>
      }
    >
      <Chart option={option} label={title} />
    </ChartCard>
  );
}

/** Weekly training load with the ACWR, monotony, strain and streaks (D-092). */
export function TrainingLoadCard({ data }: { data: TrainingLoadData }) {
  const option = useMemo(() => loadOption(data), [data]);
  const title = data.label ?? "Training load";
  const recent = [...data.weeks].reverse().slice(0, data.shown);
  let ratio: string;
  if (data.acwr_today !== null) {
    ratio = `${decimal(data.acwr_today)} (${zoneOf(data.acwr_today, data.zones)})`;
  } else if (data.baseline_from !== null) {
    ratio = `building a baseline until ${shortDate(data.baseline_from)}`;
  } else {
    ratio = "–";
  }
  const longest = data.longest_streak;
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {title}
      </Title>
      {data.weeks.length === 0 ? (
        <Text c="dimmed">Nothing logged yet.</Text>
      ) : (
        <Stack gap="sm">
          <Group gap="xl">
            <Text size="sm">
              <b>Acute:chronic ratio today:</b> {ratio}
            </Text>
            <Text size="sm">
              <b>Current streak:</b> {data.current_streak} day(s)
            </Text>
            {longest !== null && (
              <Text size="sm">
                <b>Longest streak:</b> {longest.days} day(s), {shortDate(longest.start)}–
                {shortDate(longest.end)}
              </Text>
            )}
          </Group>
          <Chart option={option} label={title} />
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Week</Table.Th>
                <Table.Th>Load</Table.Th>
                {data.others.map((label) => (
                  <Table.Th key={label}>{label}</Table.Th>
                ))}
                <Table.Th>Sessions</Table.Th>
                <Table.Th>Rest days</Table.Th>
                <Table.Th>ACWR</Table.Th>
                <Table.Th>Monotony</Table.Th>
                <Table.Th>Strain</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {recent.map((week) => (
                <Table.Tr key={week.label}>
                  <Table.Td>
                    {week.label} ({shortDate(week.start)})
                  </Table.Td>
                  <Table.Td>
                    {decimal(week.load)}
                    {week.without_load > 0 && (
                      <Text span c="orange" size="xs">
                        {" "}
                        ({week.without_load} without load)
                      </Text>
                    )}
                  </Table.Td>
                  {week.others.map((value, i) => (
                    <Table.Td key={data.others[i] ?? i}>{decimal(value)}</Table.Td>
                  ))}
                  <Table.Td>{week.sessions}</Table.Td>
                  <Table.Td>{week.rest_days}</Table.Td>
                  <Table.Td>{decimal(week.acwr)}</Table.Td>
                  <Table.Td>{decimal(week.monotony)}</Table.Td>
                  <Table.Td>{decimal(week.strain)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Text size="xs" c="dimmed">
            Load = duration × effort (session RPE); a session missing either counts as 0. The ratio
            compares the last {data.acute} days with the last {data.chronic} (exponentially
            weighted): context, not a rule. Monotony = the week&apos;s mean daily load over its
            spread; strain = load × monotony.
            {data.absent.length > 0 && ` Not found in the app config: ${data.absent.join(", ")}.`}
          </Text>
        </Stack>
      )}
    </Card>
  );
}
