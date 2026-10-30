// SPDX-License-Identifier: GPL-3.0-or-later
import { Group, Select } from "@mantine/core";
import { useNavigate } from "react-router";

import { entityNames, type ModuleInfo } from "../api/client";

interface Props {
  modules: ModuleInfo[]; // the modules that loaded
  base: string; // the page's path, e.g. "/records"
  module: ModuleInfo;
  entity?: string; // shown (and picked) only on pages per entity
}

/** Pick the module, and the entity where the page needs one; the choice is in the URL. */
export function ModulePicker({ modules, base, module, entity }: Props) {
  const navigate = useNavigate();
  const pick = (id: string | null) => {
    const next = modules.find((m) => m.id === id);
    if (next === undefined) return;
    const first = entityNames(next)[0];
    void navigate(
      entity === undefined || first === undefined
        ? `${base}/${next.id}`
        : `${base}/${next.id}/${first}`,
    );
  };
  return (
    <Group>
      <Select
        label="Module"
        data={modules.map((m) => ({ value: m.id, label: m.name ?? m.id }))}
        value={module.id}
        onChange={pick}
        allowDeselect={false}
      />
      {entity !== undefined && (
        <Select
          label="Entity"
          data={entityNames(module)}
          value={entity}
          onChange={(value) => {
            if (value !== null) void navigate(`${base}/${module.id}/${value}`);
          }}
          allowDeselect={false}
        />
      )}
    </Group>
  );
}
