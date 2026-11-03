// SPDX-License-Identifier: GPL-3.0-or-later
import {
  Alert,
  Group,
  Loader,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import dayjs from "dayjs";
import { useSearchParams } from "react-router";

import { viewNames, type ModuleInfo, type View } from "../api/client";
import { useView } from "../api/queries";
import { DataStatus } from "../components/DataStatus";
import {
  BarsCard,
  BodyHeatmapCard,
  BoxByCard,
  PrePostCard,
  ScatterCard,
  StackedCard,
  TrainingLoadCard,
  WeekbarsCard,
} from "../components/ChartWidgets";
import {
  HeatmapCard,
  KpiCard,
  LineCard,
  MonthlyCard,
  PlannedCard,
  SideBySideCard,
  StatusBoard,
  TableCard,
  TextFeedCard,
} from "../components/Widgets";
import { WithModule } from "../components/WithModule";

/** A module's dashboard (06-ui Dashboards, D-083): its view's widgets, computed in the backend
 * for a day (today by default; `?date=` and `?view=` in the URL). */
export function Dashboards() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? dayjs().format("YYYY-MM-DD");
  return (
    <Stack>
      <Group justify="space-between" align="end">
        <Title order={2}>Dashboards</Title>
        <DateInput
          label="As of"
          valueFormat="DD/MM/YYYY"
          value={date}
          onChange={(value) => {
            if (value !== null) {
              setParams((p) => {
                p.set("date", value);
                return p;
              });
            }
          }}
        />
      </Group>
      <WithModule base="/dashboards">
        {({ module }) => <ModuleViews module={module} date={date} />}
      </WithModule>
    </Stack>
  );
}

function ModuleViews({ module, date }: { module: ModuleInfo; date: string }) {
  const [params, setParams] = useSearchParams();
  const names = viewNames(module);
  if (names.length === 0) return <Text>Module '{module.id}' has no views.</Text>;
  const asked = params.get("view");
  const view = asked !== null && names.includes(asked) ? asked : (names[0] ?? "");
  return (
    <Stack>
      {names.length > 1 && (
        <SegmentedControl
          aria-label="View"
          data={names}
          value={view}
          onChange={(value) => {
            setParams((p) => {
              p.set("view", value);
              return p;
            });
          }}
        />
      )}
      <ViewWidgets module={module.id} view={view} date={date} />
    </Stack>
  );
}

function ViewWidgets({ module, view, date }: { module: string; view: string; date: string }) {
  const query = useView(module, view, date);
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't compute the dashboard">
        {query.error.message}
      </Alert>
    );
  }
  return <Widgets view={query.data} />;
}

function Widgets({ view }: { view: View }) {
  const kpis = view.widgets.filter((w) => w.widget === "kpi");
  return (
    <Stack>
      <DataStatus records={view} />
      {kpis.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: Math.min(kpis.length, 4) }}>
          {kpis.map((w, i) => (
            <KpiCard key={i} data={w} />
          ))}
        </SimpleGrid>
      )}
      {view.widgets.map((w, i) => {
        switch (w.widget) {
          case "status_board":
            return <StatusBoard key={i} data={w} />;
          case "line":
            return <LineCard key={i} data={w} today={view.date} />;
          case "heatmap_calendar":
            return <HeatmapCard key={i} data={w} />;
          case "side_by_side":
            return <SideBySideCard key={i} data={w} />;
          case "text_feed":
            return <TextFeedCard key={i} data={w} />;
          case "table":
            return <TableCard key={i} data={w} />;
          case "monthly":
            return <MonthlyCard key={i} data={w} />;
          case "bars":
            return <BarsCard key={i} data={w} />;
          case "weekbars":
            return <WeekbarsCard key={i} data={w} />;
          case "stacked":
            return <StackedCard key={i} data={w} />;
          case "box_by":
            return <BoxByCard key={i} data={w} />;
          case "scatter":
            return <ScatterCard key={i} data={w} />;
          case "training_load":
            return <TrainingLoadCard key={i} data={w} />;
          case "pre_post":
            return <PrePostCard key={i} data={w} />;
          case "body_heatmap":
            return <BodyHeatmapCard key={i} data={w} />;
          case "planned":
            return <PlannedCard key={i} data={w} />;
          default:
            return null; // KPIs are drawn together above
        }
      })}
    </Stack>
  );
}
