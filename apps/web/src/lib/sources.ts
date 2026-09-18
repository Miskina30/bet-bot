/**
 * Source registry: a read-only mirror of `config/source_policies.yaml`.
 *
 * Why it exists in the web app: every number the dashboard renders must be
 * attributable to a source (brief, SAFETY #5). The API is authoritative for
 * health and quota; this file only supplies *labels and policy context* so a
 * source chip can say "Crocobet - manual CSV only" even before the health
 * endpoint answers. If the API also sends `display_name`/`tier`, the API value
 * wins.
 *
 * `SOURCE_REGISTRY` must be kept in step with config/source_policies.yaml; the
 * source policy gate in CI is authoritative for `automation_allowed`.
 */

export interface SourceDescriptor {
  sourceId: string;
  displayName: string;
  tier: string;
  automationScope: string;
  dataClasses: readonly string[];
  licence: string;
}

export const SOURCE_REGISTRY: readonly SourceDescriptor[] = [
  {
    sourceId: "api_football",
    displayName: "API-Football (api-sports.io)",
    tier: "free",
    automationScope: "official api only",
    dataClasses: ["fixtures", "results", "lineups", "injuries", "in-play prices"],
    licence: "Vendor ToS - personal/internal use; raw redistribution prohibited",
  },
  {
    sourceId: "football_data_org",
    displayName: "football-data.org",
    tier: "free",
    automationScope: "official api only",
    dataClasses: ["competitions", "fixtures", "results", "standings"],
    licence: "Free tier, non-commercial; attribution required",
  },
  {
    sourceId: "polymarket_gamma",
    displayName: "Polymarket (Gamma API)",
    tier: "public read",
    automationScope: "documented public reads",
    dataClasses: ["event discovery", "markets", "prices"],
    licence: "Public read endpoints; treated as one venue, never ground truth",
  },
  {
    sourceId: "polymarket_clob",
    displayName: "Polymarket (CLOB + WebSocket)",
    tier: "public read",
    automationScope: "documented public reads",
    dataClasses: ["order book", "market price history"],
    licence: "Public read endpoints; read-only, no order placement",
  },
  {
    sourceId: "football_data_uk",
    displayName: "Football-Data.co.uk (historical CSV)",
    tier: "public",
    automationScope: "bulk static download",
    dataClasses: ["historical results", "closing odds"],
    licence: "Public CSV downloads; check site notes for attribution",
  },
  {
    sourceId: "crocobet",
    displayName: "Crocobet",
    tier: "manual",
    automationScope: "manual CSV only",
    dataClasses: ["odds"],
    licence: "No public API - operator-supplied exports only; web automation disabled",
  },
  {
    sourceId: "fixture",
    displayName: "Labelled frozen fixtures (no network)",
    tier: "synthetic",
    automationScope: "local fixtures",
    dataClasses: ["all"],
    licence: "Project-owned test fixtures - never presented as live",
  },
];

export const SOURCE_REGISTRY_BY_ID: Readonly<Record<string, SourceDescriptor>> =
  Object.fromEntries(SOURCE_REGISTRY.map((entry) => [entry.sourceId, entry]));

/** The synthetic source id: anything from it is labelled, never presented live. */
export const FIXTURE_SOURCE_ID = "fixture";

export function sourceDescriptor(sourceId: string): SourceDescriptor | undefined {
  return SOURCE_REGISTRY_BY_ID[sourceId];
}

/** Prefer the API's `display_name`; fall back to the local registry, then the id. */
export function sourceDisplayName(
  sourceId: string | null | undefined,
  providedName?: string | null,
): string {
  if (providedName !== null && providedName !== undefined && providedName !== "") {
    return providedName;
  }
  if (sourceId === null || sourceId === undefined || sourceId === "") {
    return "unknown source";
  }
  return sourceDescriptor(sourceId)?.displayName ?? sourceId;
}

/** True when a health row describes synthetic fixtures rather than live data. */
export function isFixtureHealth(row: {
  source_id: string;
  mode?: string | null;
  is_synthetic?: boolean | null;
  tier?: string | null;
}): boolean {
  if (row.source_id === FIXTURE_SOURCE_ID) {
    return true;
  }
  if (row.mode !== null && row.mode !== undefined && row.mode.toLowerCase() === "fixture") {
    return true;
  }
  if (row.tier === "synthetic") {
    return true;
  }
  return row.is_synthetic === true;
}

/**
 * Fixture mode for the whole deployment: reported by the API when it says so,
 * otherwise derived (any source in fixture/synthetic mode, or every source
 * synthetic). Derived detection is deliberately conservative - a false positive
 * only adds a warning banner.
 */
export function isFixtureMode(
  rows: readonly {
    source_id: string;
    mode?: string | null;
    is_synthetic?: boolean | null;
    tier?: string | null;
  }[],
  reported?: boolean | null,
): boolean {
  if (reported === true) {
    return true;
  }
  return rows.some((row) => isFixtureHealth(row));
}

/** Live (non-fixture) sources, for the fixtures-vs-live banner. */
export function liveSourceCount(rows: readonly { source_id: string; mode?: string | null; is_synthetic?: boolean | null; tier?: string | null }[]): number {
  return rows.filter((row) => !isFixtureHealth(row)).length;
}

/** Health rows that are failing or degraded - drives the partial-source state. */
export function degradedSources<T extends { ok: boolean; consecutive_failures?: number }>(
  rows: readonly T[],
): T[] {
  return rows.filter((row) => !row.ok || (row.consecutive_failures ?? 0) > 0);
}

/** Human label for a health row's mode. */
export function sourceModeLabel(mode: string | null | undefined): string {
  if (mode === null || mode === undefined || mode === "") {
    return "unknown mode";
  }
  const normalised = mode.toLowerCase();
  if (normalised === "live") {
    return "live";
  }
  if (normalised === "fixture" || normalised === "fixtures") {
    return "synthetic fixtures";
  }
  if (normalised === "manual") {
    return "manual import";
  }
  if (normalised === "disabled") {
    return "disabled";
  }
  return normalised;
}