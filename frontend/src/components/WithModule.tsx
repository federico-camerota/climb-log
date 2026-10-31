// SPDX-License-Identifier: GPL-3.0-or-later
import { Alert, Loader, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useParams } from "react-router";

import { entityNames, isLoaded, type ModuleInfo } from "../api/client";
import { useModules } from "../api/queries";
import { ModulePicker } from "./ModulePicker";

interface Chosen {
  modules: ModuleInfo[];
  module: ModuleInfo;
  entity: string; // "" on pages not per entity
}

interface Props {
  base: string; // the page's path, e.g. "/records"
  perEntity?: boolean;
  children: (chosen: Chosen) => ReactNode;
}

/** The module (and entity) named in the URL, the first configured one when the URL has none
 * (D-073), with the picker above the page. */
export function WithModule({ base, perEntity = false, children }: Props) {
  const params = useParams();
  const query = useModules();
  if (query.isPending) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" title="Can't list the modules">
        {query.error.message}
      </Alert>
    );
  }
  const modules = query.data.modules.filter(isLoaded);
  const first = modules[0];
  if (first === undefined) {
    return (
      <Text>
        No module is ready: add one to the app config, or see Settings for what&apos;s wrong.
      </Text>
    );
  }
  if (params.module === undefined) {
    const entity = perEntity ? entityNames(first)[0] : undefined;
    return (
      <Navigate replace to={entity ? `${base}/${first.id}/${entity}` : `${base}/${first.id}`} />
    );
  }
  const module = modules.find((m) => m.id === params.module);
  if (module === undefined) {
    return <Text>No module &apos;{params.module}&apos; is ready: see Settings.</Text>;
  }
  let entity = "";
  if (perEntity) {
    if (params.entity === undefined) {
      const firstEntity = entityNames(module)[0];
      return firstEntity === undefined ? (
        <Text>Module &apos;{module.id}&apos; has no entities.</Text>
      ) : (
        <Navigate replace to={`${base}/${module.id}/${firstEntity}`} />
      );
    }
    if (!entityNames(module).includes(params.entity)) {
      return (
        <Text>
          Module &apos;{module.id}&apos; has no entity &apos;{params.entity}&apos;.
        </Text>
      );
    }
    entity = params.entity;
  }
  return (
    <Stack>
      <ModulePicker
        modules={modules}
        base={base}
        module={module}
        entity={perEntity ? entity : undefined}
      />
      {children({ modules, module, entity })}
    </Stack>
  );
}
