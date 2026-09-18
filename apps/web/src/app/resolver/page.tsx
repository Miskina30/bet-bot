"use client";

/**
 * Resolver review queue — the analyst screen for cross-provider event matching.
 *
 * Each row shows the candidate (provider) vs the canonical match with the
 * score, component breakdown, and evidence. Rows with
 * ``review_status === "review_required"`` need a decision; everything else is
 * read-only history. The decision action is analyst-only and goes through the
 * same-origin Next.js proxy.
 */

import { useState } from "react";

import {
  BulletList,
  EmptyBlock,
  ErrorBlock,
  LoadingBlock,
  SectionPanel,
} from "@/components/StateBlocks";
import { formatScore, formatUtcTimestamp } from "@/lib/format";
import {
  matchScoreBand,
  resolverCanonicalLabel,
  resolverNeedsDecision,
  resolverProviderLabel,
} from "@/lib/derive";
import { useResolveReview, useResolverReview } from "@/lib/queries";
import type { ResolverReview } from "@/lib/schemas";

export default function ResolverReviewPage() {
  const query = useResolverReview({ limit: 100 });
  const resolve = useResolveReview();
  const [actionError, setActionError] = useState<string | null>(null);

  const refetch = () => {
    void query.refetch();
  };

  if (query.isPending) {
    return <LoadingBlock label="Loading the resolver review queue" />;
  }
  if (query.isError || query.data === undefined) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message: query.error instanceof Error ? query.error.message : "Unknown error",
          detail: null,
          url: "/v1/resolver/review",
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

  const rows = result.data.items;
  const needsDecision = rows.filter((row) => resolverNeedsDecision(row));

  return (
    <div className="space-y-4">
      <SectionPanel
        title="Resolver review queue"
        subtitle={`${rows.length} resolution(s) · ${needsDecision.length} awaiting a decision`}
        actions={
          <button type="button" className="btn" onClick={refetch}>
            Refresh
          </button>
        }
      >
        <div className="space-y-3">
          {actionError !== null ? (
            <div className="panel border-danger bg-danger-soft">
              <div className="panel-body text-2xs text-danger">{actionError}</div>
            </div>
          ) : null}
          {rows.length === 0 ? (
            <EmptyBlock
              title="No provider events have been resolved yet."
              hint="Run the worker seed or ingest to populate the resolver. An empty queue is normal before the first ingest pass."
            />
          ) : (
            <div className="space-y-3">
              {rows.map((row) => (
                <ReviewCard
                  key={row.id}
                  row={row}
                  onDecide={async (action, note) => {
                    setActionError(null);
                    const result = await resolve.mutateAsync({
                      reviewId: row.id,
                      action,
                      note: note ?? null,
                    });
                    if (!result.ok) {
                      setActionError(
                        `Decision failed: ${result.error.message} (HTTP ${result.error.status ?? "?"})`,
                      );
                    }
                  }}
                  decisionPending={resolve.isPending}
                />
              ))}
            </div>
          )}
        </div>
      </SectionPanel>
    </div>
  );
}

function ReviewCard({
  row,
  onDecide,
  decisionPending,
}: {
  row: ResolverReview;
  onDecide: (action: "link" | "reject", note?: string) => Promise<void>;
  decisionPending: boolean;
}) {
  const needsDecision = resolverNeedsDecision(row);
  const band = matchScoreBand(row.match_score);
  const statusTone =
    row.review_status === "auto_accepted"
      ? "chip-positive"
      : row.review_status === "rejected"
        ? "chip-danger"
        : row.review_status === "review_required"
          ? "chip-caution"
          : "chip";
  const hardRejects = row.hard_reject_reasons ?? [];

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`chip ${statusTone}`}>{row.review_status}</span>
          <span className={`chip ${band.tone === "positive" ? "chip-positive" : "chip"}`}>
            score {formatScore(row.match_score)} · {band.label}
          </span>
          <span className="chip">{row.source_id}</span>
          {row.is_synthetic ? <span className="chip">synthetic</span> : null}
        </div>
        {needsDecision ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={decisionPending}
              onClick={() => void onDecide("link")}
            >
              Link
            </button>
            <button
              type="button"
              className="btn"
              disabled={decisionPending}
              onClick={() => void onDecide("reject")}
            >
              Reject
            </button>
          </div>
        ) : (
          <span className="text-2xs text-ink-muted">
            {row.decided_by ?? "system"} · {formatUtcTimestamp(row.decided_at)}
          </span>
        )}
      </div>
      <div className="panel-body space-y-2">
        <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
          <div>
            <p className="text-2xs uppercase tracking-wide text-ink-subtle">Provider (candidate)</p>
            <p className="text-xs text-ink">{resolverProviderLabel(row)}</p>
          </div>
          <div>
            <p className="text-2xs uppercase tracking-wide text-ink-subtle">Canonical (match)</p>
            <p className="text-xs text-ink">{resolverCanonicalLabel(row)}</p>
          </div>
        </div>
        {hardRejects.length > 0 ? (
          <div>
            <p className="text-2xs uppercase tracking-wide text-ink-subtle">Hard rejects</p>
            <BulletList items={hardRejects} tone="danger" />
          </div>
        ) : null}
      </div>
    </div>
  );
}

