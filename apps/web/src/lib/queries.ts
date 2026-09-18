"use client";

/**
 * TanStack Query v5 wrappers around the API client.
 *
 * Two deliberate choices:
 *  1. `queryFn` returns `ApiResult<T>` instead of throwing. Every screen therefore
 *     sees the same discriminated union it would get from a direct call, and the
 *     error/partial/empty branches stay explicit instead of hiding in `isError`.
 *     A transport failure is a *value*, not an exception, so `retry` is left off
 *     and the UI offers "Try again" (only when `error.retriable`).
 *  2. Query keys are built from a sorted, JSON-stable projection of the filters,
 *     so changing a filter always produces a new cache entry and never reuses
 *     another filter's page.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import * as api from "@/lib/api";
import type {
  Alert,
  AlertAcknowledgement,
  EventDetail,
  EventRecord,
  LedgerEntry,
  Market,
  ModelCard,
  Opportunity,
  Page,
  Prediction,
  Quote,
  ResolverDecision,
  ResolverReview,
  SourceHealth,
} from "@/lib/schemas";

/** Polling cadences. Every screen states the age it is showing, so these are slow. */
export const BOARD_REFRESH_MS = 30_000;
export const DETAIL_REFRESH_MS = 60_000;
export const HEALTH_REFRESH_MS = 60_000;
export const ALERTS_REFRESH_MS = 30_000;
export const LEDGER_REFRESH_MS = 120_000;
export const PREDICTIONS_REFRESH_MS = 120_000;

export interface HookOptions {
  enabled?: boolean;
}

function stableKey(parts: Record<string, unknown>): string {
  return JSON.stringify(parts, Object.keys(parts).sort());
}

export const queryKeys = {
  sourcesHealth: (params: api.SourceHealthQuery) => ["sources-health", stableKey({ ...params })] as const,
  events: (params: api.EventQuery) => ["events", stableKey({ ...params })] as const,
  event: (eventId: string) => ["event", eventId] as const,
  markets: (params: api.MarketQuery) => ["markets", stableKey({ ...params })] as const,
  latestQuotes: (params: api.LatestQuoteQuery) => ["latest-quotes", stableKey({ ...params })] as const,
  quoteHistory: (params: api.QuoteHistoryQuery) => ["quote-history", stableKey({ ...params })] as const,
  opportunities: (params: api.OpportunityQuery) =>
    ["opportunities", stableKey({ ...params })] as const,
  opportunity: (opportunityId: string) => ["opportunity", opportunityId] as const,
  resolverReview: (params: api.ResolverReviewQuery) =>
    ["resolver-review", stableKey({ ...params })] as const,
  predictions: (eventId: string, params: api.PredictionQuery) =>
    ["predictions", eventId, stableKey({ ...params })] as const,
  modelsMetrics: () => ["models-metrics"] as const,
  alerts: (params: api.AlertQuery) => ["alerts", stableKey({ ...params })] as const,
  ledger: (params: api.LedgerQuery) => ["paper-ledger", stableKey({ ...params })] as const,
} as const;

/* -------------------------------------------------------------------------- *
 * Reads
 * -------------------------------------------------------------------------- */

export function useSourcesHealth(
  params: api.SourceHealthQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<SourceHealth>>, Error> {
  return useQuery({
    queryKey: queryKeys.sourcesHealth(params),
    queryFn: ({ signal }) => api.getSourcesHealth(params, { signal }),
    staleTime: 15_000,
    refetchInterval: HEALTH_REFRESH_MS,
    enabled: options.enabled ?? true,
  });
}

export function useEvents(
  params: api.EventQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<EventRecord>>, Error> {
  return useQuery({
    queryKey: queryKeys.events(params),
    queryFn: ({ signal }) => api.getEvents(params, { signal }),
    staleTime: 30_000,
    enabled: options.enabled ?? true,
  });
}

export function useEvent(
  eventId: string | null,
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<EventDetail>, Error> {
  return useQuery({
    queryKey: queryKeys.event(eventId ?? ""),
    queryFn: ({ signal }) => api.getEvent(eventId ?? "", { signal }),
    staleTime: 30_000,
    refetchInterval: DETAIL_REFRESH_MS,
    enabled: (options.enabled ?? true) && eventId !== null && eventId !== "",
  });
}

export function useMarkets(
  params: api.MarketQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<Market>>, Error> {
  return useQuery({
    queryKey: queryKeys.markets(params),
    queryFn: ({ signal }) => api.getMarkets(params, { signal }),
    staleTime: 30_000,
    enabled: options.enabled ?? true,
  });
}

export function useLatestQuotes(
  params: api.LatestQuoteQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<Quote>>, Error> {
  return useQuery({
    queryKey: queryKeys.latestQuotes(params),
    queryFn: ({ signal }) => api.getLatestQuotes(params, { signal }),
    staleTime: 10_000,
    refetchInterval: DETAIL_REFRESH_MS,
    enabled: options.enabled ?? true,
  });
}

export function useQuoteHistory(
  params: api.QuoteHistoryQuery,
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<Quote>>, Error> {
  return useQuery({
    queryKey: queryKeys.quoteHistory(params),
    queryFn: ({ signal }) => api.getQuoteHistory(params, { signal }),
    staleTime: 30_000,
    enabled: (options.enabled ?? true) && params.marketId !== "",
  });
}

export function useOpportunities(
  params: api.OpportunityQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<Opportunity>>, Error> {
  return useQuery({
    queryKey: queryKeys.opportunities(params),
    queryFn: ({ signal }) => api.getOpportunities(params, { signal }),
    staleTime: 15_000,
    refetchInterval: BOARD_REFRESH_MS,
    enabled: options.enabled ?? true,
  });
}

export function useOpportunity(
  opportunityId: string | null,
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Opportunity>, Error> {
  return useQuery({
    queryKey: queryKeys.opportunity(opportunityId ?? ""),
    queryFn: ({ signal }) => api.getOpportunity(opportunityId ?? "", { signal }),
    staleTime: 15_000,
    refetchInterval: DETAIL_REFRESH_MS,
    enabled: (options.enabled ?? true) && opportunityId !== null && opportunityId !== "",
  });
}

export function useResolverReview(
  params: api.ResolverReviewQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<ResolverReview>>, Error> {
  return useQuery({
    queryKey: queryKeys.resolverReview(params),
    queryFn: ({ signal }) => api.getResolverReview(params, { signal }),
    staleTime: 15_000,
    refetchInterval: HEALTH_REFRESH_MS,
    enabled: options.enabled ?? true,
  });
}

export function usePredictions(
  eventId: string | null,
  params: api.PredictionQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<Prediction>>, Error> {
  return useQuery({
    queryKey: queryKeys.predictions(eventId ?? "", params),
    queryFn: ({ signal }) => api.getPredictions(eventId ?? "", params, { signal }),
    staleTime: 60_000,
    refetchInterval: PREDICTIONS_REFRESH_MS,
    enabled: (options.enabled ?? true) && eventId !== null && eventId !== "",
  });
}

export function useModelsMetrics(
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<api.ModelMetricsPage>, Error> {
  return useQuery({
    queryKey: queryKeys.modelsMetrics(),
    queryFn: ({ signal }) => api.getModelsMetrics({ signal }),
    staleTime: 60_000,
    enabled: options.enabled ?? true,
  });
}

export function useAlerts(
  params: api.AlertQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<Page<Alert>>, Error> {
  return useQuery({
    queryKey: queryKeys.alerts(params),
    queryFn: ({ signal }) => api.getAlerts(params, { signal }),
    staleTime: 10_000,
    refetchInterval: ALERTS_REFRESH_MS,
    enabled: options.enabled ?? true,
  });
}

export function usePaperLedger(
  params: api.LedgerQuery = {},
  options: HookOptions = {},
): UseQueryResult<api.ApiResult<api.LedgerPage>, Error> {
  return useQuery({
    queryKey: queryKeys.ledger(params),
    queryFn: ({ signal }) => api.getPaperLedger(params, { signal }),
    staleTime: 30_000,
    refetchInterval: LEDGER_REFRESH_MS,
    enabled: options.enabled ?? true,
  });
}

/* -------------------------------------------------------------------------- *
 * Analyst-only writes (same-origin proxies; disabled unless enabled server-side)
 * -------------------------------------------------------------------------- */

export interface AcknowledgeAlertVariables {
  alertId: string;
  acknowledgedBy?: string | null | undefined;
}

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();
  return useMutation<api.ApiResult<AlertAcknowledgement>, Error, AcknowledgeAlertVariables>({
    mutationFn: (variables) =>
      api.acknowledgeAlert(variables.alertId, {
        acknowledgedBy: variables.acknowledgedBy ?? null,
      }),
    onSuccess: (result) => {
      if (result.ok) {
        void queryClient.invalidateQueries({ queryKey: ["alerts"] });
      }
    },
  });
}

export interface ResolveReviewVariables {
  reviewId: string;
  action: api.ResolverDecisionAction;
  canonicalEventId?: string | null | undefined;
  note?: string | null | undefined;
}

export function useResolveReview() {
  const queryClient = useQueryClient();
  return useMutation<api.ApiResult<ResolverDecision>, Error, ResolveReviewVariables>({
    mutationFn: (variables) =>
      api.resolveReview(variables.reviewId, {
        action: variables.action,
        canonicalEventId: variables.canonicalEventId ?? null,
        note: variables.note ?? null,
      }),
    onSuccess: (result) => {
      if (result.ok) {
        void queryClient.invalidateQueries({ queryKey: ["resolver-review"] });
        void queryClient.invalidateQueries({ queryKey: ["events"] });
      }
    },
  });
}