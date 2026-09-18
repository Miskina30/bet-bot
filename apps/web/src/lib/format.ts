/**
 * Display formatting for the Academic Edge dashboard.
 *
 * Rules this module enforces so no screen has to remember them:
 *  * Every timestamp is rendered in UTC and suffixed with `Z`. date-fns `format`
 *    would silently use the *browser's* timezone, so UTC field extraction is done
 *    explicitly here (date-fns is used for parsing).
 *  * Every number that could be absent renders as an explicit placeholder - the
 *    UI never invents, rounds away or back-fills a missing value.
 *  * No string here claims a profit, an outcome or a guarantee. Edge is always
 *    described as a modelled, friction-adjusted estimate in bps.
 */

import { parseISO } from "date-fns";

/** Placeholder for a value the API did not report. */
export const DASH = "not reported";

/* -------------------------------------------------------------------------- *
 * Time
 * -------------------------------------------------------------------------- */

/**
 * Parse an API timestamp into a Date. The backend guarantees UTC; a value with no
 * zone designator is therefore treated as UTC rather than as browser-local time.
 */
export function toUtcDate(value: string | null | undefined): Date | null {
  if (value === null || value === undefined) {
    return null;
  }
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  const hasZone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const candidate = hasZone ? trimmed : `${trimmed}Z`;
  const parsed = parseISO(candidate);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** `2026-09-15T12:03:44Z` -> `2026-09-15 12:03:44Z` (UTC, explicit). */
export function formatUtcTimestamp(value: string | null | undefined): string {
  const date = toUtcDate(value);
  if (date === null) {
    return DASH;
  }
  const ymd = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
  const hms = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
  return `${ymd} ${hms}Z`;
}

/** Date only, UTC: `2026-09-15`. */
export function formatUtcDate(value: string | null | undefined): string {
  const date = toUtcDate(value);
  if (date === null) {
    return DASH;
  }
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

export function utcNowIso(): string {
  return new Date().toISOString();
}

/** Age of an observation in seconds (negative when the API clock leads ours). */
export function ageInSeconds(
  observedAt: string | null | undefined,
  nowMs: number = Date.now(),
): number | null {
  const date = toUtcDate(observedAt);
  if (date === null) {
    return null;
  }
  return (nowMs - date.getTime()) / 1000;
}

/** `12s`, `4m 05s`, `2h 07m`, `3d 04h`. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) {
    return `${total}s`;
  }
  if (total < 3600) {
    return `${Math.floor(total / 60)}m ${pad(total % 60)}s`;
  }
  if (total < 86400) {
    return `${Math.floor(total / 3600)}h ${pad(Math.floor((total % 3600) / 60))}m`;
  }
  return `${Math.floor(total / 86400)}d ${pad(Math.floor((total % 86400) / 3600))}h`;
}

/** Human-readable age with clock skew called out instead of hidden. */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return DASH;
  }
  if (seconds < -5) {
    return `future-dated (+${formatDuration(Math.abs(seconds))})`;
  }
  return formatDuration(seconds);
}

/** `3m 07s ago` / placeholder - for provenance lines. */
export function formatAgeAgo(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return DASH;
  }
  if (seconds < -5) {
    return `future-dated (+${formatDuration(Math.abs(seconds))})`;
  }
  return `${formatDuration(seconds)} ago`;
}

/* -------------------------------------------------------------------------- *
 * Numbers
 * -------------------------------------------------------------------------- */

export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Decimal odds, three places (the precision used across the domain model). */
export function formatDecimalOdds(value: string | number | null | undefined): string {
  const parsed = toNumber(value);
  return parsed === null ? DASH : parsed.toFixed(3);
}

/**
 * A bps figure. `+` means the modelled edge survives the modelled friction, `-`
 * means it does not. It is never labelled as a profit.
 */
export function formatBps(
  value: number | string | null | undefined,
  options: { signed?: boolean } = {},
): string {
  const parsed = toNumber(value);
  if (parsed === null) {
    return DASH;
  }
  const { signed = true } = options;
  const rounded = Math.round(parsed);
  const magnitude = Math.abs(rounded);
  if (!signed) {
    return `${magnitude} bps`;
  }
  if (rounded > 0) {
    return `+${magnitude} bps`;
  }
  if (rounded < 0) {
    return `-${magnitude} bps`;
  }
  return "0 bps";
}

/** A probability expressed as a 0-1 decimal -> `53.32%`. */
export function formatProbability(value: string | number | null | undefined, digits = 2): string {
  const parsed = toNumber(value);
  return parsed === null ? DASH : `${(parsed * 100).toFixed(digits)}%`;
}

/** A 0-1 ratio (confidence, match score as a ratio) -> `82.0%`. */
export function formatRatioPercent(value: number | string | null | undefined, digits = 1): string {
  const parsed = toNumber(value);
  return parsed === null ? DASH : `${(parsed * 100).toFixed(digits)}%`;
}

/** Money with an explicit currency; never presented as a realised profit. */
export function formatMoney(
  value: string | number | null | undefined,
  currency: string | null | undefined,
): string {
  const parsed = toNumber(value);
  if (parsed === null) {
    return DASH;
  }
  const code = (currency ?? "").toUpperCase();
  if (/^[A-Z]{3}$/.test(code)) {
    try {
      return new Intl.NumberFormat("en-GB", {
        style: "currency",
        currency: code,
        maximumFractionDigits: 2,
      }).format(parsed);
    } catch {
      /* fall through to the plain rendering below */
    }
  }
  return `${parsed.toFixed(2)}${code === "" ? "" : ` ${code}`}`;
}

/** Resolver match score, four places (thresholds are 0.940 / 0.985). */
export function formatScore(value: number | null | undefined): string {
  const parsed = toNumber(value);
  return parsed === null ? DASH : parsed.toFixed(4);
}

export function formatInteger(value: number | null | undefined): string {
  const parsed = toNumber(value);
  return parsed === null ? DASH : String(Math.round(parsed));
}

/* -------------------------------------------------------------------------- *
 * Labels
 * -------------------------------------------------------------------------- */

const ACRONYMS = new Set([
  "api",
  "bps",
  "btts",
  "clv",
  "ece",
  "ev",
  "fx",
  "id",
  "pnl",
  "roi",
  "rps",
  "sse",
  "utc",
  "xg",
]);

function mapToken(token: string, index: number): string {
  const lower = token.toLowerCase();
  if (ACRONYMS.has(lower)) {
    return lower.toUpperCase();
  }
  return index === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
}

/** `net_edge_bps` -> `Net edge BPS`; used for JSON-column keys. */
export function humaniseKey(key: string): string {
  const spaced = key.replace(/_/g, " ").trim();
  if (spaced === "") {
    return key;
  }
  return spaced
    .split(" ")
    .map((token, index) => mapToken(token, index))
    .join(" ");
}

/** `ft_totals_2_5` -> `FT totals 2.5`; `positive_ev` -> `positive EV`. */
export function humaniseEnumValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return DASH;
  }
  const parts: string[] = [];
  for (const token of value.split("_")) {
    if (token === "") {
      continue;
    }
    if (/^\d+$/.test(token)) {
      const previous = parts[parts.length - 1];
      if (previous !== undefined && /^\d+$/.test(previous)) {
        parts[parts.length - 1] = `${previous}.${token}`;
        continue;
      }
      parts.push(token);
      continue;
    }
    if (token === "ft") {
      parts.push("FT");
      continue;
    }
    if (token === "btts") {
      parts.push("BTTS");
      continue;
    }
    if (/^\d+x\d+$/i.test(token)) {
      parts.push(token.toUpperCase());
      continue;
    }
    parts.push(mapToken(token, parts.length));
  }
  return parts.join(" ");
}

export function capitaliseFirst(value: string): string {
  return value === "" ? value : value.charAt(0).toUpperCase() + value.slice(1);
}

/* -------------------------------------------------------------------------- *
 * Arbitrary JSON values (evidence, friction, params, metrics)
 * -------------------------------------------------------------------------- */

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Renders an arbitrary JSON value without ever throwing. */
export function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) {
    return DASH;
  }
  if (typeof value === "string") {
    return value === "" ? DASH : value;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : DASH;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return "[]";
    }
    if (value.every((entry) => typeof entry === "string")) {
      return value.join(", ");
    }
    return JSON.stringify(value);
  }
  if (isRecord(value)) {
    const keys = Object.keys(value);
    return keys.length === 0 ? "{}" : JSON.stringify(value);
  }
  return String(value);
}

/** Joins a string list for a table cell, with an explicit overflow marker. */
export function summariseList(values: readonly string[], max = 2): string {
  if (values.length === 0) {
    return DASH;
  }
  if (values.length <= max) {
    return values.join("; ");
  }
  return `${values.slice(0, max).join("; ")} (+${values.length - max} more)`;
}