// SPDX-License-Identifier: GPL-3.0-or-later
// TanStack Query hooks for the API (D-070): cached per key, refetched when the window
// regains focus, so entries typed on the phone show up when coming back to the app.

import { keepPreviousData, QueryClient, useQuery } from "@tanstack/react-query";

import {
  ApiError,
  getCorrelation,
  getHealth,
  getMetrics,
  getModules,
  getRecommendation,
  getRecord,
  getRecords,
  getToday,
  getView,
  hiddenFields,
  queryMetrics,
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

export function useRecords(module: string, entity: string, enabled = true) {
  return useQuery({
    queryKey: ["records", module, entity],
    queryFn: () => getRecords(module, entity),
    enabled,
  });
}

/** The fields a form hides for its values so far (`visible_if`); the last answer is kept while
 * the next is asked, so fields don't flicker as you type. */
export function useHidden(module: string, entity: string, values: Values, enabled: boolean) {
  return useQuery({
    queryKey: ["hidden", module, entity, values],
    queryFn: () => hiddenFields(module, entity, values),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** One record by its key (null: none yet). */
export function useRecord(module: string, entity: string, key: Values, enabled = true) {
  return useQuery({
    queryKey: ["record", module, entity, key],
    queryFn: () => getRecord(module, entity, key),
    enabled,
  });
}

export function useRecommendation(date: string) {
  return useQuery({ queryKey: ["recommendation", date], queryFn: () => getRecommendation(date) });
}

export function useToday(date: string) {
  return useQuery({ queryKey: ["today", date], queryFn: () => getToday(date) });
}

export function useView(module: string, view: string, date: string) {
  return useQuery({
    queryKey: ["view", module, view, date],
    queryFn: () => getView(module, view, date),
  });
}

export function useMetrics() {
  return useQuery({ queryKey: ["metrics"], queryFn: getMetrics });
}

/** A metric query; none while `query` is null (no metric picked yet). */
export function useMetricQuery(query: string | null) {
  return useQuery({
    queryKey: ["metric-query", query],
    queryFn: () => queryMetrics(query ?? ""),
    enabled: query !== null,
  });
}

/** A correlation; none while `query` is null (not enough picked yet). */
export function useCorrelation<T>(kind: "pair" | "matrix" | "predictors", query: string | null) {
  return useQuery({
    queryKey: ["correlation", kind, query],
    queryFn: () => getCorrelation<T>(kind, query ?? ""),
    enabled: query !== null,
  });
}
