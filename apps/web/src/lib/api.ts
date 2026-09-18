/**
 * Typed, read-only HTTP client for the Academic Edge FastAPI backend.
 *
 * DESIGN CONTRACT
 *  * Every function returns `ApiResult<T>` - a discriminated union - so no screen
 *    can accidentally treat an error as data. Network failures, timeouts, HTTP
 *    statuses and schema (contract) mismatches are all mapped into `ApiError`.
 *  * Every request is a GET against `NEXT_PUBLIC_API_BASE_URL`, except the two
 *    analyst actions (acknowledge an alert, decide a resolver review). Those POST
 *    to *same-origin Next.js Route Handlers* which hold the analyst key
 *    server-side: the browser never sees an analyst credential, and the app has
 *    no code path that could place a bet or store bookmaker credentials.
 *  * Cursor pagination is normalised to `Page<T>` (`items` + `next_cursor`) with
 *    the optional envelope metadata preserved (`fixture_mode`, `partial`, `stale`).
 *  * A bare JSON array body is accepted and wrapped; a single-entity response is
 *    accepted either bare or wrapped as `{ "item": {...} }`.
 */

import { z } from "zod";

import {
  alertAcknowledgementSchema,
  alertPageSchema,
  eventDetailSchema,
  eventPageSchema,
  ledgerEntryPageSchema,
  marketPageSchema,
  modelMetricsSchema,
  opportunityPageSchema,
  opportunitySchema,
  predictionPageSchema,
  quotePageSchema,
  resolverDecisionSchema,
  resolverReviewPageSchema,
  sourceHealthPageSchema,
  type Alert,
  type AlertAcknowledgement,
  type AlertSeverity,
  type AlertStatus,
  type EventDetail,
  type EventRecord,
  type LedgerEntry,
  type LedgerStatus,
  type LedgerSummary,
  type Market,
  type MarketType,
  type ModelCard,
  type Opportunity,
  type OpportunityType,
  type Page,
  type Prediction,
  type Quote,
  type ResolverDecision,
  type ResolverReview,
  type ReviewStatus,
  type SourceHealth,
} from "@/lib/schemas";

/* -------------------------------------------------------------------------- *
 * Configuration
 * -------------------------------------------------------------------------- */

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

/** Browser-visible API base URL. Inlined at build time by Next.js. */
export const API_BASE_URL = trimTrailingSlash(
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
);

/**
 * Optional low-privilege reader key for browser GETs. It is public by definition
 * (the `reader` role); analyst/admin keys live only on the server.
 */
export const API_READ_KEY = process.env.NEXT_PUBLIC_API_READ_KEY ?? "";

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw === "") {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/** How long without an SSE event before the stream is considered stale. */
export const SSE_STALE_AFTER_MS = parsePositiveInt(
  process.env.NEXT_PUBLIC_SSE_STALE_AFTER_MS,
  30_000,
);

const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_DETAIL_CHARS = 600;

/* -------------------------------------------------------------------------- *
 * Result types
 * -------------------------------------------------------------------------- */

export type ApiErrorKind = "network" | "timeout" | "http" | "contract" | "aborted" | "unknown";

export interface ApiError {
  kind: ApiErrorKind;
  /** HTTP status when a response was received, otherwise null. */
  status: number | null;
  /** Short, analyst-readable summary. */
  message: string;
  /** Raw upstream detail (truncated) - shown in the error block, never parsed. */
  detail: string | null;
  url: string;
  method: string;
  /** Whether a retry could plausibly succeed ("Try again" is only offered then). */
  retriable: boolean;
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

/** One-line explanation for an error block, including what an operator can do. */
export function describeApiError(error: ApiError): string {
  switch (error.kind) {
    case "network":
      return `The dashboard could not reach the API at ${API_BASE_URL}. Check that the API is running and that CORS allows this origin.`;
    case "timeout":
      return "The API did not answer within the client timeout. The backend may still be building this page.";
    case "aborted":
      return "The request was cancelled because the view changed or was unmounted.";
    case "contract":
      return "The API answered with a payload this client does not understand, so nothing is displayed rather than showing mismatched numbers.";
    case "http":
      if (error.status === 401) {
        return "The API rejected the request (401). Set NEXT_PUBLIC_API_READ_KEY to a valid reader key, or run the local no-auth profile.";
      }
      if (error.status === 403) {
        return "The API refused this request for the current role (403). This action needs the analyst role on the server side.";
      }
      if (error.status === 404) {
        return "The API has no record for this identifier (404).";
      }
      if (error.status === 422) {
        return "The API rejected the query parameters (422): this filter combination is not supported by this API revision.";
      }
      if (error.status !== null && error.status >= 500) {
        return "The API reported a server error. Reading is safe to retry; nothing was modified.";
      }
      return error.message;
    default:
      return error.message;
  }
}

/* -------------------------------------------------------------------------- *
 * Pagination envelope
 * -------------------------------------------------------------------------- */

/** Envelope fields the client understands (all optional except `items`). */
export interface PageEnvelope<TItem> {
  items: TItem[];
  next_cursor?: string | null | undefined;
  generated_at?: string | null | undefined;
  fixture_mode?: boolean | null | undefined;
  stale?: boolean | null | undefined;
  partial?: boolean | null | undefined;
  sources_failed?: string[] | null | undefined;
}

/** Normalises an envelope into the concrete `Page<T>` shape screens consume. */
export function toPage<TItem>(raw: PageEnvelope<TItem>): Page<TItem> {
  return {
    items: raw.items,
    next_cursor: raw.next_cursor ?? null,
    generated_at: raw.generated_at ?? null,
    fixture_mode: raw.fixture_mode ?? false,
    stale: raw.stale ?? false,
    partial: raw.partial ?? false,
    sources_failed: raw.sources_failed ?? [],
  };
}

/* -------------------------------------------------------------------------- *
 * Query parameters
 * -------------------------------------------------------------------------- */

export type QueryParamValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryParamValue>;

/** Cursor pagination shared by every list endpoint. */
export interface CursorQuery {
  cursor?: string | null | undefined;
  limit?: number | null | undefined;
}

export interface ClientOptions {
  signal?: AbortSignal | undefined;
  timeoutMs?: number | undefined;
}

function buildQueryString(params: QueryParams | undefined): string {
  if (params === undefined) {
    return "";
  }
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered === "" ? "" : `?${rendered}`;
}

interface RequestOptions extends ClientOptions {
  method?: "GET" | "POST";
  query?: QueryParams | undefined;
  body?: unknown;
  /** Absolute (or same-origin) URL that bypasses the API_BASE_URL join. */
  absoluteUrl?: string | undefined;
  headers?: Record<string, string> | undefined;
  /** Rewrites the decoded JSON body before schema validation. */
  prepare?: ((body: unknown) => unknown) | undefined;
}

function truncateDetail(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return null;
  }
  return trimmed.length > MAX_DETAIL_CHARS ? `${trimmed.slice(0, MAX_DETAIL_CHARS)}...` : trimmed;
}

function isAbortError(cause: unknown): boolean {
  if (typeof cause !== "object" || cause === null) {
    return false;
  }
  return (cause as { name?: unknown }).name === "AbortError";
}

function describeHttpStatus(status: number): string {
  if (status >= 500) {
    return `The API returned HTTP ${status} (server error).`;
  }
  if (status === 401) {
    return "The API returned HTTP 401 (authentication required).";
  }
  if (status === 403) {
    return "The API returned HTTP 403 (role not permitted).";
  }
  if (status === 404) {
    return "The API returned HTTP 404 (no record).";
  }
  if (status === 422) {
    return "The API returned HTTP 422 (unprocessable query).";
  }
  return `The API returned HTTP ${status}.`;
}

/** Wraps a bare JSON array body into the paginated envelope. */
function wrapArrayBody(body: unknown): unknown {
  if (Array.isArray(body)) {
    return { items: body };
  }
  return body;
}

/** Unwraps `{ "item": {...} }`; leaves anything else untouched. */
function unwrapItemBody(body: unknown): unknown {
  if (typeof body === "object" && body !== null && !Array.isArray(body) && "item" in body) {
    const wrapped = (body as { item: unknown }).item;
    return wrapped === undefined ? body : wrapped;
  }
  return body;
}

/** Renders the first schema issues so a contract mismatch is actionable. */
function contractDetail(issues: z.ZodIssue[]): string {
  return issues
    .slice(0, 6)
    .map((issue) => {
      const path = issue.path.length === 0 ? "(root)" : issue.path.join(".");
      return `${path}: ${issue.message}`;
    })
    .join("; ");
}

function requestHeaders(extra: Record<string, string> | undefined): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(extra ?? {}),
  };
  if (API_READ_KEY !== "" && headers["X-Api-Key"] === undefined) {
    headers["X-Api-Key"] = API_READ_KEY;
  }
  return headers;
}

/**
 * Single transport used by every function below: builds the URL, applies a
 * timeout, links any caller `AbortSignal`, then maps the outcome into
 * `ApiResult<T>`. It never throws - a screen always receives a value.
 */
async function execute<TOutput>(
  path: string,
  schema: z.ZodType<TOutput>,
  options: RequestOptions = {},
): Promise<ApiResult<TOutput>> {
  const method = options.method ?? "GET";
  const base = options.absoluteUrl ?? `${API_BASE_URL}${path}`;
  const url = `${base}${buildQueryString(options.query)}`;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  const controller = new AbortController();
  let timedOut = false;
  const linkedSignal = options.signal;
  const linkAbort = (): void => {
    controller.abort();
  };
  if (linkedSignal !== undefined) {
    if (linkedSignal.aborted) {
      controller.abort();
    } else {
      linkedSignal.addEventListener("abort", linkAbort);
    }
  }
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const fail = (
    kind: ApiErrorKind,
    message: string,
    detail: string | null,
    status: number | null,
    retriable: boolean,
  ): ApiResult<TOutput> => ({
    ok: false,
    error: { kind, status, message, detail, url, method, retriable },
  });

  try {
    const response = await fetch(url, {
      method,
      headers: requestHeaders(options.headers),
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      credentials: "omit",
      redirect: "follow",
      signal: controller.signal,
    });

    const rawText = await response.text();

    if (!response.ok) {
      const retriable =
        response.status >= 500 || response.status === 408 || response.status === 429;
      return fail(
        "http",
        describeHttpStatus(response.status),
        truncateDetail(rawText),
        response.status,
        retriable,
      );
    }

    let decoded: unknown;
    try {
      decoded = rawText.trim() === "" ? {} : JSON.parse(rawText);
    } catch (cause) {
      return fail(
        "contract",
        "The API returned a body that is not valid JSON.",
        cause instanceof Error ? cause.message : truncateDetail(rawText),
        response.status,
        false,
      );
    }

    const prepared = options.prepare === undefined ? decoded : options.prepare(decoded);
    const parsed = schema.safeParse(prepared);
    if (!parsed.success) {
      return fail(
        "contract",
        "The API payload did not match the schema this client was built against.",
        contractDetail(parsed.error.issues),
        response.status,
        false,
      );
    }
    return { ok: true, data: parsed.data };
  } catch (cause) {
    if (timedOut) {
      return fail("timeout", `The API did not answer within ${timeoutMs} ms.`, null, null, true);
    }
    if (isAbortError(cause)) {
      return fail("aborted", "The request was cancelled.", null, null, false);
    }
    return fail(
      "network",
      `The dashboard could not reach ${url}.`,
      cause instanceof Error ? cause.message : String(cause),
      null,
      true,
    );
  } finally {
    clearTimeout(timer);
    if (linkedSignal !== undefined) {
      linkedSignal.removeEventListener("abort", linkAbort);
    }
  }
}

/**
 * GET that returns a normalised cursor page. The schema validates the item shape;
 * `toPage` then removes the `| undefined` the envelope's `.nullish()` readers
 * allow, so screens always see an explicit `next_cursor: string | null`.
 */
async function getPage<TItem>(
  path: string,
  schema: z.ZodType<PageEnvelope<TItem>>,
  options: RequestOptions = {},
): Promise<ApiResult<Page<TItem>>> {
  const result = await execute(path, schema, { ...options, prepare: wrapArrayBody });
  if (!result.ok) {
    return result;
  }
  return { ok: true, data: toPage(result.data) };
}

/* ========================================================================== *
 * Endpoints - every one of these is a read-only GET
 * ========================================================================== */

/** GET /v1/sources/health */
export interface SourceHealthQuery extends CursorQuery {
  sourceId?: string | null | undefined;
}

export function getSourcesHealth(
  params: SourceHealthQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<SourceHealth>>> {
  return getPage("/v1/sources/health", sourceHealthPageSchema, {
    ...options,
    query: { cursor: params.cursor, limit: params.limit, source_id: params.sourceId },
  });
}

/** GET /v1/events */
export interface EventQuery extends CursorQuery {
  competitionId?: string | null | undefined;
  /** UTC ISO lower bound on start_time_utc. */
  from?: string | null | undefined;
  /** UTC ISO upper bound on start_time_utc. */
  to?: string | null | undefined;
  status?: string | null | undefined;
  search?: string | null | undefined;
  upcomingOnly?: boolean | null | undefined;
}

export function getEvents(
  params: EventQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<EventRecord>>> {
  return getPage("/v1/events", eventPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      competition_id: params.competitionId,
      from: params.from,
      to: params.to,
      status: params.status,
      q: params.search,
      upcoming_only: params.upcomingOnly,
    },
  });
}

/** GET /v1/events/{id} - detail incl. optional markets, source links, context. */
export function getEvent(
  eventId: string,
  options: ClientOptions = {},
): Promise<ApiResult<EventDetail>> {
  return execute(`/v1/events/${encodeURIComponent(eventId)}`, eventDetailSchema, {
    ...options,
    prepare: unwrapItemBody,
  });
}

/** GET /v1/markets */
export interface MarketQuery extends CursorQuery {
  eventId?: string | null | undefined;
  marketType?: MarketType | null | undefined;
  period?: string | null | undefined;
}

export function getMarkets(
  params: MarketQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<Market>>> {
  return getPage("/v1/markets", marketPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      event_id: params.eventId,
      market_type: params.marketType,
      period: params.period,
    },
  });
}

/** GET /v1/quotes/latest - newest observed price per outcome/venue. */
export interface LatestQuoteQuery extends CursorQuery {
  marketId?: string | null | undefined;
  eventId?: string | null | undefined;
  outcomeId?: string | null | undefined;
  sourceId?: string | null | undefined;
}

export function getLatestQuotes(
  params: LatestQuoteQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<Quote>>> {
  return getPage("/v1/quotes/latest", quotePageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      market_id: params.marketId,
      event_id: params.eventId,
      outcome_id: params.outcomeId,
      source_id: params.sourceId,
    },
  });
}

/**
 * GET /v1/quotes/latest?include_history=true - the odds timeline for one outcome.
 *
 * ASSUMPTION (documented in README): the brief's endpoint list has no dedicated
 * history route, so history is requested from the same endpoint. When the API
 * does not support the flag the detail screen shows the timeline as
 * "not available from this API revision" - it never fabricates a series.
 */
export interface QuoteHistoryQuery {
  marketId: string;
  outcomeId?: string | null | undefined;
  sourceId?: string | null | undefined;
  limit?: number | null | undefined;
}

export function getQuoteHistory(
  params: QuoteHistoryQuery,
  options: ClientOptions = {},
): Promise<ApiResult<Page<Quote>>> {
  return getPage("/v1/quotes/latest", quotePageSchema, {
    ...options,
    query: {
      market_id: params.marketId,
      outcome_id: params.outcomeId,
      source_id: params.sourceId,
      limit: params.limit ?? 200,
      include_history: true,
    },
  });
}

/** GET /v1/opportunities */
export interface OpportunityQuery extends CursorQuery {
  opportunityType?: OpportunityType | null | undefined;
  marketType?: MarketType | null | undefined;
  eventId?: string | null | undefined;
  marketId?: string | null | undefined;
  /** true = actionable only, false = blocked only, null/undefined = both. */
  actionable?: boolean | null | undefined;
  minNetEdgeBps?: number | null | undefined;
  detectedSince?: string | null | undefined;
  /** Server-side ordering, e.g. "net_edge_bps:desc". */
  sort?: string | null | undefined;
}

export function getOpportunities(
  params: OpportunityQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<Opportunity>>> {
  return getPage("/v1/opportunities", opportunityPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      opportunity_type: params.opportunityType,
      market_type: params.marketType,
      event_id: params.eventId,
      market_id: params.marketId,
      actionable: params.actionable,
      min_net_edge_bps: params.minNetEdgeBps,
      detected_since: params.detectedSince,
      sort: params.sort,
    },
  });
}

/** GET /v1/opportunities/{id} */
export function getOpportunity(
  opportunityId: string,
  options: ClientOptions = {},
): Promise<ApiResult<Opportunity>> {
  return execute(`/v1/opportunities/${encodeURIComponent(opportunityId)}`, opportunitySchema, {
    ...options,
    prepare: unwrapItemBody,
  });
}

/** GET /v1/resolver/review - the unresolved/settled match review queue. */
export interface ResolverReviewQuery extends CursorQuery {
  reviewStatus?: ReviewStatus | null | undefined;
  sourceId?: string | null | undefined;
  canonicalEventId?: string | null | undefined;
  minScore?: number | null | undefined;
  maxScore?: number | null | undefined;
}

export function getResolverReview(
  params: ResolverReviewQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<ResolverReview>>> {
  return getPage("/v1/resolver/review", resolverReviewPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      review_status: params.reviewStatus,
      source_id: params.sourceId,
      canonical_event_id: params.canonicalEventId,
      min_score: params.minScore,
      max_score: params.maxScore,
    },
  });
}

/** GET /v1/predictions/{event_id} */
export interface PredictionQuery extends CursorQuery {
  marketType?: MarketType | null | undefined;
  /** Include abstained predictions (default true server-side). */
  includeAbstained?: boolean | null | undefined;
}

export function getPredictions(
  eventId: string,
  params: PredictionQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<Prediction>>> {
  return getPage(`/v1/predictions/${encodeURIComponent(eventId)}`, predictionPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      market_type: params.marketType,
      include_abstained: params.includeAbstained,
    },
  });
}

/** Model-card page (`/v1/models/metrics`) plus the active model when reported. */
export interface ModelMetricsPage extends Page<ModelCard> {
  active_model: ModelCard | null;
}

/**
 * `/v1/models/metrics` is accepted in four shapes: a page (`items`), a bare array,
 * `{ models: [...] }`, or a single model card.
 */
function prepareModelMetricsBody(body: unknown): unknown {
  if (Array.isArray(body)) {
    return { items: body };
  }
  if (typeof body === "object" && body !== null) {
    const record = body as Record<string, unknown>;
    if (Array.isArray(record["items"])) {
      return body;
    }
    if (Array.isArray(record["models"])) {
      return { ...record, items: record["models"] };
    }
    if (typeof record["name"] === "string" && typeof record["version"] === "string") {
      return { items: [body], active_model: body };
    }
  }
  return body;
}

/** GET /v1/models/metrics */
export async function getModelsMetrics(
  options: ClientOptions = {},
): Promise<ApiResult<ModelMetricsPage>> {
  const result = await execute("/v1/models/metrics", modelMetricsSchema, {
    ...options,
    prepare: prepareModelMetricsBody,
  });
  if (!result.ok) {
    return result;
  }
  return {
    ok: true,
    data: { ...toPage(result.data), active_model: result.data.active_model ?? null },
  };
}

/** GET /v1/alerts */
export interface AlertQuery extends CursorQuery {
  status?: AlertStatus | null | undefined;
  severity?: AlertSeverity | null | undefined;
  eventId?: string | null | undefined;
  opportunityId?: string | null | undefined;
  raisedSince?: string | null | undefined;
}

export function getAlerts(
  params: AlertQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<Page<Alert>>> {
  return getPage("/v1/alerts", alertPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      status: params.status,
      severity: params.severity,
      event_id: params.eventId,
      opportunity_id: params.opportunityId,
      raised_since: params.raisedSince,
    },
  });
}

/** GET /v1/paper-ledger */
export interface LedgerQuery extends CursorQuery {
  status?: LedgerStatus | null | undefined;
  eventId?: string | null | undefined;
}

/** Paper ledger page plus the optional roll-up the API may include. */
export interface LedgerPage extends Page<LedgerEntry> {
  summary: LedgerSummary | null;
}

export async function getPaperLedger(
  params: LedgerQuery = {},
  options: ClientOptions = {},
): Promise<ApiResult<LedgerPage>> {
  const result = await execute("/v1/paper-ledger", ledgerEntryPageSchema, {
    ...options,
    query: {
      cursor: params.cursor,
      limit: params.limit,
      status: params.status,
      event_id: params.eventId,
    },
    prepare: wrapArrayBody,
  });
  if (!result.ok) {
    return result;
  }
  return { ok: true, data: { ...toPage(result.data), summary: result.data.summary ?? null } };
}

/* ========================================================================== *
 * Analyst-only actions
 *
 * These two POSTs go to same-origin Next.js Route Handlers, never straight to the
 * API from the browser:
 *   POST /api/alerts/{id}/acknowledge   ->  POST {API}/v1/alerts/{id}/acknowledge
 *   POST /api/resolver/{id}/decision    ->  POST {API}/v1/resolver/review/{id}/decision
 * The analyst key stays in the server process (ACADEMIC_EDGE_ANALYST_API_KEY) and
 * the handlers refuse to run unless ACADEMIC_EDGE_ANALYST_ACTIONS=enabled. There
 * is deliberately no code path here that places a wager or stores credentials.
 * ========================================================================== */

/** Same-origin base for the analyst proxies. */
export const ANALYST_PROXY_BASE = "/api";

export interface AcknowledgeAlertInput {
  /** Recorded in the API audit log; defaults to "web-analyst" server-side. */
  acknowledgedBy?: string | null | undefined;
}

export function acknowledgeAlert(
  alertId: string,
  input: AcknowledgeAlertInput = {},
  options: ClientOptions = {},
): Promise<ApiResult<AlertAcknowledgement>> {
  return execute(analystAlertAckPath(alertId), alertAcknowledgementSchema, {
    ...options,
    method: "POST",
    absoluteUrl: analystAlertAckPath(alertId),
    headers: { "Content-Type": "application/json" },
    body: { acknowledged_by: input.acknowledgedBy ?? null },
    prepare: unwrapItemBody,
  });
}

export function analystAlertAckPath(alertId: string): string {
  return `${ANALYST_PROXY_BASE}/alerts/${encodeURIComponent(alertId)}/acknowledge`;
}

export type ResolverDecisionAction = "link" | "reject";

export interface ResolverDecisionInput {
  action: ResolverDecisionAction;
  /** Required for `action: "link"`: the canonical event to link onto. */
  canonicalEventId?: string | null | undefined;
  decidedBy?: string | null | undefined;
  note?: string | null | undefined;
}

export function resolveReview(
  reviewId: string,
  input: ResolverDecisionInput,
  options: ClientOptions = {},
): Promise<ApiResult<ResolverDecision>> {
  return execute(analystResolverDecisionPath(reviewId), resolverDecisionSchema, {
    ...options,
    method: "POST",
    absoluteUrl: analystResolverDecisionPath(reviewId),
    headers: { "Content-Type": "application/json" },
    body: {
      action: input.action,
      canonical_event_id: input.canonicalEventId ?? null,
      decided_by: input.decidedBy ?? null,
      note: input.note ?? null,
    },
    prepare: unwrapItemBody,
  });
}

export function analystResolverDecisionPath(reviewId: string): string {
  return `${ANALYST_PROXY_BASE}/resolver/${encodeURIComponent(reviewId)}/decision`;
}

/* ========================================================================== *
 * Live updates (SSE) and page-level helpers
 * ========================================================================== */

/**
 * URL for `GET /v1/stream/opportunities`.
 *
 * `EventSource` cannot set request headers, so the optional reader key is passed
 * as a query parameter (documented assumption: a reader-role stream accepts
 * `?api_key=`). No analyst credential is ever used for the stream.
 */
export function streamOpportunitiesUrl(): string {
  const url = new URL(`${API_BASE_URL}/v1/stream/opportunities`);
  if (API_READ_KEY !== "") {
    url.searchParams.set("api_key", API_READ_KEY);
  }
  return url.toString();
}

/**
 * True when at least one source behind this page failed, or the API flagged the
 * page as partial. Drives the PartialSourceNotice on every screen.
 */
export function pageIsPartial(page: {
  partial: boolean;
  sources_failed: readonly string[];
}): boolean {
  return page.partial || page.sources_failed.length > 0;
}