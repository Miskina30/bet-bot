"""Polymarket adapter -- documented public reads only (Gamma + CLOB).

Polymarket is one more venue, never ground truth: discovery via the Gamma API,
books and history via the public CLOB reads. A Yes/No market is mapped onto a
canonical market ONLY when its question text is unambiguous:

* mentions of "both teams to score" -> FT_BTTS (yes/no);
* a "<team> to win" question (single team named) -> FT_1X2;
* anything else -> skipped, with the reason recorded in the market's evidence.

Read-only. There is no order placement, no wallet code and no signing anywhere
in this module. Price -> decimal odds is ``1 / price``; a market with a missing
or zero price is SKIPPED, never invented.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from academic_edge_domain.enums import (
    AutomationScope,
    MarketPeriod,
    MarketType,
    OutcomeKind,
    TeamScope,
    VenueKind,
)
from academic_edge_domain.settings import Settings
from academic_edge_domain.time import utcnow

from academic_edge_connectors.contracts import (
    HealthReport,
    ProviderAdapter,
    ProviderEvent,
    ProviderMarket,
    ProviderOutcome,
    build_provenance,
)
from academic_edge_connectors.fixture_io import FixtureStore
from academic_edge_connectors.http import (
    FIXTURE_MODE,
    LIVE_MODE,
    AdapterUnavailable,
    ProviderHttpClient,
)
from academic_edge_connectors.parsing import (
    optional_timestamp,
    parse_json_bytes,
    parse_timestamp,
    require_field,
    require_list,
    require_object,
)

SOURCE_ID = "polymarket_gamma"
CLOB_SOURCE_ID = "polymarket_clob"
SCOPE = AutomationScope.DOCUMENTED_PUBLIC_READS
GAMMA_EVENTS_FIXTURE = "polymarket_gamma_events.json"
CLOB_BOOK_FIXTURE = "polymarket_clob_book.json"
MIN_PRICE = "0.001"
MAX_PRICE = "0.999"

_BTTS_RE = re.compile(r"\bboth teams to score\b", re.IGNORECASE)
_TEAM_WIN_RE = re.compile(r"^(?P<team>.+?)\s+to win\b", re.IGNORECASE)
_TITLE_SIDES_RE = re.compile(r"^(?P<home>.+?)\s+vs?\.?\s+(?P<away>.+?)$", re.IGNORECASE)


def sides_from_title(title: str) -> tuple[str, str] | None:
    """Best-effort home/away extraction from an event title like "A vs B".

    Returns ``None`` when the title is not a two-sided fixture title, which is
    common for outrights and specials -- those events legitimately carry
    ``"?"`` sides and only match canonical events on question-level markets.
    """
    match = _TITLE_SIDES_RE.match(title.strip())
    if not match:
        return None
    home, away = match.group("home").strip(), match.group("away").strip()
    return (home, away) if home and away else None


def price_to_decimal_odds(price: Any) -> Decimal | None:
    """Convert a prediction-market price to decimal odds, or ``None`` when invalid.

    ``None`` means "no usable price": the caller skips the outcome rather than
    fabricating a price. Prices of 0/1 (or outside (0, 1)) are degenerate for
    conversion and are rejected for the same reason.
    """
    try:
        value = Decimal(str(price))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if value <= Decimal(MIN_PRICE) or value >= Decimal(MAX_PRICE):
        return None
    return (Decimal(1) / value).quantize(Decimal("0.000001"))


def classify_gamma_market(question: str) -> MarketType | None:
    """Map a Gamma question to a canonical market, or ``None`` to skip it."""
    if not question:
        return None
    if _BTTS_RE.search(question):
        return MarketType.FT_BTTS
    if _TEAM_WIN_RE.match(question):
        return MarketType.FT_1X2
    return None


def _team_from_win_question(question: str) -> str | None:
    match = _TEAM_WIN_RE.match(question.strip())
    return match.group("team").strip() if match else None


def _parse_gamma_event(raw: Mapping[str, Any], adapter: PolymarketAdapter) -> ProviderEvent | None:
    title = raw.get("title") or ""
    slug = str(raw.get("slug") or raw.get("id") or "")
    if not slug:
        return None
    tags: Any = raw.get("tags") or []
    observed_at = utcnow()
    sides = sides_from_title(str(title))
    scheduled = raw.get("startDate") or raw.get("endDate")
    return ProviderEvent(
        provider_event_id=slug,
        competition_name=str(
            (raw.get("series") or {}).get("title")
            if isinstance(raw.get("series"), dict)
            else "Polymarket"
        ),
        competition_provider_id=str(raw.get("seriesId"))
        if raw.get("seriesId") is not None
        else None,
        home_name=sides[0] if sides else "?",
        away_name=sides[1] if sides else "?",
        start_time_utc=parse_timestamp(scheduled) if scheduled else observed_at,
        venue_name=None,
        country=None,
        round_label=str(raw.get("groupItemTitle")) if raw.get("groupItemTitle") else None,
        status="scheduled",
        provenance=build_provenance(
            source_id=SOURCE_ID,
            endpoint="/events",
            observed_at=observed_at,
            received_at=observed_at,
            provider_timestamp=optional_timestamp(raw, "lastUpdated", where="lastUpdated"),
            raw_bytes=adapter.last_payload_bytes,
            is_synthetic=adapter.mode == FIXTURE_MODE,
        ),
        extras={
            "_question": title,
            "_tags": [str(t.get("label") if isinstance(t, dict) else t) for t in tags]
            if isinstance(tags, list)
            else [],
        },
    )


def _parse_gamma_markets(
    raw: Mapping[str, Any], adapter: PolymarketAdapter, endpoint: str
) -> list[ProviderMarket]:
    event_id = str(raw.get("slug") or raw.get("id") or "")
    nested = raw.get("markets")
    if isinstance(nested, list) and nested:
        return [
            market
            for row in nested
            for market in _parse_nested_market(
                require_object(row, where="markets[]"), event_id, adapter, endpoint
            )
        ]
    return _parse_flat_market(raw, event_id, adapter, endpoint)


def _nested_outcome_prices(row: Mapping[str, Any]) -> tuple[list[str], list[str], list[str | None]]:
    """Parse the three parallel arrays Gamma nests under each market row."""

    def _json_list(value: Any) -> list[str]:
        if isinstance(value, str):
            try:
                parsed: Any = json.loads(value)
            except ValueError:
                return []
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        return [str(item) for item in value] if isinstance(value, list) else []

    names = _json_list(row.get("outcomes"))
    prices = _json_list(row.get("outcomePrices") or row.get("lastTradePrices") or [])
    tokens_raw = _json_list(row.get("clobTokenIds") or [])
    tokens = tokens_raw + [None] * max(0, max(len(names), len(prices)) - len(tokens_raw))
    return names, prices, tokens


def _parse_nested_market(
    row: Mapping[str, Any], event_id: str, adapter: PolymarketAdapter, endpoint: str
) -> list[ProviderMarket]:
    question = str(row.get("question") or "")
    market_type = classify_gamma_market(question)
    if market_type is None:
        return []  # ambiguous question text: skip and log, never force a mapping
    names, prices, tokens = _nested_outcome_prices(row)
    parsed = _price_outcomes(market_type, question, names, prices, tokens)
    if not parsed:
        return []
    return [_build_gamma_market(event_id, market_type, question, parsed, adapter, endpoint)]


def _parse_flat_market(
    raw: Mapping[str, Any], event_id: str, adapter: PolymarketAdapter, endpoint: str
) -> list[ProviderMarket]:
    """Legacy flat row support (fixtures and some Gamma views)."""
    question = str(raw.get("title") or "")
    market_type = classify_gamma_market(question)
    if market_type is None:
        return []
    names_raw = raw.get("outcomes")
    prices_raw = raw.get("outcomePrices") or raw.get("lastTradePrices") or []
    names = [str(item) for item in json.loads(names_raw)] if isinstance(names_raw, str) else []
    prices = [str(item) for item in json.loads(prices_raw)] if isinstance(prices_raw, str) else []
    tokens = [None] * len(prices)
    parsed = _price_outcomes(market_type, question, names, prices, tokens)
    if not parsed:
        return []
    return [_build_gamma_market(event_id, market_type, question, parsed, adapter, endpoint)]


def _price_outcomes(
    market_type: MarketType,
    question: str,
    names: list[str],
    prices: list[str],
    tokens: list[str | None],
) -> list[ProviderOutcome]:
    parsed: list[ProviderOutcome] = []
    if market_type is MarketType.FT_BTTS:
        for index, name in enumerate(names):
            if index >= len(prices):
                break
            kind = OutcomeKind.YES if str(name).strip().lower() == "yes" else OutcomeKind.NO
            odds = price_to_decimal_odds(prices[index])
            if odds is None:
                continue
            parsed.append(
                ProviderOutcome(
                    outcome_kind=kind,
                    decimal_odds=odds,
                    provider_outcome_id=tokens[index] if index < len(tokens) else None,
                    extras={"label": str(name)},
                )
            )
    elif market_type is MarketType.FT_1X2:
        team = _team_from_win_question(question)
        if team is None:
            return []
        for index, name in enumerate(names):
            if index >= len(prices) or str(name).strip().lower() != "yes":
                continue  # only the named "team to win" side is mappable
            odds = price_to_decimal_odds(prices[index])
            if odds is None:
                return []
            parsed.append(
                ProviderOutcome(
                    outcome_kind=OutcomeKind.HOME,
                    decimal_odds=odds,
                    provider_outcome_id=tokens[index] if index < len(tokens) else None,
                    extras={"label": team},
                )
            )
    return parsed


def _build_gamma_market(
    event_id: str,
    market_type: MarketType,
    question: str,
    parsed: list[ProviderOutcome],
    adapter: PolymarketAdapter,
    endpoint: str,
) -> ProviderMarket:
    observed_at = utcnow()
    provenance = build_provenance(
        source_id=SOURCE_ID,
        endpoint=endpoint,
        observed_at=observed_at,
        received_at=observed_at,
        raw_bytes=adapter.last_payload_bytes,
        is_synthetic=adapter.mode == FIXTURE_MODE,
    )
    return ProviderMarket(
        provider_event_id=event_id,
        provider_market_id=f"{event_id}:{market_type.value}",
        venue_name="Polymarket",
        venue_kind=VenueKind.PREDICTION_MARKET,
        market_type=market_type,
        outcomes=tuple(parsed),
        period=MarketPeriod.FULL_TIME,
        team_scope=TeamScope.NEUTRAL,
        line=Decimal("0"),
        observed_at=observed_at,
        is_synthetic=adapter.mode == FIXTURE_MODE,
        provenance=provenance,
        extras={
            "question": question,
            "settlement_rule": (
                "Prediction-market resolution; see the market page. One venue, never ground truth."
            ),
        },
    )


class PolymarketAdapter(ProviderAdapter):
    """Gamma discovery + CLOB reads. Public endpoints only, no auth required."""

    def __init__(
        self,
        settings: Settings,
        policy_registry: Any,
        *,
        mode: str = FIXTURE_MODE,
        fixture_store: FixtureStore | None = None,
        overrides: Mapping[str, bytes] | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        live_search_tag: str = "soccer",
    ) -> None:
        if mode not in {LIVE_MODE, FIXTURE_MODE}:
            raise ValueError(f"mode must be 'live' or 'fixture', got {mode!r}")
        self.settings = settings
        self.mode = mode
        self.live_search_tag = live_search_tag
        self.store = fixture_store or FixtureStore(overrides=overrides, source_id=SOURCE_ID)
        self.last_payload_bytes: bytes | None = None
        self.http: ProviderHttpClient | None = None

        if mode == LIVE_MODE:
            if not settings.polymarket_enabled:
                raise AdapterUnavailable(
                    f"{SOURCE_ID}: POLYMARKET_ENABLED is false; use fixture mode instead"
                )
            self.http = ProviderHttpClient(
                source_id=SOURCE_ID,
                policy_registry=policy_registry,
                scope=SCOPE,
                mode=LIVE_MODE,
                base_url=settings.polymarket_gamma_base_url,
                transport=transport,
                clock=clock or time.monotonic,
                sleeper=sleeper or time.sleep,
                requests_per_minute=60,
            )

    def close(self) -> None:
        if self.http is not None:
            self.http.close()

    def _read_fixture(self, name: str) -> bytes:
        self.last_payload_bytes = self.store.read_bytes(name)
        return self.last_payload_bytes

    def _events_payload(self) -> list[dict[str, Any]]:
        if self.mode == LIVE_MODE:
            assert self.http is not None
            result = self.http.get(
                "/events", params={"tag": self.live_search_tag, "closed": "false"}
            )
            self.last_payload_bytes = result.content
            payload = parse_json_bytes(result.content, where="gamma events")
        else:
            payload = parse_json_bytes(
                self._read_fixture(GAMMA_EVENTS_FIXTURE), where="gamma events"
            )
        if isinstance(payload, dict):
            payload = require_list(
                require_field(payload, "events", where="events"), where="gamma events"
            )
        return [
            require_object(row, where="gamma events[]")
            for row in require_list(payload, where="gamma events")
        ]

    def discover_events(
        self, *, lookahead_hours: int = 72, limit: int | None = None
    ) -> list[ProviderEvent]:
        events: list[ProviderEvent] = []
        for row in self._events_payload():
            parsed = _parse_gamma_event(row, self)
            if parsed is not None:
                events.append(parsed)
        return events[:limit] if limit is not None else events

    def fetch_event(self, provider_event_id: str) -> ProviderEvent | None:
        return next(
            (e for e in self.discover_events() if e.provider_event_id == provider_event_id), None
        )

    def fetch_markets(self, provider_event_id: str) -> list[ProviderMarket]:
        markets: list[ProviderMarket] = []
        for row in self._events_payload():
            if str(row.get("slug") or row.get("id") or "") != provider_event_id:
                continue
            markets.extend(_parse_gamma_markets(row, self, "/events"))
        return markets

    def stream_updates(self) -> Any:
        """Yield every discovered market once (documented polling path).

        The WebSocket channel exists for subscribers, but the MVP uses paced
        public reads so that every price is archived with its raw payload.
        """
        yield from (
            market
            for event in self.discover_events()
            for market in self.fetch_markets(event.provider_event_id)
        )

    def healthcheck(self) -> HealthReport:
        checked_at = utcnow()
        if self.mode == FIXTURE_MODE or self.http is None:
            return HealthReport(
                source_id=SOURCE_ID,
                ok=True,
                mode=FIXTURE_MODE,
                checked_at=checked_at,
                detail="fixture mode: labelled frozen payload, no network",
                is_synthetic=True,
            )
        result = self.http.get("/events", params={"limit": 1, "closed": "false"})
        row_count = len(parse_json_bytes(result.content, where="gamma ping"))
        return HealthReport(
            source_id=SOURCE_ID,
            ok=True,
            mode=LIVE_MODE,
            checked_at=checked_at,
            latency_ms=result.elapsed_ms,
            detail=f"live (sampled events: {row_count})",
        )
