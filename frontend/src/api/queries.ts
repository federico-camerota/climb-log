// SPDX-License-Identifier: GPL-3.0-or-later
// TanStack Query hooks for the API (D-070): cached per key, refetched when the window
// regains focus, so entries typed on the phone show up when coming back to the app.

import { QueryClient, useQuery } from "@tanstack/react-query";

import {
  ApiError,
  getHealth,
  getModules,
  getRecommendation,
  getRecord,
  getRecords,
  type Values,
} from "./client";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 4xx won't change by asking again; network errors and 5xx are retried twice.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status < 500) && failures < 2,
      },
    },
  });
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: getHealth });
}

export function useModules() {
  return useQuery({ queryKey: ["modules"], queryFn: getModules });
}

export function useRecords(module: string, entity: string) {
  return useQuery({
    queryKey: ["records", module, entity],
    queryFn: () => getRecords(module, entity),
  });
}

/** One record by its key (null: none yet). */
export function useRecord(module: string, entity: string, key: Values) {
  return useQuery({
    queryKey: ["record", module, entity, key],
    queryFn: () => getRecord(module, entity, key),
  });
}

export function useRecommendation(date: string) {
  return useQuery({ queryKey: ["recommendation", date], queryFn: () => getRecommendation(date) });
}
