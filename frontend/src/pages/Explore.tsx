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
  Stack,
  Switch,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import { useSearchParams } from "react-router";

import type { MetricInfo } from "../api/client";
import { useMetricQuery, useMetrics } from "../api/queries";
import { Chart } from "../components/Chart";
import { FilterPickers, RangePicker } from "../components/ScopeControls";
import {
  readCorrelation,
  writeCorrelation,
  type CorrelationState,
  type Tab,
} from "../lib/correlation";
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
} from "../lib/explore";
import { MatrixPanel, PairPanel, PredictorsPanel } from "./ExploreCorrelation";

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

  const correlation = readCorrelation(params);

  function update(change: Partial<ExploreState>) {
    setParams(writeCorrelation(writeState({ ...state, ...change }), correlation));
  }

  function updateCorrelation(change: Partial<CorrelationState>) {
    setParams(writeCorrelation(params, { ...correlation, ...change }));
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
  // built on each render (no memo): the page renders again only when its URL or data change,
  // and the option is a few hundred points
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

  // a good session is a high feel score by default (D-096)
  const feel = metrics.find((m) => m.field === "feel_score");
  const withTarget = { ...correlation, target: correlation.target ?? feel?.id ?? null };

  return (
    <Stack>
      <Title order={2}>Explore</Title>
      {catalogue.isPending && <Loader />}
      {catalogue.error && <Alert color="red">{catalogue.error.message}</Alert>}
      {catalogue.data && metrics.length === 0 && (
        <Text>No module with numbers to explore: add one to the app config.</Text>
      )}
      {metrics.length > 0 && (
        <Tabs
          keepMounted={false}
          value={correlation.tab}
          onChange={(value) => {
            updateCorrelation({ tab: (value ?? "trends") as Tab });
          }}
        >
          <Tabs.List>
            <Tabs.Tab value="trends">Over time</Tabs.Tab>
            <Tabs.Tab value="pair">Two metrics</Tabs.Tab>
            <Tabs.Tab value="matrix">Matrix</Tabs.Tab>
            <Tabs.Tab value="predictors">What goes with a good session</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="trends" pt="md">
            <Stack>
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
                    <RangePicker scope={state} onChange={update} />
                    <Group align="end">
                      <Select
                        label="Points"
                        data={GROUPS.map((g) => ({
                          ...g,
                          disabled: g.value === "none" && !oneEntity,
                        }))}
                        description={
                          oneEntity ? undefined : "Each record: metrics of one entity only"
                        }
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
                    <FilterPickers scope={state} filters={filters} onChange={update} />
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
          </Tabs.Panel>
          {(["pair", "matrix", "predictors"] as const).map((tab) => {
            const Panel = { pair: PairPanel, matrix: MatrixPanel, predictors: PredictorsPanel }[
              tab
            ];
            return (
              <Tabs.Panel key={tab} value={tab} pt="md">
                <Panel
                  state={withTarget}
                  metrics={metrics}
                  filters={catalogue.data?.filters ?? []}
                  today={today}
                  update={updateCorrelation}
                />
              </Tabs.Panel>
            );
          })}
        </Tabs>
      )}
    </Stack>
  );
}
