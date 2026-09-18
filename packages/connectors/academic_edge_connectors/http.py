"""Provider HTTP client: rate limiting, retries and the source-policy gate.

This module is the only place in the connector layer that talks to the network.
It deliberately keeps three concerns together, because they must not be
separately bypassable:

1. **Source-policy gate.**  A client built in ``mode="live"`` first calls
   :meth:`academic_edge_domain.policy.SourcePolicyRegistry.require_live_client`
   with the adapter's declared :class:`~academic_edge_domain.enums.AutomationScope`.
   An unknown source, a source whose ``automation_allowed`` is false (Crocobet) or
   a scope mismatch raises :class:`~academic_edge_domain.policy.PolicyViolation`
   *before* any socket is created.  ``mode="fixture"`` skips the gate by design:
   fixture adapters read labelled local payloads and never issue live traffic.
2. **Politeness.**  A per-minute token bucket (rate taken from the source policy,
   overridable) with an injectable monotonic clock, so tests never sleep.
3. **Retries that respect the provider.**  429/5xx are retried with exponential
   backoff **plus jitter**, honouring ``Retry-After``.  When the budget is spent
   we raise :class:`ProviderRateLimited` (429) or :class:`AdapterUnavailable`
   (5xx) - we never circumvent a rate limit.

Tests inject ``httpx.MockTransport`` via ``transport=`` so no test ever opens a
socket; the ``client=`` argument allows injecting a fully pre-configured client.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from academic_edge_domain.enums import AutomationScope
from academic_edge_domain.policy import SourcePolicy, SourcePolicyRegistry
from academic_edge_domain.time import ensure_utc, utcnow

from academic_edge_connectors.base import AdapterUnavailable, ProviderRateLimited

__all__ = [
    "DEFAULT_USER_AGENT",
    "FIXTURE_MODE",
    "LIVE_MODE",
    "VALID_MODES",
    "HttpResult",
    "ProviderHttpClient",
    "TokenBucketRateLimiter",
    "parse_retry_after",
]

LOGGER = logging.getLogger(__name__)

LIVE_MODE = "live"
FIXTURE_MODE = "fixture"
VALID_MODES = frozenset({LIVE_MODE, FIXTURE_MODE})

#: Statuses that mean "come back later" rather than "your request is wrong".
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

DEFAULT_USER_AGENT = "academic-edge/0.1 (read-only market research; contact: operator)"


@dataclass(frozen=True, slots=True)
class HttpResult:
    """A completed HTTP exchange, archived exactly as received.

    ``headers`` keys are lower-cased so lookups are case-insensitive regardless
    of transport.  ``content`` is kept as bytes: the raw archive stores what the
    provider actually sent, and parsing happens later under drift checks.
    """

    status_code: int
    content: bytes
    headers: dict[str, str]
    elapsed_ms: int
    url: str

    @property
    def ok(self) -> bool:
        """True for 2xx responses."""
        return 200 <= self.status_code < 300

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup."""
        return self.headers.get(name.lower())

    @property
    def text(self) -> str:
        """Decoded body (UTF-8 with replacement, never raises)."""
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Decode the body as JSON.

        Raised errors are plain :class:`ValueError`/:class:`json.JSONDecodeError`;
        adapters should use ``parsing.parse_json_bytes`` to turn malformed payloads
        into :class:`~academic_edge_connectors.base.ParserDriftError` instead.
        """
        return json.loads(self.text)

    @property
    def content_type(self) -> str | None:
        return self.header("content-type")


def parse_retry_after(value: str | None, *, now: dt.datetime | None = None) -> float | None:
    """Parse an HTTP ``Retry-After`` header into a non-negative delay in seconds.

    Both documented forms are accepted: delta-seconds (``"120"``) and an
    HTTP-date (``"Wed, 21 Oct 2026 07:28:00 GMT"``).  ``None``/garbage returns
    ``None`` so callers fall back to plain exponential backoff instead of
    guessing a delay.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    parsed = email.utils.parsedate_to_datetime(text)
    if parsed is None:
        LOGGER.warning("ignoring unparseable Retry-After header: %r", value)
        return None
    reference = ensure_utc(now) if now is not None else utcnow()
    return max(0.0, (ensure_utc(parsed) - reference).total_seconds())


class TokenBucketRateLimiter:
    """Token-bucket limiter expressed in requests per minute.

    * ``requests_per_minute <= 0`` disables limiting (fixture/manual sources).
    * the bucket holds ``burst`` tokens (defaults to one minute's worth), so a
      short burst is allowed and then the sustained rate is enforced.
    * the clock and the sleeper are injected, which makes the limiter
      deterministically testable without real waiting.
    """

    def __init__(
        self,
        *,
        requests_per_minute: int,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.requests_per_minute = max(0, int(requests_per_minute))
        self.burst = int(burst) if burst is not None else max(1, self.requests_per_minute)
        if self.burst < 1:
            self.burst = 1
        self._clock = clock
        self._sleeper = sleeper
        self._tokens = float(self.burst)
        self._last_refill = clock()
        self.total_wait_seconds = 0.0

    @property
    def enabled(self) -> bool:
        """False when the source has no configured rate limit."""
        return self.requests_per_minute > 0

    @property
    def refill_rate_per_second(self) -> float:
        return self.requests_per_minute / 60.0 if self.enabled else 0.0

    def _refill(self) -> None:
        """Add the tokens earned since the previous observation."""
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._last_refill = now
        if not self.enabled:
            self._tokens = float(self.burst)
            return
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.refill_rate_per_second)

    @property
    def available_tokens(self) -> float:
        """Tokens currently available (after refilling for elapsed time)."""
        self._refill()
        return self._tokens

    def try_acquire(self) -> bool:
        """Non-blocking acquire; returns whether a token was available."""
        if not self.enabled:
            return True
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def acquire(self) -> float:
        """Block until one token is available; returns the seconds waited.

        The wait is computed from the token deficit and the refill rate, then
        handed to the injected sleeper.  Rate limits are never bypassed, only
        waited out.
        """
        if not self.enabled:
            return 0.0
        self._refill()
        wait = 0.0
        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self.refill_rate_per_second
            self._sleeper(wait)
            self.total_wait_seconds += wait
            self._tokens = 0.0
            self._last_refill = self._clock()
        else:
            self._tokens -= 1.0
        return wait


class ProviderHttpClient:
    """Policy-gated, polite, retrying HTTP client for official read endpoints.

    ``mode="fixture"`` skips the policy gate by design: fixture adapters read
    labelled local payloads and never fetch live data, and the integration tests
    inject ``httpx.MockTransport`` so no socket is opened either way.  Redirects
    are *not* followed (``follow_redirects=False``): we never chase a redirect
    into arbitrary HTML - a 3xx is handed back to the caller and fails parsing.
    """

    def __init__(
        self,
        *,
        source_id: str,
        policy_registry: SourcePolicyRegistry,
        scope: AutomationScope,
        mode: str = LIVE_MODE,
        base_url: str = "",
        default_headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.5,
        backoff_max_seconds: float = 8.0,
        max_retry_after_seconds: float = 60.0,
        jitter_ratio: float = 0.25,
        requests_per_minute: int | None = None,
        burst: int | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")

        self.source_id = source_id
        self.mode = mode
        self.scope = scope
        self.policy: SourcePolicy | None = None
        policy_limit: int | None = None

        if mode == LIVE_MODE:
            # Hard gate.  Raises PolicyViolation for an unknown source, for a
            # source whose automation_allowed is false (Crocobet) or for a scope
            # the registry does not permit - all before any socket exists.
            self.policy = policy_registry.require_live_client(source_id, scope)
            policy_limit = self.policy.rate_limit_per_minute
        elif source_id in policy_registry:
            self.policy = policy_registry.get(source_id)
            policy_limit = self.policy.rate_limit_per_minute

        self.requests_per_minute = (
            int(requests_per_minute) if requests_per_minute is not None else int(policy_limit or 0)
        )

        self._rng = rng if rng is not None else random.Random()
        self._clock = clock
        self._sleeper = sleeper
        self._max_attempts = max(1, int(max_attempts))
        self._backoff_base_seconds = max(0.0, float(backoff_base_seconds))
        self._backoff_max_seconds = max(0.0, float(backoff_max_seconds))
        self._max_retry_after_seconds = max(0.0, float(max_retry_after_seconds))
        self._jitter_ratio = max(0.0, float(jitter_ratio))
        self._default_headers: dict[str, str] = {
            "user-agent": user_agent,
            "accept": "application/json",
        }
        if default_headers:
            self._default_headers.update(
                {key.lower(): value for key, value in default_headers.items()}
            )

        self.limiter = TokenBucketRateLimiter(
            requests_per_minute=self.requests_per_minute,
            burst=burst,
            clock=clock,
            sleeper=sleeper,
        )
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.Client(
                base_url=base_url,
                transport=transport,
                timeout=timeout_seconds,
                headers=self._default_headers,
                follow_redirects=False,
            )
        )

        # Observability (read-only, in-memory).
        self.request_count = 0
        self.attempts_made = 0
        self.total_backoff_seconds = 0.0
        self.last_result: HttpResult | None = None
        self.last_error: str | None = None

    @property
    def is_fixture_mode(self) -> bool:
        """True when this client was built outside the live-policy gate."""
        return self.mode == FIXTURE_MODE

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResult:
        """GET a provider endpoint; equivalent to ``request("GET", ...)``."""
        return self.request("GET", path, params=params, headers=headers)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> HttpResult:
        """Perform one politeness-gated, retried request.

        Returns the first response whose status is not in
        :data:`RETRY_STATUS_CODES` (so 4xx other than 429 come back to the caller
        for interpretation).  Raises :class:`ProviderRateLimited` when a 429
        survives the retry budget, or when the provider asks us to wait longer
        than ``max_retry_after_seconds`` (the caller must then back off at a
        higher level; we never retry before the provider said we could).  Raises
        :class:`AdapterUnavailable` for transport failures and persistent 5xx.
        """
        merged = dict(self._default_headers)
        if headers:
            merged.update({key.lower(): value for key, value in headers.items()})

        for attempt in range(1, self._max_attempts + 1):
            self.attempts_made += 1
            waited = self.limiter.acquire()
            if waited > 0:
                LOGGER.debug(
                    "%s: token bucket held %s %s for %.3fs",
                    self.source_id,
                    method,
                    path,
                    waited,
                )
            started = self._clock()
            try:
                response = self._client.request(
                    method, path, params=params, headers=merged, content=content
                )
            except httpx.HTTPError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning(
                    "%s: %s %s failed on attempt %d/%d (%s)",
                    self.source_id,
                    method,
                    path,
                    attempt,
                    self._max_attempts,
                    exc,
                )
                if attempt >= self._max_attempts:
                    raise AdapterUnavailable(
                        f"{self.source_id}: {method} {path} unavailable after "
                        f"{attempt} attempt(s): {exc}"
                    ) from exc
                self._sleep_backoff(attempt)
                continue

            result = HttpResult(
                status_code=response.status_code,
                content=response.content,
                headers={key.lower(): value for key, value in response.headers.items()},
                elapsed_ms=self._elapsed_ms(started),
                url=str(response.url),
            )
            self.last_result = result
            self.request_count += 1
            if result.status_code not in RETRY_STATUS_CODES:
                return result

            retry_after = parse_retry_after(result.header("retry-after"))
            self.last_error = f"HTTP {result.status_code}"
            is_rate_limited = result.status_code == 429
            if retry_after is not None and retry_after > self._max_retry_after_seconds:
                if is_rate_limited:
                    raise ProviderRateLimited(
                        f"{self.source_id}: {path} returned HTTP 429 with "
                        f"Retry-After={retry_after:g}s, above the "
                        f"{self._max_retry_after_seconds:g}s in-process cap; "
                        "back off externally and retry later",
                        retry_after_seconds=retry_after,
                    )
                LOGGER.warning(
                    "%s: ignoring Retry-After=%gs above cap on HTTP %d",
                    self.source_id,
                    retry_after,
                    result.status_code,
                )
                retry_after = None

            if attempt >= self._max_attempts:
                if is_rate_limited:
                    raise ProviderRateLimited(
                        f"{self.source_id}: {path} still rate limited (HTTP 429) "
                        f"after {attempt} attempt(s)",
                        retry_after_seconds=retry_after,
                    )
                raise AdapterUnavailable(
                    f"{self.source_id}: {path} returned HTTP {result.status_code} "
                    f"after {attempt} attempt(s)"
                )

            LOGGER.warning(
                "%s: HTTP %d on %s; retrying (%d/%d)",
                self.source_id,
                result.status_code,
                path,
                attempt,
                self._max_attempts,
            )
            self._sleep_backoff(attempt, retry_after=retry_after)

        raise AdapterUnavailable(
            f"{self.source_id}: {method} {path} exhausted {self._max_attempts} attempt(s)"
        )

    def _sleep_backoff(self, attempt: int, *, retry_after: float | None = None) -> float:
        """Sleep before the next attempt; returns the seconds slept.

        Exponential backoff (``backoff_base_seconds * 2 ** (attempt - 1)``) capped
        at ``backoff_max_seconds`` and jittered by up to ``jitter_ratio`` of the
        delay.  When the provider sent a usable ``Retry-After`` we wait exactly
        that long plus jitter: retrying earlier would be a rate-limit violation,
        not a politeness choice.
        """
        if retry_after is not None:
            delay = retry_after
        else:
            delay = min(
                self._backoff_max_seconds,
                self._backoff_base_seconds * 2 ** (attempt - 1),
            )
        jitter = self._rng.uniform(0.0, delay * self._jitter_ratio) if delay > 0 else 0.0
        total = delay + jitter
        if total > 0:
            self._sleeper(total)
        self.total_backoff_seconds += total
        return total

    def _elapsed_ms(self, started: float) -> int:
        """Milliseconds since ``started`` on the injected (monotonic) clock."""
        return max(0, int((self._clock() - started) * 1000))

    def close(self) -> None:
        """Close the underlying httpx client when this instance owns it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ProviderHttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
