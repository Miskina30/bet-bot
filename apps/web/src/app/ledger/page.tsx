"use client";

/**
 * Paper ledger — the 4-week paper-trading record. Research only: no real stake
 * exists. Every entry is labelled `is_synthetic` and tied to an opportunity id,
 * so an analyst can trace a hypothetical P&L back to the evidence that caused it.
 */

import { EmptyBlock, ErrorBlock, LoadingBlock, SectionPanel } from "@/components/StateBlocks";
import { formatMoney, formatUtcTimestamp, humaniseEnumValue } from "@/lib/format";
import { usePaperLedger } from "@/lib/queries";

export default function LedgerPage() {
  const query = usePaperLedger({ limit: 200 });
  const refetch = () => {
    void query.refetch();
  };

  if (query.isPending) {
    return <LoadingBlock label="Loading the paper ledger" />;
  }
  if (query.isError || query.data === undefined) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message: query.error instanceof Error ? query.error.message : "Unknown error",
          detail: null,
          url: "/v1/paper-ledger",
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
  const summary = page.summary;
  const openCount = rows.filter((row) => row.status === "open").length;
  const settledCount = rows.filter((row) => row.status === "settled").length;

  return (
    <div className="space-y-4">
      <SectionPanel
        title="Paper ledger"
        subtitle={`${rows.length} entries · ${openCount} open · ${settledCount} settled · research only, no real stake`}
        actions={
          <button type="button" className="btn" onClick={refetch}>
            Refresh
          </button>
        }
      >
        {summary !== null && summary !== undefined ? (
          <div className="panel border-accent bg-accent-soft">
            <div className="panel-body text-2xs text-accent">
              <strong>Summary:</strong> net P&amp;L {formatMoney(summary.net_pnl ?? null, summary.currency ?? "EUR")}
              {" · turnover "}{formatMoney(summary.total_staked ?? null, summary.currency ?? "EUR")}
              {" · entries "}{rows.length}
            </div>
          </div>
        ) : null}

        {rows.length === 0 ? (
          <EmptyBlock
            title="No paper ledger entries yet."
            hint="Paper entries are created when an actionable opportunity clears friction and a stake is simulated. Run the seed or the worker pipeline to populate the ledger."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-xs">
              <thead>
                <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-ink-subtle">
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Source</th>
                  <th className="px-2 py-2 text-right">Stake</th>
                  <th className="px-2 py-2 text-right">Odds</th>
                  <th className="px-2 py-2 text-right">Fees</th>
                  <th className="px-2 py-2 text-right">P&amp;L</th>
                  <th className="px-2 py-2">Placed</th>
                  <th className="px-2 py-2">Settled</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-line/60 align-top">
                    <td className="px-2 py-2">
                      <span className={row.status === "settled" ? "chip chip-positive" : "chip"}>
                        {humaniseEnumValue(row.status)}
                      </span>
                      {row.is_synthetic ? <span className="chip ml-1">synthetic</span> : null}
                    </td>
                    <td className="px-2 py-2">
                      <a className="underline hover:no-underline" href={`/opportunities/${row.opportunity_id ?? ""}`}>
                        {row.source_id}
                      </a>
                    </td>
                    <td className="px-2 py-2 text-right">{formatMoney(row.stake, row.currency)}</td>
                    <td className="px-2 py-2 text-right mono">{row.decimal_odds}</td>
                    <td className="px-2 py-2 text-right">{formatMoney(row.fees ?? null, row.currency)}</td>
                    <td className="px-2 py-2 text-right">
                      {row.pnl === null || row.pnl === undefined ? (
                        <span className="text-ink-muted">pending</span>
                      ) : (
                        <span className={Number(row.pnl) >= 0 ? "chip chip-positive" : "chip chip-danger"}>
                          {formatMoney(row.pnl, row.currency)}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2">{formatUtcTimestamp(row.placed_at)}</td>
                    <td className="px-2 py-2">{row.settled_at ? formatUtcTimestamp(row.settled_at) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionPanel>
    </div>
  );
}
