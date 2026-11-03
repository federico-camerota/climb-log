// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Alert,
  Card,
  Group,
  Loader,
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import dayjs from "dayjs";
import { useSearchParams } from "react-router";

import type { MetricInfo } from "../api/client";
import { useMetricQuery, useMetrics } from "../api/queries";
import { Chart } from "../components/Chart";
import {
  exploreOption,
  fits,
  metricGroup,
  metricNames,
  metricQuery,
  readState,
  writeState,
  type AggKey,
  type ExploreState,
  type GroupKey,
  type RangeKey,
} from "../lib/explore";

const RANGES: { value: RangeKey; label: string }[] = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "all", label: "All" },
  { value: "custom", label: "Custom" },
];
const GROUPS: { value: GroupKey; label: string }[] = [
  { value: "none", label: "Each record" },
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];
const AGGS: { value: AggKey; label: string }[] = [
  { value: "mean", label: "Mean" },
  { value: "min", label: "Min" },
  { value: "max", label: "Max" },
  { value: "sum", label: "Sum" },
  { value: "count", label: "Count" },
  { value: "latest", label: "Latest" },
];

/** Any metrics of any module over time, grouped, aggregated and filtered (06-ui Explore,
 * D-095); the page's URL holds the view. */
export function Explore() {
  const [params, setParams] = useSearchParams();
  const state = readState(params);
  const today = dayjs().format("YYYY-MM-DD");
  const catalogue = useMetrics();

  function update(change: Partial<ExploreState>) {
    setParams(writeState({ ...state, ...change }));
  }

  const metrics = catalogue.data?.metrics ?? [];
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const picked = state.metrics.map((id) => byId.get(id)).filter((m): m is MetricInfo => !!m);
  const entities = new Set(picked.map((m) => `${m.module}.${m.entity}`));
  // one point per record needs metrics of one entity: by day otherwise (the URL may ask)
  const oneEntity = entities.size <= 1;
  const group = state.group === "none" && !oneEntity ? "day" : state.group;
  const names = metricNames(metrics);
  const result = useMetricQuery(metricQuery({ ...state, group }, today));
  const filters = (catalogue.data?.filters ?? []).filter((f) =>
    entities.has(`${f.module}.${f.entity}`),
  );
  // the React compiler memoizes this (D-070's lint): no useMemo by hand
  // the chart names the picked metrics apart from each other only ("Sleep hours", not
  // "Sleep hours · Wellbeing · before" when no other sleep hours is picked)
  const shown = metricNames(picked);
  const option = result.data ? exploreOption(result.data, metrics, state.chart, shown) : null;

  const groups = new Map<string, { value: string; label: string; disabled: boolean }[]>();
  for (const m of metrics) {
    const items = groups.get(metricGroup(m)) ?? [];
    items.push({
      value: m.id,
      label: names.get(m.id) ?? m.label,
      disabled: !state.metrics.includes(m.id) && !fits(m, picked),
    });
    groups.set(metricGroup(m), items);
  }

  return (
    <Stack>
      <Title order={2}>Explore</Title>
      {catalogue.isPending && <Loader />}
      {catalogue.error && <Alert color="red">{catalogue.error.message}</Alert>}
      {catalogue.data && metrics.length === 0 && (
        <Text>No module with numbers to explore: add one to the app config.</Text>
      )}
      {metrics.length > 0 && (
        <Card withBorder>
          <Stack gap="sm">
            <MultiSelect
              label="Metrics"
              description="Up to two units at once (each gets its own axis)."
              placeholder="Pick one or more"
              searchable
              data={[...groups].map(([group, items]) => ({ group, items }))}
              value={state.metrics}
              onChange={(value) => {
                const kept = Object.fromEntries(
                  Object.entries(state.filters).filter(([id]) =>
                    value.some((m) => m.startsWith(id.slice(0, id.lastIndexOf(".") + 1))),
                  ),
                );
                update({ metrics: value, filters: kept });
              }}
            />
            <Group align="end">
              <SegmentedControl
                aria-label="Range"
                data={RANGES}
                value={state.range}
                onChange={(value) => {
                  update({ range: value });
                }}
              />
              {state.range === "custom" && (
                <>
                  <DateInput
                    label="From"
                    valueFormat="DD/MM/YYYY"
                    value={state.start}
                    onChange={(value) => {
                      update({ start: value });
                    }}
                  />
                  <DateInput
                    label="To"
                    valueFormat="DD/MM/YYYY"
                    value={state.end}
                    onChange={(value) => {
                      update({ end: value });
                    }}
                  />
                </>
              )}
            </Group>
            <Group align="end">
              <Select
                label="Points"
                data={GROUPS.map((g) => ({ ...g, disabled: g.value === "none" && !oneEntity }))}
                description={oneEntity ? undefined : "Each record: metrics of one entity only"}
                allowDeselect={false}
                value={group}
                onChange={(value) => {
                  update({ group: value ?? "day" });
                }}
              />
              <Select
                label="Aggregate"
                data={AGGS}
                allowDeselect={false}
                disabled={group === "none"}
                value={state.agg}
                onChange={(value) => {
                  update({ agg: value ?? "mean" });
                }}
              />
              <Switch
                label="Rolling mean"
                checked={state.rolling !== null}
                onChange={(event) => {
                  update({ rolling: event.currentTarget.checked ? 4 : null });
                }}
              />
              {state.rolling !== null && (
                <NumberInput
                  aria-label="Rolling mean of"
                  w={80}
                  min={2}
                  max={60}
                  value={state.rolling}
                  onChange={(value) => {
                    const n = Number(value);
                    if (Number.isInteger(n) && n >= 2) update({ rolling: n });
                  }}
                />
              )}
              <SegmentedControl
                aria-label="Chart"
                data={[
                  { value: "line", label: "Line" },
                  { value: "bars", label: "Bars" },
                ]}
                value={state.chart}
                onChange={(value) => {
                  update({ chart: value });
                }}
              />
            </Group>
            {filters.length > 0 && (
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
                {filters.map((f) => (
                  <MultiSelect
                    key={f.id}
                    label={`Only ${f.label.toLowerCase()}`}
                    placeholder="All"
                    clearable
                    data={f.choices}
                    value={state.filters[f.id] ?? []}
                    onChange={(value) => {
                      const next = Object.fromEntries(
                        Object.entries(state.filters).filter(([id]) => id !== f.id),
                      );
                      update({ filters: value.length > 0 ? { ...next, [f.id]: value } : next });
                    }}
                  />
                ))}
              </SimpleGrid>
            )}
          </Stack>
        </Card>
      )}
      {state.metrics.length === 0 && metrics.length > 0 && (
        <Text c="dimmed">Pick a metric to see it over time.</Text>
      )}
      {result.isFetching && !result.data && <Loader />}
      {result.error && <Alert color="red">{result.error.message}</Alert>}
      {result.data && option && (
        <Card withBorder>
          {result.data.points.length === 0 ? (
            <Text c="dimmed">Nothing logged in this range.</Text>
          ) : (
            <Stack gap="xs">
              <Chart option={option} label="Explore chart" height={380} />
              <Text size="xs" c="dimmed">
                {result.data.series
                  .map((s) => {
                    const n = s.n.reduce((a, b) => a + b, 0);
                    return `${shown.get(s.metric) ?? s.metric}: n = ${String(n)}`;
                  })
                  .join(" · ")}
              </Text>
            </Stack>
          )}
        </Card>
      )}
    </Stack>
  );
}
