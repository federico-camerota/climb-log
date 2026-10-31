// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Anchor, Badge, Card, Group, List, Loader, Stack, Text, Title } from "@mantine/core";
import { DateInput } from "@mantine/dates";
import dayjs from "dayjs";
import { Link, useSearchParams } from "react-router";

import type { DueForm, ModuleAdvice, ModuleDay } from "../api/client";
import { useRecommendation, useToday } from "../api/queries";
import { asText } from "../forms/values";
import { formatDateTime } from "../lib/format";

const HEADLINE_COLOURS: Record<string, string> = {
  RECOVER: "red",
  MODERATE: "yellow",
  "GREEN LIGHT": "green",
};
const STATUS_COLOURS: Record<string, string> = {
  done: "green",
  partial: "yellow",
  missing: "gray",
};

/** The home page (06-ui Today): what to log on a day, what is missing, and the next-session
 * recommendation. The day is in the URL (`/?date=2026-10-30`), today by default. */
export function Today() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? dayjs().format("YYYY-MM-DD");
  return (
    <Stack>
      <Group justify="space-between" align="end">
        <Title order={2}>Today</Title>
        <DateInput
          label="Day"
          valueFormat="DD/MM/YYYY"
          value={date}
          onChange={(value) => {
            if (value !== null) setParams({ date: value }, { replace: true });
          }}
        />
      </Group>
      <Advice date={date} />
      <DueLists date={date} />
    </Stack>
  );
}

function Advice({ date }: { date: string }) {
  const query = useRecommendation(date);
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't compute the recommendation">
        {query.error.message}
      </Alert>
    );
  }
  return (
    <>
      {query.data.items.map((item) => (
        <AdviceCard key={item.module} item={item} />
      ))}
    </>
  );
}

function AdviceCard({ item }: { item: ModuleAdvice }) {
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Text fw={500}>{item.label}</Text>
        <Group gap="xs" wrap="nowrap" align="start">
          {item.headline !== null && (
            <Badge size="lg" color={HEADLINE_COLOURS[item.headline] ?? "gray"}>
              {item.headline}
            </Badge>
          )}
          <Text>{item.message ?? "No rule applies."}</Text>
        </Group>
        {item.reasons.length > 0 && (
          <List size="sm" c="dimmed">
            {item.reasons.map((reason) => (
              <List.Item key={reason.name}>
                {reason.label}: {shown(reason.value)}
              </List.Item>
            ))}
          </List>
        )}
      </Stack>
    </Card>
  );
}

function DueLists({ date }: { date: string }) {
  const query = useToday(date);
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't read the day">
        {query.error.message}
      </Alert>
    );
  }
  const { modules, problems } = query.data;
  return (
    <>
      {problems.map((problem) => (
        <Alert key={problem} color="orange" title="Can't read a module">
          {problem}
        </Alert>
      ))}
      {modules.length === 0 && problems.length === 0 && <Text>No module has forms to fill.</Text>}
      {modules.map((day) => (
        <DueList key={day.module} day={day} date={date} />
      ))}
    </>
  );
}

function DueList({ day, date }: { day: ModuleDay; date: string }) {
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={500}>{day.name}</Text>
          {day.last !== null && (
            <Text size="sm" c="dimmed">
              Last {(day.last_label ?? "record").toLowerCase()}: {formatDateTime(day.last)} ·{" "}
              {ago(day.days_since)}
            </Text>
          )}
        </Group>
        {day.any_one && <Text size="sm">Nothing logged yet: one of these.</Text>}
        {day.items.map((item) => (
          <DueItem
            key={`${item.form}:${JSON.stringify(item.key)}`}
            module={day.module}
            item={item}
            date={date}
          />
        ))}
        {day.notes.map((note) => (
          <Text key={note} size="sm" c="dimmed">
            {note}
          </Text>
        ))}
        {day.offline && (
          <Text size="sm" c="orange">
            Offline: the last snapshot, read-only.
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function DueItem({ module, item, date }: { module: string; item: DueForm; date: string }) {
  const search = new URLSearchParams({ date });
  for (const [name, value] of Object.entries(item.key)) {
    if (value !== null) search.set(name, asText(value));
  }
  const number = item.key.session_no;
  const action = { done: "Open", partial: "Complete", missing: "Fill in" }[item.status] ?? "Open";
  return (
    <Group justify="space-between" wrap="nowrap" align="start">
      <Stack gap={2}>
        <Group gap="xs">
          <Text>
            {item.label}
            {typeof number === "number" && number > 1 ? ` · session ${String(number)}` : ""}
          </Text>
          <Badge variant="light" color={STATUS_COLOURS[item.status] ?? "gray"}>
            {item.status}
          </Badge>
        </Group>
        {item.status === "partial" && item.missing.length > 0 && (
          <Text size="sm" c="dimmed">
            Missing: {item.missing.join(", ")}
          </Text>
        )}
        {item.log_check !== null && item.log_check !== undefined && (
          <Text size="sm" c="dimmed">
            Log check: {asText(item.log_check)}
          </Text>
        )}
      </Stack>
      <Anchor component={Link} to={`/log/${module}/${item.form}?${search.toString()}`}>
        {action}
      </Anchor>
    </Group>
  );
}

function ago(days: number | null): string {
  if (days === null) return "";
  if (days === 0) return "today";
  return days === 1 ? "yesterday" : `${String(days)} days ago`;
}

/** A reason's value as the app shows it: dates day first, blanks as a dash. */
function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "string" ? formatDateTime(value) : asText(value);
}
