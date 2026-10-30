// SPDX-License-Identifier: GPL-3.0-or-later
// Typed wrappers around the backend HTTP API (/api/...). The types are generated from the
// backend's OpenAPI schema into schema.ts (`make api-types`, D-073).

import type { components } from "./schema";

type Schemas = components["schemas"];
export type Health = Schemas["Health"];
export type ModuleList = Schemas["ModuleList"];
export type ModuleInfo = Schemas["ModuleInfo"];
export type Records = Schemas["Records"];
export type Issue = Schemas["Issue"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    path: string,
    readonly detail?: string,
  ) {
    super(detail ?? `GET ${path} failed with HTTP ${String(status)}`);
    this.name = "ApiError";
  }
}

/** The API's own message: FastAPI's `detail`, a string or `{message}`. */
async function detailOf(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      return String(detail.message);
    }
  } catch {
    // not JSON: keep the generic message
  }
  return undefined;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(response.status, path, await detailOf(response));
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export function getModules(): Promise<ModuleList> {
  return getJson<ModuleList>("/api/modules");
}

export function getRecords(module: string, entity: string): Promise<Records> {
  const path = `/api/modules/${encodeURIComponent(module)}/${encodeURIComponent(entity)}`;
  return getJson<Records>(path);
}

/** The entities of a module, in YAML order (from its schema; none if it didn't load). */
export function entityNames(module: ModuleInfo): string[] {
  const entities = module.module_schema?.entities;
  return typeof entities === "object" && entities !== null ? Object.keys(entities) : [];
}
