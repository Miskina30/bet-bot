"use client";

/**
 * Shared screen states. The brief requires five of them everywhere, so they live
 * in one place and every screen uses the same vocabulary:
 *
 *  * `LoadingBlock`   - first load, nothing to show yet
 *  * `EmptyBlock`     - the request succeeded and there is genuinely nothing
 *  * `StaleBanner`    - the data is older than its freshness budget
 *  * `PartialBanner`  - one or more sources did not answer, so the view is partial
 *  * `ErrorBlock`     - the request failed; retriable only when the API says so
 *
 * None of them hides the underlying detail: an analyst needs to know *why* a
 * number is missing before trusting what remains.
 */

import type { ReactNode } from "react";

import { describeApiError, type ApiError } from "@/lib/api";

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="panel" role="status" aria-live="polite">
      <div className="panel-body text-ink-muted">{label}…</div>
    </div>
  );
}

export function EmptyBlock({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="panel" role="status">
      <div className="panel-body space-y-1">
        <p className="text-ink">{title}</p>
        {hint !== undefined ? <p className="text-2xs text-ink-muted">{hint}</p> : null}
      </div>
    </div>
  );
}

export function StaleBanner({ sinceIso, ageLabel }: { sinceIso?: string | null; ageLabel: string }) {
  return (
    <div className="panel border-caution bg-caution-soft" role="status">
      <div className="panel-body text-2xs text-caution">
        <strong>Stale data.</strong> Last confirmed update {sinceIso ?? "unknown"} ({ageLabel}).
        Prices may have moved; re-check the source before acting on anything here.
      </div>
    </div>
  );
}

export function PartialBanner({ failedSources }: { failedSources: readonly string[] }) {
  return (
    <div className="panel border-caution bg-caution-soft" role="status">
      <div className="panel-body text-2xs text-caution">
        <strong>Partial view.</strong> {failedSources.length} source
        {failedSources.length === 1 ? "" : "s"} did not answer: {failedSources.join(", ")}. Rows
        below may be missing venues, so an apparent absence of an opportunity is not evidence
        that none exists.
      </div>
    </div>
  );
}

export function ErrorBlock({
  error,
  onRetry,
  title = "Request failed",
}: {
  error: ApiError;
  onRetry?: (() => void) | undefined;
  title?: string;
}) {
  return (
    <div className="panel border-danger bg-danger-soft" role="alert">
      <div className="panel-body space-y-2">
        <p className="text-ink">
          <strong>{title}.</strong> {describeApiError(error)}
        </p>
        {error.detail !== null ? (
          <pre className="mono max-h-40 overflow-auto whitespace-pre-wrap rounded border border-line bg-surface-sunken p-2">
            {error.detail}
          </pre>
        ) : null}
        <p className="text-2xs text-ink-muted">
          {error.method} {error.url}
          {error.status !== null ? ` → HTTP ${error.status}` : ""}
        </p>
        {onRetry !== undefined && error.retriable ? (
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function SectionPanel({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2 className="panel-title">{title}</h2>
          {subtitle !== undefined ? <p className="panel-subtitle">{subtitle}</p> : null}
        </div>
        {actions !== undefined ? <div className="flex items-center gap-2">{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function KeyValueList({ rows }: { rows: ReadonlyArray<{ label: string; value: ReactNode }> }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1">
          <dt className="text-2xs uppercase tracking-wide text-ink-subtle">{row.label}</dt>
          <dd className="text-right text-xs text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function BulletList({ items, tone = "neutral" }: { items: readonly string[]; tone?: "neutral" | "caution" | "danger" }) {
  if (items.length === 0) {
    return <p className="text-2xs text-ink-muted">none</p>;
  }
  const toneClass = tone === "caution" ? "text-caution" : tone === "danger" ? "text-danger" : "text-ink";
  return (
    <ul className={`list-disc space-y-1 pl-4 text-2xs ${toneClass}`}>
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>{item}</li>
      ))}
    </ul>
  );
}
