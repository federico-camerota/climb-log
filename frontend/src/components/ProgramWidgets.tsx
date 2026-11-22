// SPDX-License-Identifier: GPL-3.0-or-later
// A program's dashboard (D-117): the table by program week, the program grid and the retests
// before/after.
import { Badge, Card, ColorSwatch, Group, Table, Text, Title, Tooltip } from "@mantine/core";
import type { CSSProperties } from "react";

import type { BeforeAfterData, ProgramGridData, WeekTableData } from "../api/client";
import { formatDateTime } from "../lib/format";
import { decimal, percent, qualityColour, weekValue } from "../lib/programGrid";

const KEY_WIDTH = 160;

const stickyCell: CSSProperties = {
  position: "sticky",
  left: 0,
  zIndex: 1,
  background: "var(--mantine-color-body)",
  minWidth: KEY_WIDTH,
};

/** A row per program week of the latest run: its phase, and each column's value. */
export function WeekTableCard({ data }: { data: WeekTableData }) {
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {data.label ?? "By program week"}
      </Title>
      {data.run === null ? (
        <Text c="dimmed">No run has started yet: start one on the Program page.</Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={stickyCell}>Week</Table.Th>
                {data.columns.map((c) => (
                  <Table.Th key={c.label}>{c.label}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.weeks.map((w) => {
                const future = data.current !== null && w.week > data.current;
                return (
                  <Table.Tr
                    key={w.week}
                    c={future ? "dimmed" : undefined}
                    fw={w.week === data.current ? 600 : undefined}
                  >
                    <Table.Td style={stickyCell}>
                      <Group gap={4} wrap="nowrap">
                        <Text span inherit>
                          W{w.week}
                        </Text>
                        {w.light && (
                          <Badge size="xs" variant="light">
                            light
                          </Badge>
                        )}
                      </Group>
                      {w.phase !== null && (
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {w.phase}
                        </Text>
                      )}
                    </Table.Td>
                    {data.columns.map((c, i) => (
                      <Table.Td key={c.label}>{weekValue(c.agg, w.values[i])}</Table.Td>
                    ))}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Card>
  );
}

/** The plan's exercises × program weeks: each week's prescription, coloured by the worst
 * movement quality logged; the share logged per week and per exercise. */
export function ProgramGridCard({ data }: { data: ProgramGridData }) {
  const groups: (string | null)[] = [];
  data.rows.forEach((r) => {
    const g = r.group;
    if (!groups.includes(g)) groups.push(g);
  });
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {data.label ?? "Program"}
      </Title>
      {data.rows.length === 0 ? (
        <Text c="dimmed">The plan has no rows yet: add them on the Program page.</Text>
      ) : (
        <>
          <Table.ScrollContainer minWidth={720}>
            <Table withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th style={stickyCell}>Exercise</Table.Th>
                  {data.weeks.map((w) => (
                    <Table.Th
                      key={w.week}
                      style={{ textAlign: "center" }}
                      fw={w.week === data.current ? 700 : undefined}
                    >
                      W{w.week}
                      <Text size="xs" c="dimmed">
                        {percent(w.share)}
                      </Text>
                    </Table.Th>
                  ))}
                  <Table.Th>Weeks done</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {groups.map((g) => [
                  g !== null && (
                    <Table.Tr key={`group-${g}`}>
                      <Table.Td style={stickyCell} fw={600}>
                        {g}
                      </Table.Td>
                      <Table.Td colSpan={data.weeks.length + 1} />
                    </Table.Tr>
                  ),
                  ...data.rows
                    .filter((r) => r.group === g)
                    .map((r) => (
                      <Table.Tr key={r.key}>
                        <Table.Td style={stickyCell}>
                          <Text size="sm" lineClamp={1}>
                            {r.key}
                            {r.name != null && ` · ${r.name}`}
                          </Text>
                        </Table.Td>
                        {r.cells.map((cell, i) => {
                          const week = data.weeks[i]?.week ?? i + 1;
                          const colour =
                            cell.logged > 0 ? qualityColour(cell.quality, data.qualities) : null;
                          const missed =
                            cell.logged === 0 &&
                            !cell.skip &&
                            data.current !== null &&
                            week < data.current;
                          const tip = cell.skip
                            ? "Nothing prescribed"
                            : cell.logged > 0
                              ? `Logged ${String(cell.logged)}×${cell.quality ? ` · ${cell.quality}` : ""}`
                              : missed
                                ? "Not logged"
                                : "To do";
                          return (
                            <Tooltip key={i} label={tip}>
                              <Table.Td
                                ta="center"
                                c={cell.skip ? "dimmed" : missed ? "red" : undefined}
                                bg={colour ? `var(--mantine-color-${colour}-light)` : undefined}
                                style={{ whiteSpace: "nowrap" }}
                              >
                                {cell.prescribed == null
                                  ? "–"
                                  : String(cell.prescribed).replace(".", ",")}
                              </Table.Td>
                            </Tooltip>
                          );
                        })}
                        <Table.Td>{percent(r.share)}</Table.Td>
                      </Table.Tr>
                    )),
                ])}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group gap="md" mt="xs">
            {data.qualities.map((q) => (
              <Group key={q} gap={4}>
                <ColorSwatch
                  size={12}
                  color={`var(--mantine-color-${qualityColour(q, data.qualities)}-light)`}
                />
                <Text size="xs">{q}</Text>
              </Group>
            ))}
            <Text size="xs" c="red">
              red text: not logged
            </Text>
          </Group>
        </>
      )}
    </Card>
  );
}

function changeText(change: BeforeAfterData["rows"][number]["change"]): string {
  if (change == null) return "–";
  if (change.diff !== null) return `${change.diff > 0 ? "+" : ""}${decimal(change.diff, 1)}`;
  return `${change.first ?? "–"} → ${change.latest ?? "–"}`;
}

/** The retests: each measure at each checkpoint, and its change since the first. */
export function BeforeAfterCard({ data }: { data: BeforeAfterData }) {
  return (
    <Card withBorder>
      <Title order={4} mb="xs">
        {data.label ?? "Before and after"}
      </Title>
      {data.rows.length === 0 ? (
        <Text c="dimmed">No measures yet.</Text>
      ) : (
        <Table.ScrollContainer minWidth={560}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={stickyCell}>Measure</Table.Th>
                {data.checkpoints.map((c) => (
                  <Table.Th key={c}>{c}</Table.Th>
                ))}
                <Table.Th>Change</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.rows.map((r) => (
                <Table.Tr key={r.key}>
                  <Table.Td style={stickyCell}>{r.label}</Table.Td>
                  {r.cells.map((cell, i) => (
                    <Table.Td key={i}>
                      {cell == null ? (
                        <Text c="dimmed">–</Text>
                      ) : (
                        <>
                          {typeof cell.value === "number"
                            ? String(cell.value).replace(".", ",")
                            : cell.value}
                          <Text size="xs" c="dimmed">
                            {formatDateTime(cell.date)}
                          </Text>
                        </>
                      )}
                    </Table.Td>
                  ))}
                  <Table.Td
                    c={r.change?.better == null ? undefined : r.change.better ? "green" : "red"}
                  >
                    {changeText(r.change)}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Card>
  );
}
