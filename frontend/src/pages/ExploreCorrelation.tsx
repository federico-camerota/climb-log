// SPDX-License-Identifier: GPL-3.0-or-later
// The Explore page's correlation tabs (#103, D-096): a pair, a matrix, and what goes with a
// good session. Descriptive words only; every number with n and its 95% CI.
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
  Table,
  Text,
} from "@mantine/core";

import type { CorrelationPair, MatrixData, MetricInfo, PredictorsData } from "../api/client";
import { useCorrelation } from "../api/queries";
import { Chart } from "../components/Chart";
import {
  correlationQuery,
  matrixOption,
  pairOption,
  strength,
  withCi,
  type CorrelationState,
  type Method,
  type PairGroup,
} from "../lib/correlation";
import { metricGroup, metricNames } from "../lib/explore";

interface Props {
  state: CorrelationState;
  metrics: MetricInfo[];
  window: URLSearchParams; // the date range's start/end and the filters
  update: (change: Partial<CorrelationState>) => void;
}

/** The metrics of a picker, labels told apart where they repeat ("Mood · Rest day"). */
function pickerData(metrics: MetricInfo[]) {
  const names = metricNames(metrics);
  const groups = new Map<string, { value: string; label: string }[]>();
  for (const m of metrics) {
    const items = groups.get(metricGroup(m)) ?? [];
    items.push({ value: m.id, label: names.get(m.id) ?? m.label });
    groups.set(metricGroup(m), items);
  }
  return [...groups].map(([group, items]) => ({ group, items }));
}

const CHANCE =
  "Associations, not causes. With many metrics some show up by chance: read a small n or a wide interval with care.";

function MethodPicker({ value, onChange }: { value: Method; onChange: (m: Method) => void }) {
  return (
    <SegmentedControl
      aria-label="Method"
      size="xs"
      data={[
        { value: "spearman", label: "Spearman (ranks)" },
        { value: "pearson", label: "Pearson (linear)" },
      ]}
      value={value}
      onChange={(v) => {
        onChange(v);
      }}
    />
  );
}

const POINTS: { value: PairGroup; label: string }[] = [
  { value: "auto", label: "Auto (each record or day)" },
  { value: "none", label: "Each record" },
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

export function PairPanel({ state, metrics, window, update }: Props) {
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const entityOf = (id: string | null) => (id ? id.slice(0, id.lastIndexOf(".")) : null);
  // one point per record needs X and Y of one entity and no lag: auto otherwise
  const perRecord = entityOf(state.x) === entityOf(state.y) && state.lag === 0;
  const group = state.group === "none" && !perRecord ? "auto" : state.group;
  const query = useCorrelation<CorrelationPair>(
    "pair",
    correlationQuery({ ...state, group }, window),
  );
  const data = query.data;
  const picked = [state.x, state.y]
    .map((id) => (id ? byId.get(id) : undefined))
    .filter((m): m is MetricInfo => m !== undefined);
  const names = metricNames(picked);
  return (
    <Stack>
      <Group align="end">
        <Select
          label="X"
          searchable
          data={pickerData(metrics)}
          value={state.x}
          onChange={(value) => {
            update({ x: value });
          }}
        />
        <Select
          label="Y"
          searchable
          data={pickerData(metrics)}
          value={state.y}
          onChange={(value) => {
            update({ y: value });
          }}
        />
        <NumberInput
          label="Y read days later"
          w={150}
          min={-31}
          max={31}
          value={state.lag}
          onChange={(value) => {
            const n = Number(value);
            if (Number.isInteger(n)) update({ lag: n });
          }}
        />
        <Select
          label="Points"
          w={210}
          allowDeselect={false}
          data={POINTS.map((p) => ({ ...p, disabled: p.value === "none" && !perRecord }))}
          value={group}
          onChange={(value) => {
            update({ group: value ?? "auto" });
          }}
        />
      </Group>
      {(!state.x || !state.y) && (
        <Text c="dimmed">Pick X and Y, e.g. sleep hours and feel score.</Text>
      )}
      {query.isFetching && !data && <Loader />}
      {query.error && <Alert color="red">{query.error.message}</Alert>}
      {data && (
        <Card withBorder style={{ opacity: data.too_few ? 0.6 : 1 }}>
          <Stack gap="xs">
            {data.too_few && (
              <Alert color="yellow">
                Only {data.n} point(s): under {data.min_n}, so this is too early to read.
              </Alert>
            )}
            <Chart option={pairOption(data, names)} label="Pair chart" />
            <Table>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Td>Spearman (ranks)</Table.Td>
                  <Table.Td>{withCi(data.spearman)}</Table.Td>
                  <Table.Td>{strength(data.spearman)}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>Pearson (linear)</Table.Td>
                  <Table.Td>{withCi(data.pearson)}</Table.Td>
                  <Table.Td>{strength(data.pearson)}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Td>n</Table.Td>
                  <Table.Td>{data.n}</Table.Td>
                  <Table.Td>
                    {[
                      {
                        auto: "each record or day",
                        none: "each record",
                        day: "per day",
                        week: "per week (means)",
                        month: "per month (means)",
                      }[group],
                      data.lag === 0 ? null : `Y ${String(data.lag)} day(s) later`,
                    ]
                      .filter((x) => x)
                      .join(", ")}
                  </Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
            <Text size="xs" c="dimmed">
              r from −1 to 1 with its 95% interval. {CHANCE}
            </Text>
          </Stack>
        </Card>
      )}
    </Stack>
  );
}

export function MatrixPanel({ state, metrics, window, update }: Props) {
  const query = useCorrelation<MatrixData>("matrix", correlationQuery(state, window));
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const data = query.data;
  const matrixNames = metricNames(
    state.matrix.map((id) => byId.get(id)).filter((m): m is MetricInfo => m !== undefined),
  );
  return (
    <Stack>
      <Group align="end">
        <MultiSelect
          label="Metrics (2 to 12)"
          placeholder="Pick two or more"
          searchable
          maxValues={12}
          style={{ flex: 1 }}
          data={pickerData(metrics)}
          value={state.matrix}
          onChange={(value) => {
            update({ matrix: value });
          }}
        />
        <MethodPicker
          value={state.method}
          onChange={(method) => {
            update({ method });
          }}
        />
      </Group>
      {query.isFetching && !data && <Loader />}
      {query.error && <Alert color="red">{query.error.message}</Alert>}
      {data && (
        <Card withBorder>
          <Chart
            option={matrixOption(
              data,
              data.metrics.map((m) => matrixNames.get(m) ?? m),
            )}
            label="Correlation matrix"
            height={Math.max(260, 48 * data.metrics.length + 140)}
          />
          <Text size="xs" c="dimmed">
            Each cell over the days both were logged; empty under n = {data.min_n}. {CHANCE}
          </Text>
        </Card>
      )}
    </Stack>
  );
}

export function PredictorsPanel({ state, metrics, window, update }: Props) {
  const query = useCorrelation<PredictorsData>("predictors", correlationQuery(state, window));
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const data = query.data;
  const listed = metricNames(
    (data?.predictors ?? [])
      .map((p) => byId.get(p.metric))
      .filter((m): m is MetricInfo => m !== undefined),
  );
  return (
    <Stack>
      <Group align="end">
        <Select
          label="A good session is a high"
          searchable
          data={pickerData(metrics)}
          value={state.target}
          onChange={(value) => {
            update({ target: value });
          }}
        />
        <MethodPicker
          value={state.method}
          onChange={(method) => {
            update({ method });
          }}
        />
      </Group>
      {query.isFetching && !data && <Loader />}
      {query.error && <Alert color="red">{query.error.message}</Alert>}
      {data && (
        <Card withBorder>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Known before the session</Table.Th>
                <Table.Th>r (95% interval)</Table.Th>
                <Table.Th>n</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.predictors.map((p) => (
                <Table.Tr key={p.metric} style={{ opacity: p.too_few ? 0.5 : 1 }}>
                  <Table.Td>
                    {listed.get(p.metric) ?? p.metric}
                    {byId.get(p.metric)?.direction === "lower_better" && " ↓"}
                  </Table.Td>
                  <Table.Td>{withCi(p.stat)}</Table.Td>
                  <Table.Td>{p.n}</Table.Td>
                  <Table.Td>
                    {p.too_few ? `too few (under ${String(data.min_n)})` : strength(p.stat)}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Text size="xs" c="dimmed">
            Each metric asked before climbing (or computed from such answers) against the score,
            strongest first; usable before a session. ↓: lower is better (e.g. soreness), so a
            negative r there goes with less of it. {CHANCE}
          </Text>
        </Card>
      )}
    </Stack>
  );
}
