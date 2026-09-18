"use client";

/**
 * Source health screen.
 *
 * This is the screen that decides whether any other screen can be trusted: it
 * shows each configured source's mode (live or fixture), last check, latency,
 * quota, parser drift and consecutive failures, plus the recorded terms-review
 * state from the policy registry. A source failing here is the first explanation
 * for a missing leg on the board.
 */

import {
  EmptyBlock,
  ErrorBlock,
  LoadingBlock,
  PartialBanner,
  SectionPanel,
} from "@/components/StateBlocks";
import { pageIsPartial } from "@/lib/api";
import { formatAge, formatInteger, formatUtcTimestamp, humaniseEnumValue } from "@/lib/format";
import { useSourcesHealth } from "@/lib/queries";
import {
  degradedSources,
  isFixtureHealth,
  liveSourceCount,
  sourceDisplayName,
  sourceModeLabel,
} from "@/lib/sources";

export default function SourcesPage() {
  const query = useSourcesHealth({ limit: 100 });
  const refetch = () => {
    void query.refetch();
  };

  if (query.isPending) {
    return <LoadingBlock label="Loading source health" />;
  }
  if (query.isError || query.data === undefined) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message: query.error instanceof Error ? query.error.message : "Unknown error",
          detail: null,
          url: "/v1/sources/health",
          method: "GET",
          retriable: true,
        }}
        onRetry={refetch}
      />
    );
  }
  const result = query.data;
  if (!result.ok) {
    return <ErrorBlock error={result.error} onRetry={refetch} />;
  }

  const page = result.data;
  const rows = page.items;
  const failures = degradedSources(rows);
  const live = liveSourceCount(rows);

  return (
    <div className="space-y-4">
      <SectionPanel
        title="Source health"
        subtitle={`${formatInteger(rows.length)} configured · ${formatInteger(live)} live · generated ${formatUtcTimestamp(page.generated_at)}`}
        actions={
          <button type="button" className="btn" onClick={refetch}>
            Re-check now
          </button>
        }
      >
        <div className="space-y-3">
          {pageIsPartial(page) ? <PartialBanner failedSources={page.sources_failed} /> : null}
          {failures.length > 0 ? (
            <div className="panel border-danger bg-danger-soft">
              <div className="panel-body text-2xs text-danger">
                <strong>{formatInteger(failures.length)} degraded source(s).</strong> Any board
                row depending on them is incomplete — treat a missing opportunity as unknown,
                not as evidence that none exists.
              </div>
            </div>
          ) : null}
          {page.fixture_mode ? (
            <div className="panel border-accent bg-accent-soft">
              <div className="panel-body text-2xs text-accent">
                <strong>Synthetic fixtures.</strong> No live provider credentials are
                configured, so every source below runs in labelled fixture mode.
              </div>
            </div>
          ) : null}
          {rows.length === 0 ? (
            <EmptyBlock
              title="No sources are configured."
              hint="Add entries to config/source_policies.yaml. An empty registry is a configuration error, not a healthy state."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] border-collapse text-xs">
                <thead>
                  <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-ink-subtle">
                    <th className="px-2 py-2">Source</th>
                    <th className="px-2 py-2">Mode</th>
                    <th className="px-2 py-2">Health</th>
                    <th className="px-2 py-2 text-right">Latency</th>
                    <th className="px-2 py-2 text-right">Quota</th>
                    <th className="px-2 py-2 text-right">Failures</th>
                    <th className="px-2 py-2 text-right">Drift</th>
                    <th className="px-2 py-2">Last checked</th>
                    <th className="px-2 py-2">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${row.source_id}-${row.checked_at}`} className="border-b border-line/60 align-top">
                      <td className="px-2 py-2">
                        <div className="flex flex-col gap-0.5">
                          <span className="text-ink">{sourceDisplayName(row.source_id)}</span>
                          <span className="mono text-ink-subtle">{row.source_id}</span>
                          {isFixtureHealth(row) ? <span className="chip">fixture</span> : null}
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <span className="chip">{sourceModeLabel(row.mode)}</span>
                      </td>
                      <td className="px-2 py-2">
                        <span className={row.ok ? "chip chip-positive" : "chip chip-danger"}>
                          {row.ok ? "ok" : "failing"}
                        </span>
                      </td>
                      <td className="px-2 py-2 text-right">
                        {row.latency_ms === null || row.latency_ms === undefined ? "n/a" : `${formatInteger(row.latency_ms)} ms`}
                      </td>
                      <td className="px-2 py-2 text-right">
                        {row.quota_limit === null || row.quota_limit === undefined
                          ? "not reported"
                          : `${formatInteger(row.quota_used ?? 0)} / ${formatInteger(row.quota_limit)}`}
                      </td>
                      <td className="px-2 py-2 text-right">{formatInteger(row.consecutive_failures ?? 0)}</td>
                      <td className="px-2 py-2 text-right">{formatInteger(row.parser_drift_count ?? 0)}</td>
                      <td className="px-2 py-2">
                        <div className="flex flex-col gap-0.5">
                          <span>{formatUtcTimestamp(row.checked_at)}</span>
                          <span className="text-2xs text-ink-muted">{formatAge(row.age_seconds ?? null)}</span>
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex flex-col gap-1">
                          <span>{row.message ?? "no detail reported"}</span>
                          {row.tier !== undefined && row.tier !== null ? (
                            <span className="chip">tier {humaniseEnumValue(row.tier)}</span>
                          ) : null}
                          {row.terms_reviewed_by === null || row.terms_reviewed_by === undefined ? (
                            <span className="chip chip-caution">terms review not recorded</span>
                          ) : (
                            <span className="chip chip-positive">reviewed by {row.terms_reviewed_by}</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </SectionPanel>

      <SectionPanel
        title="When a source is degraded"
        subtitle="One-paragraph runbook; the full version lives in docs/runbook.md"
      >
        <ol className="list-decimal space-y-1 pl-5 text-2xs text-ink-muted">
          <li>
            Confirm the credential and quota state against the provider dashboard. Never retry
            past a 429 — back off instead.
          </li>
          <li>
            Check parser drift. A non-zero count means the vendor changed a field; the raw
            payload is archived in the raw store for inspection, so nothing needs to be guessed.
          </li>
          <li>
            If only fixtures are available, keep the board running in fixture mode and label it.
            Synthetic data must never be presented as live market data.
          </li>
          <li>
            Record the outcome in the audit log so the next analyst does not repeat the
            diagnosis.
          </li>
        </ol>
      </SectionPanel>
    </div>
  );
}

