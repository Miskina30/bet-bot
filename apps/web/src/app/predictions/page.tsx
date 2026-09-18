"use client";

/**
 * Model card screen — walk-forward metrics and explanation per registered model.
 * "Forecast explanation" from the brief: each card shows what the model reported
 * about itself so an analyst can decide whether to trust its predictions.
 */

import {
  EmptyBlock,
  ErrorBlock,
  KeyValueList,
  LoadingBlock,
  SectionPanel,
} from "@/components/StateBlocks";
import { modelCardRows } from "@/lib/derive";
import { formatUtcTimestamp, humaniseKey } from "@/lib/format";
import { useModelsMetrics } from "@/lib/queries";

export default function PredictionsPage() {
  const query = useModelsMetrics();
  const refetch = () => {
    void query.refetch();
  };

  if (query.isPending) {
    return <LoadingBlock label="Loading model metrics" />;
  }
  if (query.isError || query.data === undefined) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message: query.error instanceof Error ? query.error.message : "Unknown error",
          detail: null,
          url: "/v1/models/metrics",
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

  const cards = result.data.items;

  return (
    <div className="space-y-4">
      <SectionPanel
        title="Registered models"
        subtitle={`${cards.length} model(s). Each card shows the walk-forward metrics the model reported at training time.`}
        actions={
          <button type="button" className="btn" onClick={refetch}>
            Refresh
          </button>
        }
      >
        {cards.length === 0 ? (
          <EmptyBlock
            title="No models registered yet."
            hint="Run the forecasting pipeline to train and register a model. Without a model, predictions and model-vs-market EV cannot be computed."
          />
        ) : (
          <div className="space-y-4">
            {cards.map((card) => {
              const { metrics, params } = modelCardRows(card);
              return (
                <div key={card.model} className="panel">
                  <div className="panel-header">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">{card.model}</span>
                      <span className="chip">{card.algorithm}</span>
                      {card.is_active ? <span className="chip chip-positive">active</span> : null}
                      {card.is_synthetic ? <span className="chip">synthetic</span> : null}
                    </div>
                    <span className="text-2xs text-ink-muted">
                      trained {formatUtcTimestamp(card.trained_at)}
                    </span>
                  </div>
                  <div className="panel-body space-y-4">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <div>
                        <p className="text-2xs uppercase tracking-wide text-ink-subtle">Training window</p>
                        <KeyValueList
                          rows={[
                            { label: "Start", value: card.train_window.start ?? "not reported" },
                            { label: "End", value: card.train_window.end ?? "not reported" },
                          ]}
                        />
                      </div>
                      <div>
                        <p className="text-2xs uppercase tracking-wide text-ink-subtle">Calibration window</p>
                        <KeyValueList
                          rows={[
                            { label: "Start", value: card.calibration_window.start ?? "not reported" },
                            { label: "End", value: card.calibration_window.end ?? "not reported" },
                          ]}
                        />
                      </div>
                    </div>
                    {metrics.length > 0 ? (
                      <div>
                        <p className="text-2xs uppercase tracking-wide text-ink-subtle">Metrics</p>
                        <dl className="mt-1 grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2 lg:grid-cols-3">
                          {metrics.map((m) => (
                            <div key={m.key} className="flex items-baseline justify-between gap-3 border-b border-line/40 py-0.5">
                              <dt className="text-2xs text-ink-subtle">{humaniseKey(m.key)}</dt>
                              <dd className="mono text-right text-xs text-ink">{m.display}</dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    ) : null}
                    {params.length > 0 ? (
                      <div>
                        <p className="text-2xs uppercase tracking-wide text-ink-subtle">Hyperparameters</p>
                        <dl className="mt-1 grid grid-cols-1 gap-x-6 gap-y-0.5 sm:grid-cols-2 lg:grid-cols-3">
                          {params.map((p) => (
                            <div key={p.key} className="flex items-baseline justify-between gap-3 border-b border-line/40 py-0.5">
                              <dt className="text-2xs text-ink-subtle">{humaniseKey(p.key)}</dt>
                              <dd className="mono text-right text-xs text-ink">{p.display}</dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </SectionPanel>
    </div>
  );
}

