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
export type Written = Schemas["Written"];
export type Recommendation = Schemas["Recommendation"];
export type ModuleAdvice = Schemas["ModuleAdvice"];
export type Today = Schemas["Today"];
export type ModuleDay = Schemas["ModuleDay"];
export type DueForm = Schemas["DueForm"];

/** A record's stored values (or its key's), by field name, as the API reads and writes them. */
export type Values = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    path: string,
    readonly detail?: string,
    readonly field?: string, // the field at fault (a write's 422)
    method = "GET",
  ) {
    super(detail ?? `${method} ${path} failed with HTTP ${String(status)}`);
    this.name = "ApiError";
  }
}

/** The API's own message: FastAPI's `detail`, a string or `{message, field}`. */
async function detailOf(response: Response): Promise<{ message?: string; field?: string }> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return { message: detail };
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      const field =
        "field" in detail && typeof detail.field === "string" ? detail.field : undefined;
      return { message: String(detail.message), field };
    }
  } catch {
    // not JSON: keep the generic message
  }
  return {};
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const { message, field } = await detailOf(response);
    throw new ApiError(response.status, path, message, field, method);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

function getJson<T>(path: string): Promise<T> {
  return send<T>("GET", path);
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}

export function getModules(): Promise<ModuleList> {
  return getJson<ModuleList>("/api/modules");
}

export function getRecords(module: string, entity: string): Promise<Records> {
  return getJson<Records>(entityPath(module, entity));
}

/** Whether the module's YAML loaded (it then has a schema; otherwise `problems` say why). */
export function isLoaded(module: ModuleInfo): boolean {
  return module.module_schema != null;
}

/** The entities of a module, in YAML order (from its schema; none if it didn't load). */
export function entityNames(module: ModuleInfo): string[] {
  const entities = module.module_schema?.entities;
  return typeof entities === "object" && entities !== null ? Object.keys(entities) : [];
}

function entityPath(module: string, entity: string): string {
  return `/api/modules/${encodeURIComponent(module)}/${encodeURIComponent(entity)}`;
}

/** `…/record?date=2026-10-30&session_no=2`: the key, one parameter per key field (D-075). */
function recordPath(module: string, entity: string, key: Values): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(key)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(name, typeof value === "string" ? value : JSON.stringify(value));
  }
  return `${entityPath(module, entity)}/record?${params.toString()}`;
}

/** One record by its key; null when there is none. */
export async function getRecord(
  module: string,
  entity: string,
  key: Values,
): Promise<Written | null> {
  try {
    return await getJson<Written>(recordPath(module, entity, key));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function addRecord(module: string, entity: string, values: Values): Promise<Written> {
  return send<Written>("POST", entityPath(module, entity), { values });
}

/** Change some fields; `expected` holds them as read, so a change since is a 409 (D-075). */
export function updateRecord(
  module: string,
  entity: string,
  key: Values,
  values: Values,
  expected: Values,
): Promise<Written> {
  return send<Written>("PATCH", recordPath(module, entity, key), { values, expected });
}

export function getRecommendation(date: string): Promise<Recommendation> {
  return getJson<Recommendation>(`/api/recommendation?date=${encodeURIComponent(date)}`);
}

export function getToday(date: string): Promise<Today> {
  return getJson<Today>(`/api/today?date=${encodeURIComponent(date)}`);
}
