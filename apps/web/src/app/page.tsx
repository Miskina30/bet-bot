"use client";

/**
 * Opportunity board - the primary analyst screen.
 *
 * Every row states *why* it is or is not actionable: net edge after friction,
 * confidence with its band, the best legs with their venues and ages, liquidity,
 * and the blockers that stopped a near-miss becoming actionable. Blocked rows are
 * shown, not hidden, because a near-miss with a reason is the most useful thing
 * this screen can tell an analyst.
 *
 * Live updates arrive over SSE; the table also polls, so a dropped stream
 * degrades to "slightly older data" rather than an empty screen.
 */

import { useCallback, useMemo, useState } from "react";

import {
  BulletList,
  EmptyBlock,
  ErrorBlock,
  LoadingBlock,
  PartialBanner,
  SectionPanel,
  StaleBanner,
} from "@/components/StateBlocks";
import { pageIsPartial, type ApiError } from "@/lib/api";
import {
  confidenceBand,
  isOpportunityExpired,
  opportunityBlockers,
  opportunityEventLabel,
  opportunityFreshness,
  opportunityLiquidity,
  opportunityMarketLabel,
  opportunityQuoteAgeSeconds,
  toLegViews,
} from "@/lib/derive";
import {
  formatBps,
  formatDuration,
  formatRatioPercent,
  formatUnknown,
} from "@/lib/format";
import { useOpportunities } from "@/lib/queries";
import type { Opportunity } from "@/lib/schemas";
import { useOpportunitiesStream } from "@/lib/use-sse";

type ActionableFilter = "all" | "actionable" | "blocked";

const BOARD_URL = "/v1/opportunities";

function boardError(error: unknown): ApiError {
  return {
    kind: "unknown",
    status: null,
    message: error instanceof Error ? error.message : "Unknown error",
    detail: null,
    url: BOARD_URL,
    method: "GET",
    retriable: true,
  };
}

export default function OpportunityBoardPage() {
  const [filter, setFilter] = useState<ActionableFilter>("all");
  const [minEdge, setMinEdge] = useState<string>("");

  const params = useMemo(() => {
    const parsed = Number.parseInt(minEdge, 10);
    return {
      actionable: filter === "all" ? null : filter === "actionable",
      minNetEdgeBps: Number.isFinite(parsed) ? parsed : null,
      limit: 100,
    };
  }, [filter, minEdge]);

  const query = useOpportunities(params);
  const stream = useOpportunitiesStream({ enabled: true, maxItems: 25 });
  const refetch = useCallback(() => {
    void query.refetch();
  }, [query]);

  if (query.isPending) {
    return <LoadingBlock label="Loading the opportunity board" />;
  }
  if (query.isError || query.data === undefined) {
    return <ErrorBlock error={boardError(query.error)} onRetry={refetch} />;
  }
  const result = query.data;
  if (!result.ok) {
    return <ErrorBlock error={result.error} onRetry={refetch} />;
  }
  const page = result.data;
  const rows = page.items;

  return (
    <div className="space-y-4">
      <SectionPanel
        title="Opportunity board"
        subtitle="Arbitrage and model-vs-market value, with the friction that decides whether it is actionable."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-2xs text-ink-muted">
              Show
              <select
                className="rounded border border-line bg-surface-raised px-2 py-1 text-2xs"
                value={filter}
                onChange={(event) => setFilter(event.target.value as ActionableFilter)}
              >
                <option value="all">everything</option>
                <option value="actionable">actionable only</option>
                <option value="blocked">blocked only</option>
              </select>
            </label>
            <label className="flex items-center gap-1 text-2xs text-ink-muted">
              Min net edge (bps)
              <input
                className="w-20 rounded border border-line bg-surface-raised px-2 py-1 text-2xs"
                inputMode="numeric"
                value={minEdge}
                placeholder="0"
                onChange={(event) => setMinEdge(event.target.value.replace(/[^0-9-]/g, ""))}
              />
            </label>
            <button type="button" className="btn" onClick={refetch}>
              Refresh
            </button>
          </div>
        }
      >
        <div className="space-y-3">
          {page.stale || stream.stale ? (
            <StaleBanner
              sinceIso={page.generated_at ?? stream.lastEventAt}
              ageLabel="see the Sources screen for the last successful refresh"
            />
          ) : null}
          {pageIsPartial(page) ? <PartialBanner failedSources={page.sources_failed} /> : null}
          {page.fixture_mode ? (
            <div className="panel border-accent bg-accent-soft">
              <div className="panel-body text-2xs text-accent">
                <strong>Synthetic fixtures.</strong> This deployment has no live provider
                credentials, so every row below is labelled synthetic demo data and must not be
                read as a real market price.
              </div>
            </div>
          ) : null}
          {stream.lastError !== null ? (
            <div className="panel border-caution bg-caution-soft">
              <div className="panel-body text-2xs text-caution">{stream.lastError}</div>
            </div>
          ) : null}

          {rows.length === 0 ? (
            <EmptyBlock
              title="No opportunities match these filters."
              hint="An empty board is a real answer: no cross-venue arbitrage cleared friction, and no model disagreed with the market by enough to matter. Check the Sources screen before concluding the market is quiet."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1100px] border-collapse text-xs">
                <thead>
                  <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-ink-subtle">
                    <th className="px-2 py-2">Type</th>
                    <th className="px-2 py-2">Event</th>
                    <th className="px-2 py-2">Market</th>
                    <th className="px-2 py-2 text-right">Net edge</th>
                    <th className="px-2 py-2 text-right">Gross</th>
                    <th className="px-2 py-2 text-right">Confidence</th>
                    <th className="px-2 py-2">Best legs</th>
                    <th className="px-2 py-2 text-right">Age</th>
                    <th className="px-2 py-2 text-right">Liquidity</th>
                    <th className="px-2 py-2">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((opportunity) => (
                    <OpportunityRow key={opportunity.id} opportunity={opportunity} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </SectionPanel>

      <SectionPanel
        title="Live stream"
        subtitle={`Server-Sent Events · ${stream.status}${stream.attempts > 0 ? ` · reconnect attempts: ${stream.attempts}` : ""}`}
        actions={
          <button type="button" className="btn" onClick={stream.reconnect}>
            Reconnect
          </button>
        }
      >
        {stream.items.length === 0 ? (
          <EmptyBlock
            title="No live frames yet."
            hint="The stream pushes newly detected opportunities. A quiet stream is not proof of a quiet market - the table above is the record."
          />
        ) : (
          <ul className="space-y-1 text-2xs">
            {stream.items.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-baseline gap-2">
                <span className="chip chip-accent">{entry.opportunity.opportunity_type}</span>
                <a className="underline hover:no-underline" href={`/opportunities/${entry.id}`}>
                  {opportunityEventLabel(entry.opportunity)}
                </a>
                <span className="text-ink-muted">net {formatBps(entry.opportunity.net_edge_bps)}</span>
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>
    </div>
  );
}

/**
 * One board row. `is_actionable` is shown but never trusted blindly: the blockers
 * list is recomputed from the row's own legs and timestamps, so a row can only
 * look actionable if its evidence still says so at render time.
 */
function OpportunityRow({ opportunity }: { opportunity: Opportunity }) {
  const nowMs = Date.now();
  const expired = isOpportunityExpired(opportunity, nowMs);
  const blockers = opportunityBlockers(opportunity, nowMs);
  const legs = toLegViews(opportunity.best_legs, nowMs);
  const band = confidenceBand(opportunity.confidence);
  const liquidity = opportunityLiquidity(opportunity);
  const ageSeconds = opportunityQuoteAgeSeconds(opportunity, nowMs);
  const freshness = opportunityFreshness(opportunity, nowMs);
  const reasons = opportunitiesReasons(opportunity, blockers);

  return (
    <tr className="border-b border-line/60 align-top">
      <td className="px-2 py-2">
        <span className={opportunity.is_actionable ? "chip chip-positive" : "chip chip-caution"}>
          {opportunity.opportunity_type}
        </span>
        {opportunity.is_synthetic ? <span className="chip ml-1">synthetic</span> : null}
      </td>
      <td className="px-2 py-2">
        <a className="underline hover:no-underline" href={`/opportunities/${opportunity.id}`}>
          {opportunityEventLabel(opportunity)}
        </a>
      </td>
      <td className="px-2 py-2">{opportunityMarketLabel(opportunity)}</td>
      <td className="px-2 py-2 text-right">{formatBps(opportunity.net_edge_bps)}</td>
      <td className="px-2 py-2 text-right text-ink-muted">{formatBps(opportunity.gross_edge_bps)}</td>
      <td className="px-2 py-2 text-right">
        <span className={band.tone === "positive" ? "chip chip-positive" : "chip"}>
          {formatRatioPercent(opportunity.confidence, 0)} · {band.label}
        </span>
      </td>
      <td className="px-2 py-2">
        {legs.length === 0 ? (
          <span className="text-ink-muted">no legs published</span>
        ) : (
          <ul className="space-y-0.5">
            {legs.map((leg) => (
              <li key={leg.index} className="flex flex-wrap items-baseline gap-1">
                <span className="chip">{leg.sourceName}</span>
                <span>{leg.outcomeLabel}</span>
                <span className="mono">{leg.decimalOdds ?? "n/a"}</span>
                <span className="text-ink-muted">
                  {leg.quoteAgeSeconds === null
                    ? "age unknown"
                    : `${formatDuration(leg.quoteAgeSeconds)} old`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </td>
      <td className="px-2 py-2 text-right">
        <span className={freshness === "stale" ? "chip chip-danger" : "chip"}>
          {ageSeconds === null ? "unknown" : formatDuration(ageSeconds)}
        </span>
      </td>
      <td className="px-2 py-2 text-right">
        {liquidity === null ? (
          <span className="text-ink-muted">not reported</span>
        ) : (
          <span className="mono">{formatUnknown(liquidity)}</span>
        )}
      </td>
      <td className="px-2 py-2">
        {expired ? <span className="chip chip-danger">expired</span> : null}
        {reasons.length > 0 ? (
          <BulletList items={reasons} tone={blockers.length > 0 ? "caution" : "neutral"} />
        ) : (
          <span className="text-ink-muted">no stated reason</span>
        )}
      </td>
    </tr>
  );
}

/** Blockers first (they are why an analyst cares), then the engine's reasons. */
function opportunitiesReasons(opportunity: Opportunity, blockers: readonly string[]): string[] {
  if (blockers.length > 0) {
    return [...blockers, ...opportunity.reasons].slice(0, 4);
  }
  return opportunity.reasons.slice(0, 3);
}


