/**
 * Zod schemas for the Academic Edge FastAPI read contract.
 *
 * ---------------------------------------------------------------------------
 * SOURCE OF TRUTH AND ASSUMPTIONS (read this before changing a field name)
 * ---------------------------------------------------------------------------
 * `apps/api/academic_edge_api/schemas.py` did NOT exist when this client was
 * written (the API was being built in parallel), so every response schema here
 * is derived from the *frozen* contracts the API must serialise from:
 *
 *   packages/domain/academic_edge_domain/models.py   (columns + nullability)
 *   packages/domain/academic_edge_domain/enums.py    (StrEnum values)
 *   packages/domain/academic_edge_domain/settings.py (thresholds used in labels)
 *   config/source_policies.yaml                      (source ids, tiers, modes)
 *   the endpoint list in the project brief (API section) and the paths asserted
 *   by .github/workflows/ci.yml (`/v1/sources/health`, `/v1/events`,
 *   `/v1/opportunities`, `/v1/alerts`, `/v1/paper-ledger`, ...).
 *
 * CONVENTIONS THIS CLIENT ASSUMES
 *  1. Lists are cursor paginated as `{ "items": [...], "next_cursor": null|str }`.
 *     Optional metadata (`generated_at`, `fixture_mode`, `stale`, `partial`,
 *     `sources_failed`) is honoured when present and derived in the UI when not.
 *     A bare JSON array body is also accepted and wrapped.
 *  2. Single-entity endpoints return the object itself, or `{ "item": {...} }`.
 *  3. `Decimal` columns may serialise as a string OR a number. Both are reduced
 *     to a string here and only ever converted to `number` for *display*.
 *  4. Timestamps are UTC ISO-8601 strings; naive strings are treated as UTC.
 *  5. `is_synthetic` is REQUIRED on every data record. If the API omits it the
 *     screen fails loudly with a contract error instead of silently presenting
 *     fixture-derived numbers as live market data (brief, SAFETY #6).
 *  6. Fields marked "display join" are extra, denormalised values the API may
 *     add (participant names, display names). They are optional here and the UI
 *     degrades to identifiers when absent - it never invents a value.
 *
 * Anything that could not be verified against a running API is listed in
 * apps/web/README.md under "Contract assumptions & verification".
 */

import { z } from "zod";

/* ========================================================================== *
 * 1. Enum mirrors (academic_edge_domain/enums.py)
 * ========================================================================== */

export const sportSchema = z.enum(["football"]);

export const marketTypeSchema = z.enum(["ft_1x2", "ft_totals_2_5", "ft_btts"]);

export const marketPeriodSchema = z.enum(["full_time", "first_half", "second_half"]);

export const teamScopeSchema = z.enum(["home", "away", "neutral"]);

export const outcomeKindSchema = z.enum(["home", "draw", "away", "over", "under", "yes", "no"]);

export const venueKindSchema = z.enum([
  "bookmaker",
  "exchange",
  "prediction_market",
  "synthetic_fixture",
]);

export const sourceTierSchema = z.enum([
  "free",
  "public",
  "public_read",
  "manual",
  "paid",
  "synthetic",
]);

export const automationScopeSchema = z.enum([
  "official_api_only",
  "documented_public_reads",
  "bulk_static_download",
  "manual_csv_only",
  "local_fixtures",
]);

export const reviewStatusSchema = z.enum([
  "auto_accepted",
  "review_required",
  "manually_linked",
  "rejected",
]);

export const hardRejectReasonSchema = z.enum([
  "sport_mismatch",
  "competition_mismatch",
  "home_away_inversion",
  "period_mismatch",
  "line_mismatch",
  "overtime_mismatch",
  "settlement_version_mismatch",
  "start_time_out_of_window",
  "participant_mismatch",
]);

export const deVigMethodSchema = z.enum(["multiplicative", "power"]);

export const opportunityTypeSchema = z.enum(["arbitrage", "positive_ev", "model_disagreement"]);

export const freshnessLabelSchema = z.enum(["fresh", "aging", "stale"]);

export const alertStatusSchema = z.enum(["open", "acknowledged", "expired", "suppressed"]);

export const alertSeveritySchema = z.enum(["info", "watch", "actionable"]);

export const settlementStatusSchema = z.enum(["pending", "graded", "void", "abandoned"]);

export const ledgerStatusSchema = z.enum(["open", "settled", "void"]);

export const roleSchema = z.enum(["reader", "analyst", "admin"]);

/**
 * `SourceHealthSnapshot.mode` is a free-form VARCHAR in the domain model with a
 * default of "live" ("fixture" is used by ingest runs). It is deliberately not a
 * closed enum here: an unknown mode must degrade to "unknown", never crash the
 * source-health screen.
 */
export const sourceModeSchema = z.string().min(1);

export type Sport = z.infer<typeof sportSchema>;
export type MarketType = z.infer<typeof marketTypeSchema>;
export type MarketPeriod = z.infer<typeof marketPeriodSchema>;
export type TeamScope = z.infer<typeof teamScopeSchema>;
export type OutcomeKind = z.infer<typeof outcomeKindSchema>;
export type VenueKind = z.infer<typeof venueKindSchema>;
export type SourceTier = z.infer<typeof sourceTierSchema>;
export type AutomationScope = z.infer<typeof automationScopeSchema>;
export type ReviewStatus = z.infer<typeof reviewStatusSchema>;
export type HardRejectReason = z.infer<typeof hardRejectReasonSchema>;
export type DeVigMethod = z.infer<typeof deVigMethodSchema>;
export type OpportunityType = z.infer<typeof opportunityTypeSchema>;
export type FreshnessLabel = z.infer<typeof freshnessLabelSchema>;
export type AlertStatus = z.infer<typeof alertStatusSchema>;
export type AlertSeverity = z.infer<typeof alertSeveritySchema>;
export type SettlementStatus = z.infer<typeof settlementStatusSchema>;
export type LedgerStatus = z.infer<typeof ledgerStatusSchema>;
export type Role = z.infer<typeof roleSchema>;

/* ========================================================================== *
 * 2. Primitive helpers
 * ========================================================================== */

/** Shown when a value is genuinely absent from the API response. */
export const NOT_AVAILABLE = "not reported";

/** `Decimal` columns arrive as string or number; keep them lossless as strings. */
const decimalLikeSchema = z.union([z.string(), z.number()]);

export const decimalStringSchema = decimalLikeSchema.transform((value) =>
  typeof value === "number" ? String(value) : value,
);

export const optionalDecimalStringSchema = decimalLikeSchema.nullish().transform((value) => {
  if (value === null || value === undefined) {
    return null;
  }
  return typeof value === "number" ? String(value) : value;
});

export const timestampSchema = z.string().min(1);

export const optionalTimestampSchema = z
  .string()
  .nullish()
  .transform((value) => (value === null || value === undefined || value === "" ? null : value));

export const optionalStringSchema = z
  .string()
  .nullish()
  .transform((value) => (value === null || value === undefined || value === "" ? null : value));

export const optionalNumberSchema = z
  .number()
  .nullish()
  .transform((value) => (value === null || value === undefined ? null : value));

export const numberOrZeroSchema = z
  .number()
  .nullish()
  .transform((value) => (value === null || value === undefined ? 0 : value));

export const booleanOrFalseSchema = z.boolean().nullish().transform((value) => value === true);

/** `Mapped[dict[str, Any]]` columns: an object, possibly null, never an array. */
export const jsonObjectSchema = z
  .record(z.string(), z.unknown())
  .nullish()
  .transform((value) => value ?? {});

/** `Mapped[list[str]]` columns. */
export const stringListSchema = z
  .array(z.string())
  .nullish()
  .transform((value) => value ?? []);

/** `Mapped[list[dict[str, Any]]]` columns (lineup players, ...). */
export const jsonListSchema = z
  .array(z.record(z.string(), z.unknown()))
  .nullish()
  .transform((value) => value ?? []);

/**
 * Tolerant enum reader: a value outside the mirrored StrEnum becomes `null`
 * (rendered as "not reported") instead of failing the whole payload, so a new
 * provider value cannot blank out an analyst screen.
 */
export function looseEnumSchema<T extends readonly [string, ...string[]]>(values: T) {
  return z
    .string()
    .nullish()
    .transform((value) =>
      value === null || value === undefined || !(values as readonly string[]).includes(value)
        ? null
        : (value as T[number]),
    );
}

/* ========================================================================== *
 * 3. Pagination envelope
 * ========================================================================== */

export const pageMetaSchema = z.object({
  next_cursor: z.string().nullish(),
  generated_at: z.string().nullish(),
  fixture_mode: z.boolean().nullish(),
  stale: z.boolean().nullish(),
  partial: z.boolean().nullish(),
  sources_failed: z.array(z.string()).nullish(),
});

export type PageMeta = z.infer<typeof pageMetaSchema>;

/** Normalised page shape that every `getX` client function resolves to. */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  generated_at: string | null;
  fixture_mode: boolean;
  stale: boolean;
  partial: boolean;
  sources_failed: string[];
}

export function paginatedSchema<TItem extends z.ZodTypeAny>(item: TItem) {
  return pageMetaSchema.extend({ items: z.array(item) });
}

/* ========================================================================== *
 * 4. `best_legs` entries
 *
 * `Opportunity.best_legs` is `list[dict[str, Any]]` in the domain model, so the
 * web client cannot know the key set statically. Every field is optional and the
 * UI renders "not reported" plus a warning rather than inventing a number.
 * ========================================================================== */

export const bestLegSchema = z.object({
  /** Pricing-engine leg fields (expected names; all optional by design). */
  source_id: optionalStringSchema,
  venue_name: optionalStringSchema,
  venue_kind: looseEnumSchema(venueKindSchema.options).optional(),
  market_id: optionalStringSchema,
  outcome_id: optionalStringSchema,
  outcome_kind: looseEnumSchema(outcomeKindSchema.options).optional(),
  outcome_label: optionalStringSchema,
  decimal_odds: optionalDecimalStringSchema,
  available_size: optionalDecimalStringSchema,
  currency: optionalStringSchema,
  commission_bps: optionalNumberSchema,
  stake: optionalDecimalStringSchema,
  quote_age_seconds: optionalNumberSchema,
  freshness: looseEnumSchema(freshnessLabelSchema.options).optional(),
  observed_at: optionalTimestampSchema,
  received_at: optionalTimestampSchema,
  provider_timestamp: optionalTimestampSchema,
  latency_ms: optionalNumberSchema,
  raw_payload_id: optionalStringSchema,
  is_synthetic: z.boolean().nullish().transform((value) => value ?? null),
  /** Some engines nest the originating quote object instead of flattening it. */
  quote: z
    .record(z.string(), z.unknown())
    .nullish()
    .transform((value) => value ?? null),
});

export type BestLeg = z.infer<typeof bestLegSchema>;

/** A friction key the pricing engine is known to emit (label + optional unit). */
export const FRICTION_BPS_KEYS = [
  "slippage_bps",
  "exchange_fee_bps",
  "fx_spread_bps",
  "commission_bps",
  "quote_age_haircut_bps",
  "stale_quote_haircut_bps",
  "total_friction_bps",
  "gross_edge_bps",
  "net_edge_bps",
  "overround_bps",
] as const;

/* ========================================================================== *
 * 5. Entity schemas (mirror models.py column names)
 * ========================================================================== */

/** `source_health_snapshot` plus the policy fields an analyst needs beside it. */
export const sourceHealthSchema = z.object({
  id: optionalStringSchema,
  source_id: z.string().min(1),
  display_name: optionalStringSchema,
  checked_at: timestampSchema,
  ok: z.boolean(),
  latency_ms: optionalNumberSchema,
  mode: sourceModeSchema,
  quota_used: optionalNumberSchema,
  quota_limit: optionalNumberSchema,
  parser_drift_count: numberOrZeroSchema,
  consecutive_failures: numberOrZeroSchema,
  message: optionalStringSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins / registry (config/source_policies.yaml) */
  tier: looseEnumSchema(sourceTierSchema.options).optional(),
  automation_allowed: z.boolean().nullish().transform((value) => value ?? null),
  automation_scope: looseEnumSchema(automationScopeSchema.options).optional(),
  rate_limit_per_minute: optionalNumberSchema,
  license: optionalStringSchema,
  quota_notes: optionalStringSchema,
  notes: optionalStringSchema,
  vendor_url: optionalStringSchema,
  docs_url: optionalStringSchema,
  enabled: z.boolean().nullish().transform((value) => value ?? null),
  terms_reviewed_by: optionalStringSchema,
  terms_reviewed_at: optionalTimestampSchema,
});

export type SourceHealth = z.infer<typeof sourceHealthSchema>;

/** `event` plus participant/competition display joins. */
export const eventSchema = z.object({
  id: z.string().min(1),
  sport_id: optionalStringSchema,
  competition_id: z.string().min(1),
  season_id: optionalStringSchema,
  home_participant_id: z.string().min(1),
  away_participant_id: z.string().min(1),
  venue_id: optionalStringSchema,
  start_time_utc: timestampSchema,
  status: z.string().min(1),
  round_label: optionalStringSchema,
  home_score: optionalNumberSchema,
  away_score: optionalNumberSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins */
  home_name: optionalStringSchema,
  away_name: optionalStringSchema,
  competition_name: optionalStringSchema,
  competition_country: optionalStringSchema,
  season_label: optionalStringSchema,
  venue_name: optionalStringSchema,
  sport_code: optionalStringSchema,
});

export type EventRecord = z.infer<typeof eventSchema>;

export const outcomeSchema = z.object({
  id: z.string().min(1),
  market_id: z.string().min(1),
  outcome_kind: outcomeKindSchema,
  label: z.string().min(1),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,
});

export type Outcome = z.infer<typeof outcomeSchema>;

/**
 * `market`: the normalised definition. Identity = event + market_type + period +
 * line_value + team_scope + overtime_included + settlement_version.
 */
export const marketSchema = z.object({
  id: z.string().min(1),
  event_id: z.string().min(1),
  sport_id: optionalStringSchema,
  market_type: marketTypeSchema,
  period: marketPeriodSchema,
  line_value: optionalDecimalStringSchema,
  team_scope: teamScopeSchema,
  overtime_included: z.boolean(),
  settlement_version: z.string().min(1),
  identity_key: optionalStringSchema,
  settlement_rule: z.string().min(1),
  display_name: z.string().min(1),
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,
  outcomes: z.array(outcomeSchema).nullish().transform((value) => value ?? []),
});

export type Market = z.infer<typeof marketSchema>;

/** `quote`: an observed price with mandatory provenance (brief, SAFETY #5). */
export const quoteSchema = z.object({
  id: z.string().min(1),
  market_id: z.string().min(1),
  outcome_id: z.string().min(1),
  source_id: z.string().min(1),
  venue_kind: venueKindSchema,
  venue_name: z.string().min(1),
  provider_market_id: optionalStringSchema,
  provider_outcome_id: optionalStringSchema,
  decimal_odds: decimalStringSchema,
  available_size: optionalDecimalStringSchema,
  currency: z.string().min(1),
  commission_bps: numberOrZeroSchema,
  observed_at: timestampSchema,
  provider_timestamp: optionalTimestampSchema,
  received_at: optionalTimestampSchema,
  latency_ms: optionalNumberSchema,
  freshness: freshnessLabelSchema,
  is_synthetic: z.boolean(),
  raw_payload_id: optionalStringSchema,
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins / derived */
  source_display_name: optionalStringSchema,
  age_seconds: optionalNumberSchema,

  /* present only when the endpoint answers with `quote_snapshot` rows */
  as_of: optionalTimestampSchema,
  best_decimal_odds: optionalDecimalStringSchema,
  best_source_id: optionalStringSchema,
  fair_probability: optionalDecimalStringSchema,
  implied_probability: optionalDecimalStringSchema,
  de_vig_method: looseEnumSchema(deVigMethodSchema.options).optional(),
  overround: optionalDecimalStringSchema,
  quote_count: optionalNumberSchema,
});

export type Quote = z.infer<typeof quoteSchema>;

/**
 * `opportunity`. `is_actionable` is only ever true when every leg is fresh,
 * settlement rules match, quoted size covers the stake and net edge survives
 * conservative friction - so the UI treats `false` as "blocked by policy or
 * evidence", never as a slightly-worse version of `true`.
 */
export const opportunitySchema = z.object({
  id: z.string().min(1),
  event_id: z.string().min(1),
  market_id: z.string().min(1),
  opportunity_type: opportunityTypeSchema,
  model_version_id: optionalStringSchema,
  gross_edge_bps: z.number(),
  net_edge_bps: z.number(),
  confidence: z.number(),
  best_legs: z.array(bestLegSchema).nullish().transform((value) => value ?? []),
  friction: jsonObjectSchema,
  reasons: stringListSchema,
  warnings: stringListSchema,
  total_stake: optionalDecimalStringSchema,
  expected_profit: optionalDecimalStringSchema,
  currency: z.string().min(1),
  detected_at: timestampSchema,
  expires_at: optionalTimestampSchema,
  is_actionable: z.boolean(),
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins */
  event_label: optionalStringSchema,
  market_display_name: optionalStringSchema,
  market_type: looseEnumSchema(marketTypeSchema.options).optional(),
  quote_age_seconds: optionalNumberSchema,
  liquidity: optionalDecimalStringSchema,
  sources: z.array(z.string()).nullish().transform((value) => value ?? []),
});

export type Opportunity = z.infer<typeof opportunitySchema>;

/** `provider_event_map`: one resolver review row plus its evidence. */
export const resolverReviewSchema = z.object({
  id: z.string().min(1),
  canonical_event_id: z.string().min(1),
  source_id: z.string().min(1),
  provider_event_id: z.string().min(1),
  provider_competition_id: optionalStringSchema,
  provider_home_id: optionalStringSchema,
  provider_away_id: optionalStringSchema,
  review_status: reviewStatusSchema,
  match_score: z.number(),
  evidence: jsonObjectSchema,
  hard_reject_reasons: stringListSchema,
  decided_at: optionalTimestampSchema,
  decided_by: optionalStringSchema,
  last_seen_at: optionalTimestampSchema,
  raw_payload_id: optionalStringSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins: provider-side and canonical-side labels */
  provider_home_name: optionalStringSchema,
  provider_away_name: optionalStringSchema,
  provider_start_time_utc: optionalTimestampSchema,
  provider_competition_name: optionalStringSchema,
  canonical_home_name: optionalStringSchema,
  canonical_away_name: optionalStringSchema,
  canonical_start_time_utc: optionalTimestampSchema,
  canonical_competition_name: optionalStringSchema,
});

export type ResolverReview = z.infer<typeof resolverReviewSchema>;

/** `prediction`: a model probability with explicit abstention support. */
export const predictionSchema = z.object({
  id: z.string().min(1),
  event_id: z.string().min(1),
  model_version_id: z.string().min(1),
  market_type: marketTypeSchema,
  outcome_kind: outcomeKindSchema,
  probability: decimalStringSchema,
  fair_odds: decimalStringSchema,
  uncertainty: optionalNumberSchema,
  abstained: z.boolean(),
  abstain_reason: optionalStringSchema,
  market_free: z.boolean(),
  as_of: timestampSchema,
  explanation: jsonObjectSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins */
  model_name: optionalStringSchema,
  model_version: optionalStringSchema,
});

export type Prediction = z.infer<typeof predictionSchema>;

/**
 * `model_version` ("model card"). `params` and `metrics` are JSON columns in the
 * domain model, so their keys are rendered generically with humanised labels.
 */
export const modelCardSchema = z.object({
  id: optionalStringSchema,
  name: z.string().min(1),
  version: z.string().min(1),
  algorithm: z.string().min(1),
  description: optionalStringSchema,
  trained_at: timestampSchema,
  train_window_start: optionalTimestampSchema,
  train_window_end: optionalTimestampSchema,
  calibration_window_start: optionalTimestampSchema,
  calibration_window_end: optionalTimestampSchema,
  params: jsonObjectSchema,
  metrics: jsonObjectSchema,
  artifact_uri: optionalStringSchema,
  is_active: booleanOrFalseSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* reporting hygiene: how many events/folds backed those metrics */
  evaluated_event_count: optionalNumberSchema,
  walk_forward_folds: optionalNumberSchema,
  evaluation_notes: optionalStringSchema,
});

export type ModelCard = z.infer<typeof modelCardSchema>;

/** `alert`: a rule firing with the evidence snapshotted at raise time. */
export const alertSchema = z.object({
  id: z.string().min(1),
  alert_rule_id: z.string().min(1),
  opportunity_id: optionalStringSchema,
  event_id: z.string().min(1),
  market_id: optionalStringSchema,
  status: alertStatusSchema,
  severity: alertSeveritySchema,
  message: z.string().min(1),
  dedupe_key: z.string().min(1),
  evidence: jsonObjectSchema,
  raised_at: timestampSchema,
  acknowledged_at: optionalTimestampSchema,
  acknowledged_by: optionalStringSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins */
  rule_name: optionalStringSchema,
  event_label: optionalStringSchema,
});

export type Alert = z.infer<typeof alertSchema>;

/** Response of the acknowledge POST (analyst role only). */
export const alertAcknowledgementSchema = z.object({
  id: z.string().min(1),
  status: alertStatusSchema,
  acknowledged_at: optionalTimestampSchema,
  acknowledged_by: optionalStringSchema,
});

export type AlertAcknowledgement = z.infer<typeof alertAcknowledgementSchema>;

/** Response of the resolver decision POST (analyst role only). */
export const resolverDecisionSchema = z.object({
  id: z.string().min(1),
  review_status: reviewStatusSchema,
  decided_at: optionalTimestampSchema,
  decided_by: optionalStringSchema,
  canonical_event_id: optionalStringSchema,
});

export type ResolverDecision = z.infer<typeof resolverDecisionSchema>;

/** `paper_ledger_entry`: paper trading only - never a real stake. */
export const ledgerEntrySchema = z.object({
  id: z.string().min(1),
  event_id: z.string().min(1),
  market_id: z.string().min(1),
  outcome_id: z.string().min(1),
  opportunity_id: optionalStringSchema,
  source_id: z.string().min(1),
  stake: decimalStringSchema,
  decimal_odds: decimalStringSchema,
  currency: z.string().min(1),
  fees: optionalDecimalStringSchema,
  status: ledgerStatusSchema,
  placed_at: timestampSchema,
  settled_at: optionalTimestampSchema,
  pnl: optionalDecimalStringSchema,
  notes: optionalStringSchema,
  is_synthetic: z.boolean(),
  created_at: optionalTimestampSchema,
  updated_at: optionalTimestampSchema,

  /* display joins */
  event_label: optionalStringSchema,
  market_label: optionalStringSchema,
  outcome_label: optionalStringSchema,
  venue_name: optionalStringSchema,
});

export type LedgerEntry = z.infer<typeof ledgerEntrySchema>;

/** Optional roll-up the ledger endpoint may return alongside the entries. */
export const ledgerSummarySchema = z.object({
  entry_count: optionalNumberSchema,
  open_count: optionalNumberSchema,
  settled_count: optionalNumberSchema,
  open_stake: optionalDecimalStringSchema,
  settled_pnl: optionalDecimalStringSchema,
  total_fees: optionalDecimalStringSchema,
  currency: optionalStringSchema,
  win_count: optionalNumberSchema,
  loss_count: optionalNumberSchema,
  void_count: optionalNumberSchema,
});

export type LedgerSummary = z.infer<typeof ledgerSummarySchema>;

/* ========================================================================== *
 * 6. Response envelopes
 * ========================================================================== */

export const sourceHealthPageSchema = paginatedSchema(sourceHealthSchema);
export const eventPageSchema = paginatedSchema(eventSchema);
export const marketPageSchema = paginatedSchema(marketSchema);
export const quotePageSchema = paginatedSchema(quoteSchema);
export const opportunityPageSchema = paginatedSchema(opportunitySchema);
export const resolverReviewPageSchema = paginatedSchema(resolverReviewSchema);
export const predictionPageSchema = paginatedSchema(predictionSchema);
export const alertPageSchema = paginatedSchema(alertSchema);
export const ledgerEntryPageSchema = paginatedSchema(ledgerEntrySchema).extend({
  summary: ledgerSummarySchema.nullish().transform((value) => value ?? null),
});

/**
 * `/v1/models/metrics` may answer with a page of model cards, a bare array, or a
 * single object. All three are accepted; `getModelsMetrics` normalises the result
 * to `Page<ModelCard>` so the model-card screen has exactly one code path.
 */
export const modelMetricsSchema = z.object({
  items: z.array(modelCardSchema).nullish().transform((value) => value ?? []),
  active_model: modelCardSchema.nullish().transform((value) => value ?? null),
  next_cursor: z.string().nullish(),
  generated_at: z.string().nullish(),
  fixture_mode: z.boolean().nullish(),
  stale: z.boolean().nullish(),
  partial: z.boolean().nullish(),
  sources_failed: z.array(z.string()).nullish(),
});

export type ModelMetrics = z.infer<typeof modelMetricsSchema>;

/** Injury/availability row (optional context; never invented by the client). */
export const injurySchema = z.object({
  id: optionalStringSchema,
  participant_id: optionalStringSchema,
  participant_name: optionalStringSchema,
  player_name: z.string().min(1),
  status: z.string().min(1),
  reason: optionalStringSchema,
  expected_return: optionalTimestampSchema,
  source_id: z.string().min(1),
  reported_at: timestampSchema,
  is_synthetic: z.boolean(),
});

export type Injury = z.infer<typeof injurySchema>;

/** Lineup row: expected or confirmed XI for one participant (brief: UI section). */
export const lineupSchema = z.object({
  id: optionalStringSchema,
  participant_id: optionalStringSchema,
  participant_name: optionalStringSchema,
  is_confirmed: booleanOrFalseSchema,
  formation: optionalStringSchema,
  coach: optionalStringSchema,
  players: jsonListSchema,
  source_id: z.string().min(1),
  published_at: timestampSchema,
  is_synthetic: z.boolean(),
});

export type Lineup = z.infer<typeof lineupSchema>;

/** `/v1/events/{id}`: the event plus optional context the API may include. */
export const eventDetailSchema = eventSchema.extend({
  markets: z.array(marketSchema).nullish().transform((value) => value ?? []),
  /** Source identifiers that resolved onto this event (brief: show source ids). */
  source_links: z.array(resolverReviewSchema).nullish().transform((value) => value ?? []),
  injuries: z.array(injurySchema).nullish().transform((value) => value ?? []),
  lineups: z.array(lineupSchema).nullish().transform((value) => value ?? []),
});

export type EventDetail = z.infer<typeof eventDetailSchema>;

/**
 * Single-entity envelopes: the object itself, or `{ "item": {...} }`. `api.ts`
 * unwraps before parsing, so this helper exists only for completeness/tests.
 */
export function itemEnvelopeSchema<TItem extends z.ZodTypeAny>(item: TItem) {
  return z.union([item, z.object({ item })]);
}