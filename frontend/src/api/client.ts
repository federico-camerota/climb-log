// SPDX-License-Identifier: GPL-3.0-or-later
// Typed wrappers around the backend HTTP API (/api/...).

/** Mirrors `Health` in backend/climblog/api/health.py. */
export interface Health {
  status: string;
  version: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    path: string,
  ) {
    super(`GET ${path} failed with HTTP ${String(status)}`);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(response.status, path);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}
