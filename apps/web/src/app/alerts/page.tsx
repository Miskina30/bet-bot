"use client";

/**
 * Alert inbox — evidence snapshots pinned to the moment a rule fired.
 *
 * Acknowledge is analyst-only and goes through a same-origin Next.js API route
 * (never directly to the backend), so the browser never holds a key with write
 * privileges.
 */

import { useState } from "react";

import {
  EmptyBlock,
  ErrorBlock,
  LoadingBlock,
  PartialBanner,
  SectionPanel,
} from "@/components/StateBlocks";
import { pageIsPartial } from "@/lib/api";
import { formatUtcTimestamp } from "@/lib/format";
import { useAcknowledgeAlert, useAlerts } from "@/lib/queries";
import type { Alert } from "@/lib/schemas";

const ALERTS_URL = "/v1/alerts";

export default function AlertsPage() {
  const query = useAlerts({ limit: 100 });
  const acknowledge = useAcknowledgeAlert();
  const [ackError, setAckError] = useState<string | null>(null);

  const refetch = () => {
    void query.refetch();
  };

  if (query.isPending) {
    return <LoadingBlock label="Loading alerts" />;
  }
  if (query.isError || query.data === undefined) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message: query.error instanceof Error ? query.error.message : "Unknown error",
          detail: null,
          url: ALERTS_URL,
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
  const openCount = rows.filter((row) => row.status === "open").length;

  return (
    <div className="space-y-4">
      <SectionPanel
        title="Alert inbox"
        subtitle={`${rows.length} total · ${openCount} open · generated ${formatUtcTimestamp(page.generated_at)}`}
        actions={
          <button type="button" className="btn" onClick={refetch}>
            Refresh
          </button>
        }
      >
        <div className="space-y-3">
          {pageIsPartial(page) ? <PartialBanner failedSources={page.sources_failed} /> : null}
          {ackError !== null ? (
            <div className="panel border-danger bg-danger-soft">
              <div className="panel-body text-2xs text-danger">{ackError}</div>
            </div>
          ) : null}

          {rows.length === 0 ? (
            <EmptyBlock
              title="No alerts raised yet."
              hint="Alerts fire when a rule matches an opportunity that clears friction and meets the minimum edge. An empty inbox means no rule has fired yet."
            />
          ) : (
            <div className="space-y-2">
              {rows.map((alert) => (
                <AlertCard
                  key={alert.id}
                  alert={alert}
                  onAcknowledge={async () => {
                    setAckError(null);
                    const result = await acknowledge.mutateAsync({
                      alertId: alert.id,
                      acknowledgedBy: "dashboard-analyst",
                    });
                    if (!result.ok) {
                      setAckError(
                        `Failed to acknowledge: ${result.error.message} (HTTP ${result.error.status ?? "?"})`,
                      );
                    }
                  }}
                  ackPending={acknowledge.isPending}
                />
              ))}
            </div>
          )}
        </div>
      </SectionPanel>

      <SectionPanel
        title="How alerts fire"
        subtitle="The pipeline evaluates enabled rules against detected opportunities on every ingest pass"
      >
        <ol className="list-decimal space-y-1 pl-5 text-2xs text-ink-muted">
          <li>An opportunity is detected (arbitrage or model-vs-market value).</li>
          <li>Every enabled AlertRule is checked: type match, market-type match, min edge, min confidence, quote age.</li>
          <li>Matching rules produce an Alert row with a deduped key and the full evidence dict.</li>
          <li>The alert appears here and on the SSE stream for live push.</li>
          <li>An analyst acknowledges it (analyst role) or lets it expire.</li>
        </ol>
      </SectionPanel>
    </div>
  );
}

function AlertCard({
  alert,
  onAcknowledge,
  ackPending,
}: {
  alert: Alert;
  onAcknowledge: () => Promise<void>;
  ackPending: boolean;
}) {
  const isOpen = alert.status === "open";
  const severityTone =
    alert.severity === "actionable" ? "chip-danger" : alert.severity === "watch" ? "chip-caution" : "chip";

  const evidenceKeys = Object.keys(alert.evidence ?? {}).sort();

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`chip ${severityTone}`}>{alert.severity}</span>
          <span className="chip">{alert.status}</span>
          <span className="chip">{alert.rule}</span>
          {alert.is_synthetic ? <span className="chip">synthetic</span> : null}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-2xs text-ink-muted">{formatUtcTimestamp(alert.raised_at)}</span>
          {isOpen ? (
            <button
              type="button"
              className="btn"
              disabled={ackPending}
              onClick={() => void onAcknowledge()}
            >
              {ackPending ? "Acknowledging…" : "Acknowledge"}
            </button>
          ) : null}
        </div>
      </div>
      <div className="panel-body space-y-2">
        <p className="text-ink">{alert.message}</p>
        {evidenceKeys.length > 0 ? (
          <div>
            <p className="text-2xs uppercase tracking-wide text-ink-subtle">Evidence snapshot</p>
            <dl className="mt-1 grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2">
              {evidenceKeys.map((key) => {
                const value = (alert.evidence as Record<string, unknown>)[key];
                const display =
                  typeof value === "string" || typeof value === "number" || typeof value === "boolean"
                    ? String(value)
                    : JSON.stringify(value, null, 2);
                return (
                  <div key={key} className="flex items-baseline justify-between gap-3 border-b border-line/40 py-0.5">
                    <dt className="mono text-ink-subtle">{key}</dt>
                    <dd className="text-right text-2xs text-ink">{display}</dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ) : null}
      </div>
    </div>
  );
}

