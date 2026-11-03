// SPDX-License-Identifier: GPL-3.0-or-later
// Cards of the widget library v1 (#98, D-091): each draws the backend's numbers with ECharts.
import { Card, Text, Title } from "@mantine/core";
import { useMemo } from "react";

import type { BarsData, BoxByData, ScatterData, StackedData, WeekbarsData } from "../api/client";
import {
  barsOption,
  boxOption,
  decimal,
  scatterOption,
  stackedOption,
  weekbarsOption,
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
