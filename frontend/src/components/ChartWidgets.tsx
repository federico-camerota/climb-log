// SPDX-License-Identifier: GPL-3.0-or-later
// Cards of the widget library v1 (#98, D-091): each draws the backend's numbers with ECharts.
import { Card, Group, SegmentedControl, Select, Stack, Table, Text, Title } from "@mantine/core";
import { useMemo, useState } from "react";

import type {
  BarsData,
  BodyHeatmapData,
  BoxByData,
  GradesData,
  PrePostData,
  ScatterData,
  StackedData,
  TrainingLoadData,
  WeekbarsData,
} from "../api/client";
import {
  barsOption,
  bodyOption,
  boxOption,
  changeTone,
  decimal,
  gradesOption,
  loadOption,
  othersOption,
  pairStats,
  prePostOption,
  pyramidOption,
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
  const others = useMemo(() => othersOption(data), [data]);
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
          {data.others.length > 0 && (
            <>
              <Text size="sm" fw={500}>
                {data.others.join(", ")}: in its own units, not in the ratio
              </Text>
              <Chart option={others} height={220} label={data.others.join(", ")} />
            </>
          )}
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Week</Table.Th>
                <Table.Th>Load</Table.Th>
                {data.others.map((label) => (
                  <Table.Th key={label}>{label}</Table.Th>
                ))}
                <Table.Th>Sessions</Table.Th>
                <Table.Th>Days trained</Table.Th>
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
                    <Table.Td key={data.others[i] ?? i}>
                      {decimal(value)}
                      {(week.others_without[i] ?? 0) > 0 && (
                        <Text span c="orange" size="xs">
                          {" "}
                          ({week.others_without[i]} without load)
                        </Text>
                      )}
                    </Table.Td>
                  ))}
                  <Table.Td>{week.sessions}</Table.Td>
                  <Table.Td>{week.days}</Table.Td>
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

/** Before → after per pair (mood, each body part), for all sessions or one type (D-093). */
export function PrePostCard({ data }: { data: PrePostData }) {
  const [group, setGroup] = useState("-1");
  const index = Number(group);
  const option = useMemo(() => prePostOption(data, index), [data, index]);
  const stats = pairStats(data, index);
  const title = data.label ?? "Before → after";
  const empty = data.pairs.every((p) => p.all.n === 0);
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={4}>{title}</Title>
        {data.groups.length > 0 && (
          <Select
            aria-label="Session type"
            size="xs"
            allowDeselect={false}
            data={[
              { value: "-1", label: "All sessions" },
              ...data.groups.map((g, i) => ({ value: String(i), label: g })),
            ]}
            value={group}
            onChange={(value) => {
              setGroup(value ?? "-1");
            }}
          />
        )}
      </Group>
      {empty ? (
        <Text c="dimmed">No session with both answers yet.</Text>
      ) : (
        <Stack gap="sm">
          <Chart
            option={option}
            label={title}
            height={Math.max(200, 40 * data.pairs.length + 72)}
          />
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th />
                <Table.Th>Before</Table.Th>
                <Table.Th>After</Table.Th>
                <Table.Th>Change</Table.Th>
                <Table.Th>n</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.pairs.map((pair, i) => {
                const s = stats[i] ?? pair.all;
                const sign = s.change !== null && s.change > 0 ? "+" : "";
                return (
                  <Table.Tr key={pair.label}>
                    <Table.Td>
                      {pair.label}
                      {pair.lower_better === true && " ↓"}
                    </Table.Td>
                    <Table.Td>{decimal(s.pre)}</Table.Td>
                    <Table.Td>{decimal(s.post)}</Table.Td>
                    <Table.Td>
                      <Text span c={changeTone(s.change, pair.lower_better)}>
                        {s.change === null ? "–" : sign + decimal(s.change)}
                      </Text>
                    </Table.Td>
                    <Table.Td>{s.n}</Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
          <Text size="xs" c="dimmed">
            Means over the sessions with both answers (n). ↓: lower is better. Soreness changes
            aren&apos;t coloured: it is expected to rise after a session.
          </Text>
        </Stack>
      )}
    </Card>
  );
}

/** The template's fields (body parts) by week, for one source at a time (D-093). */
export function BodyHeatmapCard({ data }: { data: BodyHeatmapData }) {
  const [source, setSource] = useState("0");
  const index = Number(source);
  const option = useMemo(() => bodyOption(data, index), [data, index]);
  const title = data.label ?? "By week";
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={4}>{title}</Title>
        <SegmentedControl
          aria-label="Source"
          size="xs"
          data={data.sources.map((s, i) => ({ value: String(i), label: s.label }))}
          value={source}
          onChange={setSource}
        />
      </Group>
      {data.weeks.length === 0 ? (
        <Text c="dimmed">Nothing logged yet.</Text>
      ) : (
        <Chart option={option} label={title} height={Math.max(220, 36 * data.parts.length + 96)} />
      )}
    </Card>
  );
}

/** The hardest grade tried over time, its pyramid per period, by setting and by venue (D-094). */
export function GradesCard({ data }: { data: GradesData }) {
  const option = useMemo(() => gradesOption(data), [data]);
  const periods = data.pyramid.periods;
  const [row, setRow] = useState("0");
  const [period, setPeriod] = useState(String(Math.max(0, periods.length - 1)));
  const pyramid = useMemo(
    () => pyramidOption(data, Number(row), Number(period)),
    [data, row, period],
  );
  const title = data.label ?? "Grades";
  const rows = data.pyramid.rows[Number(row)];
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {title}
      </Title>
      {data.series.length === 0 ? (
        <Text c="dimmed">No grades logged yet.</Text>
      ) : (
        <Stack gap="sm">
          <Chart option={option} label={title} />
          <Group justify="space-between">
            <Text fw={500}>Sessions by hardest grade tried</Text>
            <Group gap="xs">
              <Select
                aria-label="Grades of"
                size="xs"
                allowDeselect={false}
                data={data.pyramid.rows.map((r, i) => ({ value: String(i), label: r.label }))}
                value={row}
                onChange={(value) => {
                  setRow(value ?? "0");
                }}
              />
              <Select
                aria-label="Period"
                size="xs"
                allowDeselect={false}
                data={periods.map((p, i) => ({ value: String(i), label: p }))}
                value={period}
                onChange={(value) => {
                  setPeriod(value ?? "0");
                }}
              />
            </Group>
          </Group>
          <Chart
            option={pyramid}
            label={`Sessions by grade, ${rows?.label ?? ""}`}
            height={Math.max(160, 28 * (rows?.grades.length ?? 0) + 48)}
          />
          {data.by_setting.length > 0 && (
            <GradeTable
              head="Setting"
              rows={data.by_setting.map((r) => ({ ...r, name: r.setting }))}
            />
          )}
          {data.by_venue.length > 0 && (
            <GradeTable head="Venue" rows={data.by_venue.map((r) => ({ ...r, name: r.venue }))} />
          )}
          <Text size="xs" c="dimmed">
            The hardest grade tried per session (not sends). French and gym grades are never
            converted; each gym grades its own way, so its grades are a series of their own.
            {data.unparsed > 0 && ` ${String(data.unparsed)} value(s) that aren't grades left out.`}
          </Text>
        </Stack>
      )}
    </Card>
  );
}

function GradeTable({
  head,
  rows,
}: {
  head: string;
  rows: { name: string; system: string; sessions: number; hardest: string; median: string }[];
}) {
  return (
    <Table striped>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{head}</Table.Th>
          <Table.Th>Grades</Table.Th>
          <Table.Th>Sessions</Table.Th>
          <Table.Th>Hardest</Table.Th>
          <Table.Th>Median</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r) => (
          <Table.Tr key={`${r.name}-${r.system}`}>
            <Table.Td>{r.name}</Table.Td>
            <Table.Td>{r.system === "french" ? "French" : "Gym"}</Table.Td>
            <Table.Td>{r.sessions}</Table.Td>
            <Table.Td>{r.hardest}</Table.Td>
            <Table.Td>{r.median}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
