"""football-data.org adapter (v4, official API only).

Used as a secondary *identity* source: competitions, fixtures, results and
standings cross-check event resolution. The vendor does not expose odds, so
:meth:`FootballDataOrgAdapter.fetch_markets` returns an empty list -- and says
so -- rather than inventing a price.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from academic_edge_domain.enums import AutomationScope
from academic_edge_domain.settings import Settings
from academic_edge_domain.time import parse_timestamp, utcnow

from academic_edge_connectors.contracts import (
    HealthReport,
    ProviderAdapter,
    ProviderEvent,
    ProviderMarket,
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
    parse_json_bytes,
    require_field,
    require_int,
    require_list,
    require_object,
    require_str,
)

SOURCE_ID = "football_data_org"
SCOPE = AutomationScope.OFFICIAL_API_ONLY
FIXTURE_NAME = "football_data_org_matches.json"


def _parse_match(
    raw: Mapping[str, Any], source_id: str, raw_bytes: bytes | None, fixture: bool
) -> ProviderEvent:
    competition = require_object(
        require_field(raw, "competition", where="competition"), where="match.competition"
    )
    season = require_object(raw.get("season") or {}, where="match.season")
    home = require_object(require_field(raw, "homeTeam", where="homeTeam"), where="match.homeTeam")
    away = require_object(require_field(raw, "awayTeam", where="awayTeam"), where="match.awayTeam")
    score = require_object(raw.get("score") or {}, where="match.score")
    full_time = score.get("fullTime")

    def _pid(team: Mapping[str, Any]) -> str | None:
        return str(team.get("id")) if team.get("id") is not None else None

    area = competition.get("area")
    observed_at = utcnow()
    return ProviderEvent(
        provider_event_id=str(require_int(raw, "id", where="id")),
        competition_name=require_str(competition, "name", where="name"),
        competition_provider_id=str(competition.get("id"))
        if competition.get("id") is not None
        else None,
        home_name=require_str(home, "name", where="name"),
        away_name=require_str(away, "name", where="name"),
        start_time_utc=parse_timestamp(require_field(raw, "utcDate", where="utcDate")),
        home_provider_id=_pid(home),
        away_provider_id=_pid(away),
        venue_name=None,  # v4 exposes no venue names: record None, not a guess
        country=area if isinstance(area, str) else None,
        season_label=str(season.get("startDate", "") or "") or None,
        round_label=f"Matchday {raw['matchday']}" if raw.get("matchday") is not None else None,
        status=require_str(raw, "status", where="status"),
        home_score=full_time.get("home") if isinstance(full_time, dict) else None,
        away_score=full_time.get("away") if isinstance(full_time, dict) else None,
        provenance=build_provenance(
            source_id=source_id,
            endpoint="/competitions/{code}/matches",
            observed_at=observed_at,
            received_at=observed_at,
            raw_bytes=raw_bytes,
            is_synthetic=fixture,
        ),
    )


class FootballDataOrgAdapter(ProviderAdapter):
    """Event/identity adapter. ``fetch_markets`` is intentionally empty."""

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
        competition_code: str = "PL",
    ) -> None:
        if mode not in {LIVE_MODE, FIXTURE_MODE}:
            raise ValueError(f"mode must be 'live' or 'fixture', got {mode!r}")
        self.settings = settings
        self.mode = mode
        self.competition_code = competition_code
        self.store = fixture_store or FixtureStore(overrides=overrides, source_id=SOURCE_ID)
        self.last_payload_bytes: bytes | None = None
        self.http: ProviderHttpClient | None = None

        if mode == LIVE_MODE:
            if not settings.football_data_org_token:
                raise AdapterUnavailable(
                    f"{SOURCE_ID}: FOOTBALL_DATA_ORG_TOKEN is empty; build the "
                    "adapter in fixture mode instead (never fake live data)"
                )
            self.http = ProviderHttpClient(
                source_id=SOURCE_ID,
                policy_registry=policy_registry,
                scope=SCOPE,
                mode=LIVE_MODE,
                base_url=settings.football_data_org_base_url,
                default_headers={"X-Auth-Token": settings.football_data_org_token},
                transport=transport,
                clock=clock or time.monotonic,
                sleeper=sleeper or time.sleep,
                requests_per_minute=settings.football_data_org_rate_limit_per_min,
            )

    def close(self) -> None:
        if self.http is not None:
            self.http.close()

    def _read_fixture(self) -> bytes:
        self.last_payload_bytes = self.store.read_bytes(FIXTURE_NAME)
        return self.last_payload_bytes

    def _parse_rows(self, payload: bytes) -> list[ProviderEvent]:
        document = parse_json_bytes(payload, where="matches")
        rows = require_list(
            require_field(document, "matches", where="matches"), where="matches.matches"
        )
        return [
            _parse_match(
                require_object(row, where="matches[]"),
                SOURCE_ID,
                self.last_payload_bytes,
                self.mode == FIXTURE_MODE,
            )
            for row in rows
        ]

    def discover_events(
        self, *, lookahead_hours: int = 72, limit: int | None = None
    ) -> list[ProviderEvent]:
        if self.mode == LIVE_MODE:
            assert self.http is not None
            today = utcnow().date()
            result = self.http.get(
                f"/competitions/{self.competition_code}/matches",
                params={
                    "dateFrom": today.isoformat(),
                    "dateTo": (today + dt.timedelta(hours=lookahead_hours)).isoformat(),
                },
            )
            self.last_payload_bytes = result.content
            events = self._parse_rows(result.content)
        else:
            events = self._parse_rows(self._read_fixture())
        return events[:limit] if limit is not None else events

    def fetch_event(self, provider_event_id: str) -> ProviderEvent | None:
        if self.mode == LIVE_MODE:
            assert self.http is not None
            result = self.http.get(f"/matches/{provider_event_id}")
            self.last_payload_bytes = result.content
            row = parse_json_bytes(result.content, where="match")
            return _parse_match(
                require_object(row, where="match"), SOURCE_ID, result.content, False
            )
        return next(
            (e for e in self.discover_events() if e.provider_event_id == provider_event_id), None
        )

    def fetch_markets(self, provider_event_id: str) -> list[ProviderMarket]:
        """football-data.org exposes no odds; this is intentionally empty."""
        return []

    def stream_updates(self) -> Any:
        """Yield every discovered event once (v4 has no push channel)."""
        yield from self.discover_events()

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
        result = self.http.get("/competitions")
        remaining = result.headers.get("x-requests-minute-remaining")
        return HealthReport(
            source_id=SOURCE_ID,
            ok=True,
            mode=LIVE_MODE,
            checked_at=checked_at,
            latency_ms=result.elapsed_ms,
            quota_remaining=int(remaining) if remaining is not None else None,
            detail="live",
        )
