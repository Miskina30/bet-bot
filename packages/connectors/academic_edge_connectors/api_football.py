"""API-Football (api-sports.io) adapter -- official API only.

Bet-id mapping (documented vendor ids, v3):
    1 -> Match Winner            -> FT_1X2       (home/draw/away)
    5 -> Goals Over/Under        -> FT_TOTALS_2_5 (line 2.5 only)
    8 -> Both Teams Score        -> FT_BTTS      (yes/no)

Fixture mode reads a labelled frozen payload via ``FixtureStore`` and never
opens a socket; live mode is gated by the source policy registry. Missing or
renamed provider fields raise :class:`ParserDriftError`, never a guessed value.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
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
from academic_edge_domain.time import parse_timestamp, utcnow

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
    require_field,
    require_int,
    require_list,
    require_object,
    require_odds,
    require_str,
)

SOURCE_ID = "api_football"
SCOPE = AutomationScope.OFFICIAL_API_ONLY
#: vendor bet id -> (canonical market, label -> canonical outcome)
BET_MAP: dict[int, tuple[MarketType, dict[str, OutcomeKind]]] = {
    1: (
        MarketType.FT_1X2,
        {"Home": OutcomeKind.HOME, "Draw": OutcomeKind.DRAW, "Away": OutcomeKind.AWAY},
    ),
    8: (MarketType.FT_BTTS, {"Yes": OutcomeKind.YES, "No": OutcomeKind.NO}),
}
TOTALS_LABELS = {"Over": OutcomeKind.OVER, "Under": OutcomeKind.UNDER}
TOTALS_LINE = Decimal("2.5")
FIXTURE_NAME = "api_football_fixtures.json"
ODDS_FIXTURE_NAME = "api_football_odds.json"


class ApiFootballAdapter(ProviderAdapter):
    """``discover_events`` / ``fetch_event`` / ``fetch_markets`` / ``healthcheck``.

    ``stream_updates`` is a documented *polling* generator over
    ``fetch_markets``: the vendor's free tier does not offer push odds updates,
    and inventing a websocket would mean inventing a provider capability.
    """

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
        lookahead_days: int = 7,
    ) -> None:
        if mode not in {LIVE_MODE, FIXTURE_MODE}:
            raise ValueError(f"mode must be 'live' or 'fixture', got {mode!r}")
        self.settings = settings
        self.mode = mode
        self.lookahead_days = lookahead_days
        self.store = fixture_store or FixtureStore(overrides=overrides, source_id=SOURCE_ID)
        self.last_payload_bytes: bytes | None = None
        self.http: ProviderHttpClient | None = None

        if mode == LIVE_MODE:
            if not settings.api_football_key:
                raise AdapterUnavailable(
                    f"{SOURCE_ID}: API_FOOTBALL_KEY is empty; build the adapter in "
                    "fixture mode instead (never fake live data)"
                )
            self.http = ProviderHttpClient(
                source_id=SOURCE_ID,
                policy_registry=policy_registry,
                scope=SCOPE,
                mode=LIVE_MODE,
                base_url=settings.api_football_base_url,
                default_headers={"x-apisports-key": settings.api_football_key},
                transport=transport,
                clock=clock or time.monotonic,
                sleeper=sleeper or time.sleep,
                requests_per_minute=10,
            )

    def close(self) -> None:
        if self.http is not None:
            self.http.close()

    # -- parsing -------------------------------------------------------------

    def _parse_fixture(self, raw: Mapping[str, Any], endpoint: str) -> ProviderEvent:
        fixture = require_object(
            require_field(raw, "fixture", where="fixture"), where="fixtures[].fixture"
        )
        league = require_object(
            require_field(raw, "league", where="league"), where="fixtures[].league"
        )
        teams = require_object(require_field(raw, "teams", where="teams"), where="fixtures[].teams")
        home = require_object(require_field(teams, "home", where="home"), where="teams.home")
        away = require_object(require_field(teams, "away", where="away"), where="teams.away")
        venue = raw.get("fixture") or {}
        score = raw.get("score") or {}
        full_time = score.get("fulltime") if isinstance(score, dict) else None

        observed_at = utcnow()
        return ProviderEvent(
            provider_event_id=str(require_int(fixture, "id", where="id")),
            competition_name=require_str(league, "name", where="name"),
            competition_provider_id=(
                str(league.get("id")) if league.get("id") is not None else None
            ),
            home_name=require_str(home, "name", where="name"),
            away_name=require_str(away, "name", where="name"),
            start_time_utc=parse_timestamp(require_field(fixture, "date", where="date")),
            home_provider_id=str(home.get("id")) if home.get("id") is not None else None,
            away_provider_id=str(away.get("id")) if away.get("id") is not None else None,
            venue_name=(venue.get("venue") or {}).get("name") if isinstance(venue, dict) else None,
            country=league.get("country"),
            season_label=str(league.get("season")) if league.get("season") is not None else None,
            round_label=league.get("round"),
            status=str((fixture.get("status") or {}).get("short", "NS")),
            home_score=full_time.get("home") if isinstance(full_time, dict) else None,
            away_score=full_time.get("away") if isinstance(full_time, dict) else None,
            provenance=build_provenance(
                source_id=SOURCE_ID,
                endpoint=endpoint,
                observed_at=observed_at,
                received_at=observed_at,
                provider_timestamp=optional_timestamp(fixture, "update", where="update"),
                raw_bytes=self.last_payload_bytes,
                is_synthetic=self.mode == FIXTURE_MODE,
            ),
        )

    def _parse_fixture_list(self, payload: bytes, endpoint: str) -> list[ProviderEvent]:
        document = parse_json_bytes(payload, where="fixtures")
        rows = require_list(
            require_field(document, "response", where="response"), where="fixtures.response"
        )
        return [
            self._parse_fixture(require_object(row, where="fixtures[]"), endpoint) for row in rows
        ]

    def _parse_odds(
        self, payload: bytes, provider_event_id: str, endpoint: str
    ) -> list[ProviderMarket]:
        document = parse_json_bytes(payload, where="odds")
        response = require_list(
            require_field(document, "response", where="response"), where="odds.response"
        )
        observed_at = utcnow()
        markets: dict[MarketType, dict[OutcomeKind, ProviderOutcome]] = {}

        for entry in response:
            entry_obj = require_object(entry, where="odds[]")
            if str(require_int(entry_obj, "fixture", where="fixture")) != provider_event_id:
                continue
            for bookmaker in require_list(entry_obj.get("bookmakers", []), where="bookmakers"):
                book = require_object(bookmaker, where="bookmakers[]")
                for bet in require_list(book.get("bets", []), where="bets"):
                    bet_obj = require_object(bet, where="bets[]")
                    bet_id = require_int(bet_obj, "id", where="id")
                    if bet_id == 5:
                        mapped_type = MarketType.FT_TOTALS_2_5
                        label_map = TOTALS_LABELS
                    elif bet_id in BET_MAP:
                        mapped_type, label_map = BET_MAP[bet_id]
                    else:
                        continue  # out-of-scope market family: skip, never guess
                    for item in require_list(bet_obj.get("values", []), where="values"):
                        value = require_object(item, where="values[]")
                        label = require_str(value, "value", where="value")
                        if mapped_type is MarketType.FT_TOTALS_2_5:
                            line_raw = value.get("line")
                            if line_raw is not None and abs(float(line_raw) - 2.5) > 1e-9:
                                continue  # only the 2.5 line is in scope
                        outcome_kind = label_map.get(label)
                        if outcome_kind is None:
                            continue
                        odds = require_odds(value.get("odd"), where="values[].odd")
                        current = markets.setdefault(mapped_type, {})
                        # best price per outcome across bookmakers
                        if outcome_kind not in current or odds > current[outcome_kind].decimal_odds:
                            current[outcome_kind] = ProviderOutcome(
                                outcome_kind=outcome_kind,
                                decimal_odds=odds,
                                provider_outcome_id=None,
                                extras={"label": label},
                            )

        provenance = build_provenance(
            source_id=SOURCE_ID,
            endpoint=endpoint,
            observed_at=observed_at,
            received_at=observed_at,
            raw_bytes=payload,
            is_synthetic=self.mode == FIXTURE_MODE,
        )
        return [
            ProviderMarket(
                provider_event_id=provider_event_id,
                provider_market_id=f"{provider_event_id}:{market_type.value}",
                venue_name="API-Football aggregated bookmakers",
                venue_kind=VenueKind.BOOKMAKER,
                market_type=market_type,
                outcomes=tuple(outcomes.values()),
                period=MarketPeriod.FULL_TIME,
                team_scope=TeamScope.NEUTRAL,
                line=(TOTALS_LINE if market_type is MarketType.FT_TOTALS_2_5 else Decimal("0")),
                observed_at=observed_at,
                is_synthetic=self.mode == FIXTURE_MODE,
                provenance=provenance,
                extras={
                    "settlement_rule": "Full-time result incl. stoppage time, excl. extra time."
                },
            )
            for market_type, outcomes in sorted(markets.items(), key=lambda item: item[0].value)
        ]

    # -- adapter surface -------------------------------------------------------

    def _read_fixture(self, name: str) -> bytes:
        self.last_payload_bytes = self.store.read_bytes(name)
        return self.last_payload_bytes

    def discover_events(
        self, *, lookahead_hours: int = 72, limit: int | None = None
    ) -> list[ProviderEvent]:
        if self.mode == LIVE_MODE:
            assert self.http is not None
            today = utcnow().date()
            result = self.http.get(
                "/fixtures",
                params={
                    "from": today.isoformat(),
                    "to": (today + dt.timedelta(days=self.lookahead_days)).isoformat(),
                },
            )
            self.last_payload_bytes = result.content
            events = self._parse_fixture_list(result.content, "/fixtures")
        else:
            events = self._parse_fixture_list(self._read_fixture(FIXTURE_NAME), "/fixtures")
        return events[:limit] if limit is not None else events

    def fetch_event(self, provider_event_id: str) -> ProviderEvent | None:
        if self.mode == LIVE_MODE:
            assert self.http is not None
            result = self.http.get("/fixtures", params={"id": provider_event_id})
            self.last_payload_bytes = result.content
            events = self._parse_fixture_list(result.content, "/fixtures?id=")
        else:
            events = self._parse_fixture_list(self._read_fixture(FIXTURE_NAME), "/fixtures?id=")
        return next((e for e in events if e.provider_event_id == provider_event_id), None)

    def fetch_markets(self, provider_event_id: str) -> list[ProviderMarket]:
        if self.mode == LIVE_MODE:
            assert self.http is not None
            result = self.http.get("/odds", params={"fixture": provider_event_id})
            return self._parse_odds(result.content, provider_event_id, "/odds")
        return self._parse_odds(self._read_fixture(ODDS_FIXTURE_NAME), provider_event_id, "/odds")

    def stream_updates(self) -> Any:
        """Yield every discovered market once (free tier has no push odds)."""
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
        result = self.http.get("/status")
        payload = parse_json_bytes(result.content, where="status")
        requests = require_object(
            require_field(payload, "response", where="response"), where="status.response"
        )
        return HealthReport(
            source_id=SOURCE_ID,
            ok=True,
            mode=LIVE_MODE,
            checked_at=checked_at,
            latency_ms=result.elapsed_ms,
            quota_remaining=None,
            detail=f"live (requests/day cap observed={requests})",
        )
