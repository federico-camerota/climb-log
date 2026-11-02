// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Badge,
  Card,
  ColorSwatch,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  useComputedColorScheme,
} from "@mantine/core";
import { useMemo, useState } from "react";

import type {
  HeatmapData,
  KpiData,
  LineData,
  MonthlyData,
  PlannedData,
  SideBySideData,
  StatusBoardData,
  TableData,
  TextFeedData,
} from "../api/client";
import { formatDateTime, monthName } from "../lib/format";
import { CALENDAR_HEIGHT, dayKey, heatmapOption, PIECES } from "../lib/heatmap";
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
  if (typeof value === "string") return value;
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
          {data.x == null && (
            <SegmentedControl
              aria-label="Range"
              size="xs"
              data={ranges}
              value={range}
              onChange={setRange}
            />
          )}
        </Group>
      </Group>
      {data.points.length === 0 && (data.x ?? []).length === 0 ? (
        <Text c="dimmed">No sessions yet.</Text>
      ) : (
        <Chart option={option} label={data.label ?? "Trend"} />
      )}
    </Card>
  );
}

const NAMES: Record<string, string> = {
  weekbars: "Weekly bars",
  box_by: "Distribution",
  line: "Trend",
  radar: "Radar",
  status_strip: "Status strip",
  delta_table: "Changes",
  ladder: "Ladder",
  program_grid: "Program",
  before_after: "Before and after",
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

/** A cell's value: a status as a badge, a date day first, a number with a comma. */
export function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <Text c="dimmed">–</Text>;
  if (typeof value === "string" && value in STATUS_COLOURS) return <Status value={value} />;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value)) {
    return <>{formatDateTime(value)}</>;
  }
  return <>{shownValue(value)}</>;
}

function dayLabel(date: string, key: Record<string, unknown>): string {
  const extra = Object.values(key).filter((v) => typeof v === "number" && v > 1);
  return `${formatDateTime(date)}${extra.length > 0 ? ` (${extra.map(String).join(", ")})` : ""}`;
}

/** A day per square from the first record's month: coloured by its sessions' worst status,
 * rest days lighter, a letter for the kind of day; a caption and a legend below. */
export function HeatmapCard({ data }: { data: HeatmapData }) {
  const dark = useComputedColorScheme("light") === "dark";
  const option = useMemo(() => {
    const body = getComputedStyle(document.body).getPropertyValue("--mantine-color-body").trim();
    return heatmapOption(data, dark, body === "" ? undefined : body);
  }, [data, dark]);
  const shown = new Set(data.days.map(dayKey));
  return (
    <Card withBorder>
      <Title order={4}>{data.label ?? "Calendar"}</Title>
      <Text size="sm" c="dimmed" mb="xs">
        Each square is a day, coloured by that day&apos;s session status (the worse of two
        sessions); rest days are lighter. Hover a day for details.
      </Text>
      <div style={{ overflowX: "auto" }}>
        <Chart option={option} height={CALENDAR_HEIGHT} label={data.label ?? "Calendar"} />
      </div>
      <Group gap="md" mt="xs" aria-label="Legend">
        {PIECES.filter((p) => shown.has(p.key) || !p.key.startsWith("rest ")).map((p) => (
          <Group key={p.key} gap={4} wrap="nowrap">
            <ColorSwatch color={p.color} size={12} radius={2} withShadow={false} />
            <Text size="xs">{p.label}</Text>
          </Group>
        ))}
        {data.marks.map((m) => (
          <Text key={m.letter} size="xs">
            <b>{m.letter}</b> {m.label}
          </Text>
        ))}
      </Group>
    </Card>
  );
}

const SIDE_COUNTS = [4, 8, 12];

/** The latest sessions side by side, newest first, and the latest one's notes. */
export function SideBySideCard({ data }: { data: SideBySideData }) {
  const [count, setCount] = useState(String(data.last));
  const shown = data.records.slice(0, Number(count));
  const counts = [...new Set([data.last, ...SIDE_COUNTS])].sort((a, b) => a - b);
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={4}>{data.label ?? "Last sessions"}</Title>
        <SegmentedControl
          aria-label="Sessions shown"
          size="xs"
          data={counts.map(String)}
          value={count}
          onChange={setCount}
        />
      </Group>
      {shown.length === 0 ? (
        <Text c="dimmed">No sessions yet.</Text>
      ) : (
        <Table.ScrollContainer minWidth={240 + 120 * shown.length}>
          <Table striped withColumnBorders>
            <Table.Thead>
              <Table.Tr>
                <Table.Th />
                {shown.map((r, i) => (
                  <Table.Th key={i}>{dayLabel(r.date, r.key)}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.groups.map((group) => [
                <Table.Tr key={group.label}>
                  <Table.Td
                    colSpan={shown.length + 1}
                    fw={600}
                    bg="var(--mantine-color-default-hover)"
                  >
                    {group.label}
                  </Table.Td>
                </Table.Tr>,
                ...group.rows.map((row) => (
                  <Table.Tr key={row.field}>
                    <Table.Td>{row.label}</Table.Td>
                    {shown.map((r, i) => (
                      <Table.Td key={i}>
                        <Value value={r.values[row.field]} />
                      </Table.Td>
                    ))}
                  </Table.Tr>
                )),
              ])}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {data.notes.length > 0 && shown.length > 0 && (
        <Stack gap={4} mt="md">
          <Text fw={600}>Notes from the latest session</Text>
          {data.notes.map((note) => (
            <Text key={note.field} size="sm" lang="it">
              <Text span c="dimmed">
                {note.label}:
              </Text>{" "}
              {note.text ?? "—"}
            </Text>
          ))}
        </Stack>
      )}
    </Card>
  );
}

/** The best-scored texts of the last days per list, and the records needing attention. */
export function TextFeedCard({ data }: { data: TextFeedData }) {
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {data.label ?? "Notes"}
      </Title>
      <Stack>
        {data.lists.map((list) => (
          <Stack key={list.label} gap={4}>
            <Text fw={600}>{list.label}</Text>
            {list.items.length === 0 ? (
              <Text size="sm" c="dimmed">
                No scored entries in the last {data.window_days} days.
              </Text>
            ) : (
              list.items.map((item, i) => (
                <Text key={i} size="sm" lang="it">
                  {item.score != null && (
                    <Badge variant="light" mr="xs">
                      {shownValue(item.score)}
                    </Badge>
                  )}
                  {item.text}{" "}
                  <Text span size="xs" c="dimmed">
                    {dayLabel(item.date, item.key)}
                  </Text>
                </Text>
              ))
            )}
          </Stack>
        ))}
        {data.attention != null && data.attention.items.length > 0 && (
          <Stack gap={4}>
            <Text fw={600} c="red">
              {data.attention.label}
            </Text>
            {data.attention.items.map((item, i) => (
              <Text key={i} size="sm" lang="it">
                <Text span size="xs" c="dimmed" mr="xs">
                  {dayLabel(item.date, item.key)}
                </Text>
                {item.texts.join(" · ")}
              </Text>
            ))}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}

/** An entity's recent records as a table, with averages and the latest note. */
export function TableCard({ data }: { data: TableData }) {
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {data.label ?? "Records"}
      </Title>
      {data.rows.length === 0 ? (
        <Text c="dimmed">None in this period.</Text>
      ) : (
        <Table.ScrollContainer minWidth={560}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                {data.columns.map((c) => (
                  <Table.Th key={c.field}>{c.label}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.rows.map((row, i) => (
                <Table.Tr key={i}>
                  {data.columns.map((c) => (
                    <Table.Td key={c.field}>
                      <Value value={row[c.field]} />
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <Text size="sm" mt="xs">
        {data.rows.length} logged
        {data.averages.map((a) => ` · average ${a.label.toLowerCase()} ${number(a.value)}`)}
      </Text>
      {data.note != null && (
        <Text size="sm" mt={4} lang="it">
          <Text span c="dimmed">
            Latest note ({formatDateTime(data.note.date)}):
          </Text>{" "}
          {data.note.text}
        </Text>
      )}
    </Card>
  );
}

const MONTH_COUNTS = ["6", "12", "24", "All"];

/** Per month: the records, each class's average, the overall, LOW, and the extra columns. */
export function MonthlyCard({ data }: { data: MonthlyData }) {
  const [count, setCount] = useState(String(data.months));
  const choices = [...new Set([String(data.months), ...MONTH_COUNTS])];
  const rows = count === "All" ? data.rows : data.rows.slice(-Number(count));
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={4}>{data.label ?? "Monthly averages"}</Title>
        <SegmentedControl
          aria-label="Months shown"
          size="xs"
          data={choices}
          value={count}
          onChange={setCount}
        />
      </Group>
      <Table.ScrollContainer minWidth={720}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Month</Table.Th>
              <Table.Th>{data.count_label}</Table.Th>
              {data.classes.map((c) => (
                <Table.Th key={c}>{c}</Table.Th>
              ))}
              {data.overall != null && <Table.Th>{data.overall}</Table.Th>}
              {data.low && <Table.Th>LOW</Table.Th>}
              {data.extra.map((e) => (
                <Table.Th key={e}>{e}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {[...rows].reverse().map((row) => (
              <Table.Tr key={row.month}>
                <Table.Td>{monthName(row.month)}</Table.Td>
                <Table.Td>{row.count}</Table.Td>
                {row.classes.map((v, i) => (
                  <Table.Td key={i}>{number(v)}</Table.Td>
                ))}
                {data.overall != null && <Table.Td fw={500}>{number(row.overall)}</Table.Td>}
                {data.low && <Table.Td>{row.low ?? "–"}</Table.Td>}
                {row.extra.map((v, i) => (
                  <Table.Td key={i}>{v !== null && Number.isInteger(v) ? v : number(v)}</Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}
