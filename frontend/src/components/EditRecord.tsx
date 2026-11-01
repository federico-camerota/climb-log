// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Button, Drawer, Group, Modal, Stack, Text } from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { deleteRecord, type Issue, type ModuleInfo, type Values } from "../api/client";
import { RecordForm } from "../forms/RecordForm";
import { entityOf, fieldLabel, keyOf, type EntityDef } from "../forms/schema";
import { formatDateTime } from "../lib/format";

interface Props {
  module: ModuleInfo;
  entity: string;
  recordKey: Values | null; // null: closed
  issues: Issue[]; // the record's data issues, shown under their fields
  onClose: () => void;
}

/** A record of the Records page in a drawer (D-082): the whole record in one form (every
 * section, pre and post), saved through the write API, and soft deleted after a confirmation. */
export function EditRecord({ module, entity, recordKey, issues, onClose }: Props) {
  const def = entityOf(module, entity);
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteRecord(module.id, entity, recordKey ?? {}),
    onSuccess: () => {
      setConfirming(false);
      onClose();
      void queryClient.invalidateQueries({ queryKey: ["records", module.id, entity] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      void queryClient.invalidateQueries({ queryKey: ["recommendation"] });
    },
  });
  const title = def !== undefined && recordKey !== null ? describe(entity, def, recordKey) : "";
  return (
    <Drawer opened={recordKey !== null} onClose={onClose} position="right" size="xl" title={title}>
      {def !== undefined && recordKey !== null && (
        <Stack>
          <RecordForm
            key={JSON.stringify(recordKey)}
            module={module}
            formName="_edit"
            form={{ entity }}
            entity={def}
            recordKey={recordKey}
            issues={issues}
          />
          <Group justify="flex-end">
            <Button
              color="red"
              variant="light"
              onClick={() => {
                remove.reset();
                setConfirming(true);
              }}
            >
              Delete…
            </Button>
          </Group>
        </Stack>
      )}
      <Modal
        opened={confirming}
        onClose={() => {
          setConfirming(false);
        }}
        title={`Delete ${title}?`}
      >
        <Stack>
          <Text size="sm">
            The record disappears from the app. In the sheet its rows stay, marked in the{" "}
            <code>deleted</code> column: clearing that cell brings it back.
          </Text>
          {remove.isError && (
            <Alert color="red" title="Not deleted">
              {remove.error.message}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setConfirming(false);
              }}
            >
              Cancel
            </Button>
            <Button
              color="red"
              loading={remove.isPending}
              onClick={() => {
                remove.mutate();
              }}
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Drawer>
  );
}

/** "Session · 28/10/2026 · Session # 2". */
function describe(name: string, entity: EntityDef, key: Values): string {
  const parts = keyOf(entity).map((part) => {
    const value = key[part];
    const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
    if (part === (entity.date_field ?? "date")) return formatDateTime(text);
    const field = entity.fields[part];
    return field === undefined ? text : `${fieldLabel(part, field)} ${text}`;
  });
  return [entity.label ?? name, ...parts].join(" · ");
}
