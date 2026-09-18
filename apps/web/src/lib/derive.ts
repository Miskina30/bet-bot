/**
 * Derivations shared by the dashboard screens.
 *
 * Everything here is *evidence-safe*: when the API does not report a value the
 * helper returns `null`/"not reported" so the UI can show a warning instead of a
 * number. Nothing here estimates market data; the only arithmetic is aggregating
 * values the API already published (oldest leg age, summed quoted size) plus
 * threshold banding for colour labels. No helper in this file claims a profit.
 */

import {
  ageInSeconds,
  formatBps,
  formatUnknown,
  humaniseEnumValue,
  humaniseKey,
  isRecord,
  toNumber,
} from "@/lib/format";
import type {
  BestLeg,
  FreshnessLabel,
  Market,
  ModelCard,
  Opportunity,
  Prediction,
  Quote,
  ResolverReview,
} from "@/lib/schemas";
import { sourceDisplayName } from "@/lib/sources";

/* -------------------------------------------------------------------------- *
 * Thresholds (mirror academic_edge_domain.settings defaults)
 * -------------------------------------------------------------------------- */

/** Comfortably fresh: well inside PRICING_MAX_QUOTE_AGE_SECONDS (180). */
export const FRESH_MAX_SECONDS = 60;
/** PRICING_MAX_QUOTE_AGE_SECONDS default - beyond this a quote is stale. */
export const AGING_MAX_SECONDS = 180;
/** PRICING_MIN_NET_EDGE_BPS default - below this no row is actionable. */
export const MIN_NET_EDGE_BPS = 50;
/** RESOLVER_AUTO_ACCEPT_THRESHOLD / RESOLVER_REVIEW_THRESHOLD defaults. */
export const RESOLVER_AUTO_ACCEPT = 0.985;
export const RESOLVER_REVIEW = 0.94;
/** The SSE hook marks the stream stale after this long without an event. */
export const STREAM_STALE_AFTER_MS = 30_000;

export type Tone = "neutral" | "positive" | "caution" | "danger" | "accent";

/**
 * Freshness when the API supplied an age but no label. Thresholds follow the
 * pricing configuration defaults; a missing age returns `null` (rendered as "not
 * reported") - never a guess that would make a stale quote look fresh.
 */
export function deriveFreshness(ageSeconds: number | null): FreshnessLabel | null {
  if (ageSeconds === null || !Number.isFinite(ageSeconds)) {
    return null;
  }
  if (ageSeconds <= FRESH_MAX_SECONDS) {
    return "fresh";
  }
  if (ageSeconds <= AGING_MAX_SECONDS) {
    return "aging";
  }
  return "stale";
}

/* -------------------------------------------------------------------------- *
 * Legs (`best_legs` is list[dict[str, Any]] - every field is optional)
 * -------------------------------------------------------------------------- */

export interface LegView {
  index: number;
  sourceId: string | null;
  sourceName: string;
  venueName: string | null;
  venueKind: string | null;
  outcomeLabel: string;
  decimalOdds: string | null;
  availableSize: string | null;
  stake: string | null;
  currency: string | null;
  observedAt: string | null;
  quoteAgeSeconds: number | null;
  freshness: FreshnessLabel | null;
  providerTimestamp: string | null;
  latencyMs: number | null;
  rawPayloadId: string | null;
  isSynthetic: boolean | null;
  /** True when provenance (source_id + observed_at) is missing for this leg. */
  provenanceMissing: boolean;
}

function nestedValue(leg: BestLeg, key: string): unknown {
  const nested = leg.quote;
  if (nested === null) {
    return undefined;
  }
  return nested[key];
}

function legString(leg: BestLeg, key: string): string | null {
  const direct = (leg as Record<string, unknown>)[key];
  if (typeof direct === "string" && direct !== "") {
    return direct;
  }
  const nested = nestedValue(leg, key);
  if (typeof nested === "string" && nested !== "") {
    return nested;
  }
  if (typeof nested === "number") {
    return String(nested);
  }
  return null;
}

function legNumber(leg: BestLeg, key: string): number | null {
  const direct = (leg as Record<string, unknown>)[key];
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct;
  }
  const nested = nestedValue(leg, key);
  if (typeof nested === "number" && Number.isFinite(nested)) {
    return nested;
  }
  return null;
}

export function toLegViews(legs: readonly BestLeg[], nowMs: number = Date.now()): LegView[] {
  return legs.map((leg, index) => {
    const sourceId = leg.source_id ?? legString(leg, "source_id");
    const observedAt = leg.observed_at ?? legString(leg, "observed_at");
    const reportedAge =
      leg.quote_age_seconds !== null && leg.quote_age_seconds !== undefined
        ? leg.quote_age_seconds
        : legNumber(leg, "quote_age_seconds");
    const quoteAgeSeconds = reportedAge ?? ageInSeconds(observedAt, nowMs);
    return {
      index,
      sourceId,
      sourceName: sourceDisplayName(sourceId, leg.venue_name),
      venueName: leg.venue_name ?? null,
      venueKind: leg.venue_kind ?? null,
      outcomeLabel:
        leg.outcome_label ?? humaniseEnumValue(leg.outcome_kind ?? null) ?? "outcome not labelled",
      decimalOdds: leg.decimal_odds ?? legString(leg, "decimal_odds"),
      availableSize: leg.available_size ?? legString(leg, "available_size"),
      stake: leg.stake ?? legString(leg, "stake"),
      currency: leg.currency ?? legString(leg, "currency"),
      observedAt,
      quoteAgeSeconds,
      freshness: leg.freshness ?? deriveFreshness(quoteAgeSeconds),
      providerTimestamp: leg.provider_timestamp ?? legString(leg, "provider_timestamp"),
      latencyMs: leg.latency_ms ?? legNumber(leg, "latency_ms"),
      rawPayloadId: leg.raw_payload_id ?? legString(leg, "raw_payload_id"),
      isSynthetic: leg.is_synthetic ?? null,
      provenanceMissing: sourceId === null || sourceId === "" || observedAt === null,
    };
  });
}

/* -------------------------------------------------------------------------- *
 * Opportunity aggregates
 * -------------------------------------------------------------------------- */

/** Worst-case (oldest) quote age across the legs, or the API's own figure. */
export function opportunityQuoteAgeSeconds(
  opportunity: Opportunity,
  nowMs: number = Date.now(),
): number | null {
  if (opportunity.quote_age_seconds !== null && opportunity.quote_age_seconds !== undefined) {
    return opportunity.quote_age_seconds;
  }
  const ages = toLegViews(opportunity.best_legs, nowMs)
    .map((leg) => leg.quoteAgeSeconds)
    .filter((age): age is number => age !== null);
  if (ages.length === 0) {
    return null;
  }
  return Math.max(...ages);
}

/** Worst-case freshness across the legs (one stale leg makes the row stale). */
export function opportunityFreshness(
  opportunity: Opportunity,
  nowMs: number = Date.now(),
): FreshnessLabel | null {
  const labels = toLegViews(opportunity.best_legs, nowMs)
    .map((leg) => leg.freshness)
    .filter((label): label is FreshnessLabel => label !== null);
  if (labels.length > 0) {
    if (labels.includes("stale")) {
      return "stale";
    }
    if (labels.includes("aging")) {
      return "aging";
    }
    return "fresh";
  }
  return deriveFreshness(opportunityQuoteAgeSeconds(opportunity, nowMs));
}

/** The API's liquidity figure, else the sum of quoted leg sizes it published. */
export function opportunityLiquidity(opportunity: Opportunity): number | null {
  if (opportunity.liquidity !== null && opportunity.liquidity !== undefined) {
    return toNumber(opportunity.liquidity);
  }
  const sizes = toLegViews(opportunity.best_legs)
    .map((leg) => toNumber(leg.availableSize))
    .filter((size): size is number => size !== null);
  if (sizes.length === 0) {
    return null;
  }
  return sizes.reduce((total, size) => total + size, 0);
}

export function isOpportunityExpired(opportunity: Opportunity, nowMs: number = Date.now()): boolean {
  if (opportunity.expires_at === null || opportunity.expires_at === undefined) {
    return false;
  }
  const age = ageInSeconds(opportunity.expires_at, nowMs);
  return age !== null && age > 0;
}

/**
 * Why a row is NOT actionable. API warnings come first (authoritative), then only
 * the checks the client can actually verify. The list never asserts that a row IS
 * safe - it only fails it.
 */
export function opportunityBlockers(opportunity: Opportunity, nowMs: number = Date.now()): string[] {
  if (opportunity.is_actionable) {
    return [];
  }
  const blockers: string[] = [];
  for (const warning of opportunity.warnings) {
    blockers.push(warning);
  }
  if (isOpportunityExpired(opportunity, nowMs)) {
    blockers.push(
      `Opportunity window expired at ${opportunity.expires_at ?? "an unrecorded time"}; it is a historical record.`,
    );
  }
  if (opportunity.net_edge_bps <= 0) {
    blockers.push(
      `Modelled net edge after friction is ${formatBps(opportunity.net_edge_bps)}: nothing survives the modelled costs.`,
    );
  } else if (opportunity.net_edge_bps < MIN_NET_EDGE_BPS) {
    blockers.push(
      `Modelled net edge ${formatBps(opportunity.net_edge_bps)} is below the configured minimum of ${MIN_NET_EDGE_BPS} bps.`,
    );
  }
  const age = opportunityQuoteAgeSeconds(opportunity, nowMs);
  if (age === null) {
    blockers.push("Leg quote age was not reported, so freshness cannot be verified.");
  } else if (age > AGING_MAX_SECONDS) {
    blockers.push(
      `Oldest leg quote is ${Math.round(age)}s old (limit ${AGING_MAX_SECONDS}s), so at least one leg is stale.`,
    );
  }
  const legs = toLegViews(opportunity.best_legs, nowMs);
  if (legs.length === 0) {
    blockers.push("No legs were returned with this opportunity.");
  }
  if (legs.some((leg) => leg.provenanceMissing)) {
    blockers.push("At least one leg is missing source_id or observed_at provenance.");
  }
  if (opportunity.is_synthetic) {
    blockers.push(
      "Derived from labelled synthetic fixtures, so it demonstrates the pipeline rather than a market observation.",
    );
  }
  if (blockers.length === 0) {
    blockers.push(
      "The API flagged this row as not actionable without publishing a specific reason; treat it as unverified.",
    );
  }
  return blockers;
}

/** Confidence banding for the colour label. Purely a presentation threshold. */
export function confidenceBand(confidence: number): { label: string; tone: Tone } {
  if (!Number.isFinite(confidence)) {
    return { label: "not reported", tone: "neutral" };
  }
  if (confidence >= 0.8) {
    return { label: "high confidence", tone: "positive" };
  }
  if (confidence >= 0.6) {
    return { label: "medium confidence", tone: "caution" };
  }
  return { label: "low confidence", tone: "danger" };
}

/** Resolver score banding against the configured thresholds. */
export function matchScoreBand(score: number): { label: string; tone: Tone } {
  if (!Number.isFinite(score)) {
    return { label: "no score", tone: "neutral" };
  }
  if (score >= RESOLVER_AUTO_ACCEPT) {
    return { label: "auto-accept band", tone: "positive" };
  }
  if (score >= RESOLVER_REVIEW) {
    return { label: "review band", tone: "caution" };
  }
  return { label: "below review threshold", tone: "danger" };
}

/* -------------------------------------------------------------------------- *
 * Friction / costs breakdown
 * -------------------------------------------------------------------------- */

export interface FrictionRow {
  key: string;
  label: string;
  display: string;
  unit: "bps" | "raw";
}

/** bps rows first (they are the costs), then anything else the engine published. */
export function frictionRows(friction: Record<string, unknown>): FrictionRow[] {
  const keys = Object.keys(friction);
  if (keys.length === 0) {
    return [];
  }
  const rows: FrictionRow[] = [];
  for (const key of keys) {
    const value = friction[key];
    const numeric =
      typeof value === "number" ? value : toNumber(typeof value === "string" ? value : null);
    const isBps = key.toLowerCase().endsWith("_bps");
    const display =
      isBps && numeric !== null ? formatBps(numeric, { signed: false }) : formatUnknown(value);
    rows.push({
      key,
      label: humaniseKey(key),
      display,
      unit: isBps && numeric !== null ? "bps" : "raw",
    });
  }
  return rows.sort((left, right) => {
    const leftRank = left.unit === "bps" ? 0 : 1;
    const rightRank = right.unit === "bps" ? 0 : 1;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    return left.label.localeCompare(right.label);
  });
}

/* -------------------------------------------------------------------------- *
 * Labels for entities
 * -------------------------------------------------------------------------- */

export function orientationLabel(home: string | null, away: string | null): string | null {
  if (home === null && away === null) {
    return null;
  }
  return `${home ?? "home participant"} vs ${away ?? "away participant"}`;
}

/** Best-available event label. Falls back to the id rather than inventing names. */
export function eventLabelFromParts(
  homeName: string | null,
  awayName: string | null,
  competitionName: string | null,
  eventId: string,
): string {
  const orientation = orientationLabel(homeName, awayName);
  if (orientation === null) {
    return `event ${eventId}`;
  }
  return competitionName === null ? orientation : `${orientation} · ${competitionName}`;
}

export function opportunityEventLabel(opportunity: Opportunity): string {
  if (opportunity.event_label !== null && opportunity.event_label !== undefined) {
    return opportunity.event_label;
  }
  return `event ${opportunity.event_id}`;
}

export function opportunityMarketLabel(opportunity: Opportunity): string {
  if (opportunity.market_display_name !== null && opportunity.market_display_name !== undefined) {
    return opportunity.market_display_name;
  }
  return humaniseEnumValue(opportunity.market_type ?? null);
}

export interface DefinitionRow {
  key: string;
  label: string;
  value: string;
}

/** Normalised market definition rows for the detail screen. */
export function marketDefinitionRows(market: Market | null, marketId: string): DefinitionRow[] {
  if (market === null) {
    return [
      {
        key: "market_id",
        label: "Market id",
        value: marketId,
      },
      {
        key: "definition",
        label: "Definition",
        value: "not returned by the API for this event; treat the normalised definition as unverified",
      },
    ];
  }
  const lineValue = market.line_value === null ? null : toNumber(market.line_value);
  return [
    { key: "market_id", label: "Market id", value: market.id },
    { key: "display_name", label: "Display name", value: market.display_name },
    { key: "market_type", label: "Market type", value: humaniseEnumValue(market.market_type) },
    { key: "period", label: "Period", value: humaniseEnumValue(market.period) },
    {
      key: "line_value",
      label: "Line value",
      value: lineValue === null ? "not reported" : String(lineValue),
    },
    { key: "team_scope", label: "Team scope", value: humaniseEnumValue(market.team_scope) },
    {
      key: "overtime_included",
      label: "Overtime included",
      value: market.overtime_included ? "yes" : "no",
    },
    { key: "settlement_version", label: "Settlement version", value: market.settlement_version },
    { key: "settlement_rule", label: "Settlement rule", value: market.settlement_rule },
    {
      key: "identity_key",
      label: "Identity key",
      value: market.identity_key === null ? "not reported" : market.identity_key,
    },
    { key: "is_synthetic", label: "Synthetic", value: market.is_synthetic ? "yes" : "no" },
  ];
}

/* -------------------------------------------------------------------------- *
 * Odds timeline (quote / quote_snapshot rows)
 * -------------------------------------------------------------------------- */

export interface TimelinePoint {
  /** UTC ISO timestamp of the observation. */
  at: string;
  /** Decimal odds at that observation. */
  odds: number;
}

/**
 * One odds series for an outcome. `quote_snapshot` rows carry
 * `as_of`/`best_decimal_odds`; raw `quote` rows carry `observed_at`/`decimal_odds`.
 * Points missing either coordinate are dropped rather than interpolated - the
 * dashboard never draws a line through data it does not have.
 */
export function timelineSeries(quotes: readonly Quote[], outcomeId: string | null): TimelinePoint[] {
  const points: TimelinePoint[] = [];
  for (const quote of quotes) {
    if (outcomeId !== null && outcomeId !== "" && quote.outcome_id !== outcomeId) {
      continue;
    }
    const at = quote.as_of ?? quote.observed_at;
    const odds = toNumber(quote.best_decimal_odds ?? quote.decimal_odds);
    if (at === null || odds === null) {
      continue;
    }
    points.push({ at, odds });
  }
  return points.sort((left, right) => left.at.localeCompare(right.at));
}

export interface SnapshotMeta {
  method: string | null;
  overround: string | null;
  fairProbability: string | null;
  impliedProbability: string | null;
  asOf: string | null;
  sourceId: string | null;
  quoteCount: number | null;
}

/** De-vig metadata from the most recent snapshot the API returned. */
export function latestSnapshotMeta(quotes: readonly Quote[]): SnapshotMeta | null {
  let best: Quote | null = null;
  for (const quote of quotes) {
    if (quote.de_vig_method === null && quote.fair_probability === null) {
      continue;
    }
    if (best === null) {
      best = quote;
      continue;
    }
    const bestAt = best.as_of ?? best.observed_at;
    const candidateAt = quote.as_of ?? quote.observed_at;
    if (candidateAt > bestAt) {
      best = quote;
    }
  }
  if (best === null) {
    return null;
  }
  return {
    method: best.de_vig_method ?? null,
    overround: best.overround ?? null,
    fairProbability: best.fair_probability ?? null,
    impliedProbability: best.implied_probability ?? null,
    asOf: best.as_of ?? best.observed_at,
    sourceId: best.best_source_id ?? best.source_id,
    quoteCount: best.quote_count ?? null,
  };
}

/* -------------------------------------------------------------------------- *
 * Predictions and model cards
 * -------------------------------------------------------------------------- */

export function predictionForOutcome(
  predictions: readonly Prediction[],
  marketType: string | null,
  outcomeKind: string | null,
): Prediction | null {
  if (marketType === null || outcomeKind === null || predictions.length === 0) {
    return null;
  }
  const exact = predictions.find(
    (prediction) =>
      prediction.market_type === marketType && prediction.outcome_kind === outcomeKind,
  );
  return exact ?? null;
}

/** Turns the `explanation` JSON column into readable lines (never invented). */
export function predictionExplanationLines(prediction: Prediction): string[] {
  const lines: string[] = [];
  const explanation = prediction.explanation;
  if (prediction.abstained) {
    lines.push(
      prediction.abstain_reason === null
        ? "The model abstained from this market."
        : `The model abstained from this market: ${prediction.abstain_reason}`,
    );
  }
  for (const key of ["summary", "notes", "drivers", "top_features", "reasons", "warnings"]) {
    const value = explanation[key];
    if (value === undefined) {
      continue;
    }
    if (typeof value === "string" && value !== "") {
      lines.push(value);
      continue;
    }
    if (Array.isArray(value)) {
      for (const entry of value) {
        lines.push(formatUnknown(entry));
      }
      continue;
    }
    if (isRecord(value)) {
      for (const [nestedKey, nestedValue] of Object.entries(value)) {
        lines.push(`${humaniseKey(nestedKey)}: ${formatUnknown(nestedValue)}`);
      }
    }
  }
  if (lines.length === 0) {
    for (const [key, value] of Object.entries(explanation)) {
      if (isRecord(value) || Array.isArray(value)) {
        continue;
      }
      lines.push(`${humaniseKey(key)}: ${formatUnknown(value)}`);
    }
  }
  return lines;
}

export interface MetricRow {
  key: string;
  label: string;
  display: string;
}

/** Metrics then params as display rows (model card screen). */
export function modelCardRows(card: ModelCard): { metrics: MetricRow[]; params: MetricRow[] } {
  const toRows = (source: Record<string, unknown>): MetricRow[] =>
    Object.keys(source)
      .sort((left, right) => left.localeCompare(right))
      .map((key) => ({
        key,
        label: humaniseKey(key),
        display: formatUnknown(source[key]),
      }));
  return { metrics: toRows(card.metrics), params: toRows(card.params) };
}

/* -------------------------------------------------------------------------- *
 * Resolver
 * -------------------------------------------------------------------------- */

export function resolverProviderLabel(row: ResolverReview): string {
  return (
    orientationLabel(row.provider_home_name, row.provider_away_name) ??
    `provider event ${row.provider_event_id}`
  );
}

export function resolverCanonicalLabel(row: ResolverReview): string {
  return (
    orientationLabel(row.canonical_home_name, row.canonical_away_name) ??
    `canonical event ${row.canonical_event_id}`
  );
}

/** Only rows the resolver explicitly parked need an analyst decision. */
export function resolverNeedsDecision(row: ResolverReview): boolean {
  return row.review_status === "review_required";
}