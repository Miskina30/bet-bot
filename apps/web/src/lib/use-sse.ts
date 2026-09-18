"use client";

/**
 * Live opportunity updates over Server-Sent Events.
 *
 * Contract with the API: `GET /v1/stream/opportunities` (brief, API section:
 * "Publish live updates through SSE first").
 *
 * Behaviour the dashboard depends on:
 *  * reconnect with exponential backoff + jitter after any drop;
 *  * a `stale` flag when nothing arrives for 30s (configurable), because a stream
 *    that is "open but silent" is exactly the failure an analyst must notice;
 *  * full cleanup on unmount (close the EventSource, clear every timer);
 *  * never throws: an unparseable or unexpected frame is recorded in `lastError`
 *    and dropped - it is never rendered as a number.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { SSE_STALE_AFTER_MS, streamOpportunitiesUrl } from "@/lib/api";
import { opportunitySchema, type Opportunity } from "@/lib/schemas";

export type StreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "stale"
  | "error"
  | "unsupported"
  | "closed";

export interface StreamedOpportunity {
  /** Opportunity id - used to de-duplicate repeated frames. */
  id: string;
  opportunity: Opportunity;
  /** When this browser received the frame (not the API clock). */
  receivedAt: string;
  /** SSE event name that carried the frame. */
  eventName: string;
}

export interface UseOpportunitiesStreamOptions {
  /** Set false to keep the stream closed (e.g. on a screen without live data). */
  enabled?: boolean;
  /** Silence after which the stream is reported stale. Default 30000 ms. */
  staleAfterMs?: number;
  /** How many recent frames to keep in memory. Default 50. */
  maxItems?: number;
  /** Called for each accepted frame (e.g. to invalidate a cache). */
  onOpportunity?: ((opportunity: Opportunity) => void) | undefined;
}

export interface UseOpportunitiesStreamResult {
  status: StreamStatus;
  /** True when no frame has arrived within `staleAfterMs`. */
  stale: boolean;
  lastEventAt: string | null;
  lastError: string | null;
  /** Consecutive failed connection attempts (reset on a successful open). */
  attempts: number;
  items: StreamedOpportunity[];
  /** Force an immediate reconnect (closes the current stream first). */
  reconnect: () => void;
  /** Drop buffered frames (does not affect the connection). */
  clear: () => void;
}

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

function extractOpportunityCandidate(decoded: unknown): unknown {
  if (typeof decoded === "object" && decoded !== null && !Array.isArray(decoded)) {
    const record = decoded as Record<string, unknown>;
    if ("opportunity" in record) {
      return record["opportunity"];
    }
    if ("item" in record) {
      return record["item"];
    }
    if ("data" in record) {
      return record["data"];
    }
  }
  return decoded;
}

/**
 * Parses one SSE frame into an `Opportunity`, tolerating `{opportunity}`, `{item}`
 * and `{data}` envelopes. Returns `null` for anything else.
 */
export function parseStreamOpportunity(raw: string): Opportunity | null {
  if (raw.trim() === "") {
    return null;
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    return null;
  }
  const parsed = opportunitySchema.safeParse(extractOpportunityCandidate(decoded));
  return parsed.success ? parsed.data : null;
}

/** Backoff for attempt N (1-based): 1s, 2s, 4s ... capped at 30s, plus jitter. */
export function reconnectDelayMs(attempt: number): number {
  const exponential = Math.min(
    RECONNECT_MAX_MS,
    RECONNECT_BASE_MS * 2 ** Math.max(0, attempt - 1),
  );
  return Math.round(exponential * (0.8 + Math.random() * 0.4));
}

export function useOpportunitiesStream(
  options: UseOpportunitiesStreamOptions = {},
): UseOpportunitiesStreamResult {
  const { enabled = true, staleAfterMs = SSE_STALE_AFTER_MS, maxItems = 50 } = options;

  const [status, setStatus] = useState<StreamStatus>("idle");
  const [stale, setStale] = useState(false);
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [items, setItems] = useState<StreamedOpportunity[]>([]);
  /** Bumped by `reconnect()` to tear down and rebuild the effect. */
  const [generation, setGeneration] = useState(0);

  const callbackRef = useRef<UseOpportunitiesStreamOptions["onOpportunity"]>(
    options.onOpportunity,
  );
  useEffect(() => {
    callbackRef.current = options.onOpportunity;
  }, [options.onOpportunity]);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      setStatus("unsupported");
      setLastError(
        "This browser does not expose EventSource, so live updates are unavailable. Use Refresh to read the latest page.",
      );
      return;
    }

    let disposed = false;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let staleTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const clearStaleTimer = (): void => {
      if (staleTimer !== null) {
        clearTimeout(staleTimer);
        staleTimer = null;
      }
    };

    const armStaleTimer = (): void => {
      clearStaleTimer();
      staleTimer = setTimeout(() => {
        if (!disposed) {
          setStale(true);
          setStatus("stale");
        }
      }, staleAfterMs);
    };

    const closeSource = (): void => {
      if (source !== null) {
        source.close();
        source = null;
      }
    };

    const handleFrame = (raw: string, eventName: string): void => {
      if (disposed) {
        return;
      }
      const receivedAt = new Date().toISOString();
      setLastEventAt(receivedAt);
      setStale(false);
      setStatus("open");
      armStaleTimer();

      const opportunity = parseStreamOpportunity(raw);
      if (opportunity === null) {
        setLastError(
          `Ignored a "${eventName}" frame that did not match the opportunity schema; nothing was displayed for it.`,
        );
        return;
      }
      setItems((previous) =>
        [
          { id: opportunity.id, opportunity, receivedAt, eventName },
          ...previous.filter((entry) => entry.id !== opportunity.id),
        ].slice(0, maxItems),
      );
      const callback = callbackRef.current;
      if (callback !== undefined) {
        callback(opportunity);
      }
    };

    const scheduleReconnect = (): void => {
      if (disposed) {
        return;
      }
      attempt += 1;
      setAttempts(attempt);
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        open();
      }, reconnectDelayMs(attempt));
    };

    const open = (): void => {
      if (disposed) {
        return;
      }
      closeSource();
      setStatus("connecting");
      const eventSource = new EventSource(streamOpportunitiesUrl());
      source = eventSource;

      eventSource.onopen = (): void => {
        if (disposed) {
          return;
        }
        attempt = 0;
        setAttempts(0);
        setStale(false);
        setLastError(null);
        setStatus("open");
        armStaleTimer();
      };

      eventSource.onerror = (): void => {
        if (disposed) {
          return;
        }
        setLastError(
          "The live stream disconnected. Reconnecting with backoff; the table below shows the last known state.",
        );
        setStatus("error");
        closeSource();
        clearStaleTimer();
        scheduleReconnect();
      };

      eventSource.onmessage = (event: MessageEvent<string>): void => {
        handleFrame(String(event.data), "message");
      };

      for (const eventName of ["opportunity", "opportunities", "update"]) {
        eventSource.addEventListener(eventName, (event: Event): void => {
          if (event instanceof MessageEvent) {
            handleFrame(String(event.data), eventName);
          }
        });
      }
    };

    open();

    return () => {
      disposed = true;
      clearStaleTimer();
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      closeSource();
    };
  }, [enabled, generation, maxItems, staleAfterMs]);

  const reconnect = useCallback((): void => {
    setStale(false);
    setLastError(null);
    setGeneration((current) => current + 1);
  }, []);

  const clear = useCallback((): void => {
    setItems([]);
  }, []);

  return { status, stale, lastEventAt, lastError, attempts, items, reconnect, clear };
}