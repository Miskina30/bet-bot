"""Contract tests: adapters must parse frozen, redacted provider payloads.

These tests pin the provider contract. If a vendor renames a field, the test
fails with :class:`ParserDriftError` exactly where parsing gave up -- and the
raw payload is still archived by the pipeline, so drift stays diagnosable.
No test here touches the network: ``FixtureStore`` reads local files, or
``overrides=`` injects payload bytes directly.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from academic_edge_connectors import registry
from academic_edge_connectors.api_football import ApiFootballAdapter
from academic_edge_connectors.contracts import ParserDriftError
from academic_edge_connectors.football_data_org import FootballDataOrgAdapter
from academic_edge_connectors.http import FIXTURE_MODE
from academic_edge_connectors.parsing import require_field
from academic_edge_connectors.polymarket import (
    PolymarketAdapter,
    classify_gamma_market,
    price_to_decimal_odds,
    sides_from_title,
)
from academic_edge_domain.enums import MarketType, OutcomeKind, VenueKind
from academic_edge_domain.policy import PolicyViolation, load_registry
from academic_edge_domain.settings import Settings

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

pytestmark = pytest.mark.contract


def _settings() -> Settings:
    return Settings()


def _registry() -> Any:
    return load_registry()


class TestApiFootballContract:
    def test_discovers_fixture_events(self) -> None:
        adapter = ApiFootballAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        events = adapter.discover_events()
        assert len(events) == 2
        first = events[0]
        assert first.provider_event_id == "1036371"
        assert first.home_name == "Manchester United"
        assert first.start_time_utc.tzinfo is not None
        assert first.provenance is not None and first.provenance.is_synthetic

    def test_fetches_one_event(self) -> None:
        adapter = ApiFootballAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        event = adapter.fetch_event("1036372")
        assert event is not None
        assert event.competition_name == "Serie A"
        assert adapter.fetch_event("no-such-fixture") is None

    def test_maps_only_in_scope_markets(self) -> None:
        adapter = ApiFootballAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        markets = adapter.fetch_markets("1036371")
        types = {m.market_type for m in markets}
        assert types == {MarketType.FT_1X2, MarketType.FT_TOTALS_2_5, MarketType.FT_BTTS}
        by_type = {m.market_type: m for m in markets}
        # best price across the two bookmakers wins
        one_x_two = {o.outcome_kind: o.decimal_odds for o in by_type[MarketType.FT_1X2].outcomes}
        assert one_x_two == {
            OutcomeKind.HOME: Decimal("2.20"),
            OutcomeKind.DRAW: Decimal("3.50"),
            OutcomeKind.AWAY: Decimal("3.28"),
        }
        # the 1.5 totals line is skipped; the 2.5 line is kept
        assert by_type[MarketType.FT_TOTALS_2_5].line == Decimal("2.5")

    def test_drift_raises_instead_of_guessing(self) -> None:
        payload = json.loads((FIXTURES / "api_football_fixtures.json").read_text(encoding="utf-8"))
        del payload["response"][0]["fixture"]["date"]  # vendor renamed a field
        import academic_edge_connectors.fixture_io as fixture_io

        store = fixture_io.FixtureStore(
            overrides={"api_football_fixtures.json": json.dumps(payload).encode()},
            source_id="api_football",
        )
        adapter = ApiFootballAdapter(
            _settings(), _registry(), mode=FIXTURE_MODE, fixture_store=store
        )
        with pytest.raises(ParserDriftError):
            adapter.discover_events()

    def test_missing_key_refuses_live(self) -> None:
        from academic_edge_connectors.http import AdapterUnavailable

        with pytest.raises(AdapterUnavailable):
            ApiFootballAdapter(_settings(), _registry(), mode="live")

    def test_require_helpers_reject_bad_types(self) -> None:
        with pytest.raises(ParserDriftError):
            require_field({"a": 1}, "missing", where="missing")


class TestFootballDataOrgContract:
    def test_discovers_matches_and_has_no_odds(self) -> None:
        adapter = FootballDataOrgAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        events = adapter.discover_events()
        assert len(events) == 2
        assert events[0].provider_event_id == "540011"
        assert events[0].round_label == "Matchday 28"
        # no odds capability: documented empty list, not an error
        assert adapter.fetch_markets("540011") == []

    def test_fetch_event(self) -> None:
        adapter = FootballDataOrgAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        assert adapter.fetch_event("540012") is not None
        assert adapter.fetch_event("0") is None


class TestPolymarketContract:
    def test_classification_is_conservative(self) -> None:
        assert classify_gamma_market("Will both teams to score in X vs Y?") is MarketType.FT_BTTS
        assert classify_gamma_market("Inter to win vs Juventus") is MarketType.FT_1X2
        assert classify_gamma_market("Who will win the league?") is None
        assert classify_gamma_market("") is None

    def test_price_conversion_rejects_degenerate_prices(self) -> None:
        assert price_to_decimal_odds("0.62") == Decimal("1.612903")
        for bad in ("0", "1", "1.5", "-0.2", "", "n/a", None):
            assert price_to_decimal_odds(bad) is None

    def test_sides_extracted_from_fixture_titles_only(self) -> None:
        assert sides_from_title("Manchester Utd vs Manchester City") == (
            "Manchester Utd",
            "Manchester City",
        )
        assert sides_from_title("Inter v Juventus") == ("Inter", "Juventus")
        assert sides_from_title("Who will win the league?") is None

    def test_nested_gamma_markets_parse_with_evidence(self) -> None:
        adapter = PolymarketAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        events = adapter.discover_events()
        assert len(events) == 2
        markets = adapter.fetch_markets("man-utd-vs-man-city-mar-14")
        assert len(markets) == 1  # the outright was skipped, not forced
        market = markets[0]
        assert market.market_type is MarketType.FT_BTTS
        assert market.venue_kind is VenueKind.PREDICTION_MARKET
        assert {o.outcome_kind for o in market.outcomes} == {OutcomeKind.YES, OutcomeKind.NO}
        assert market.extras["question"].startswith("Will both teams")
        italian = adapter.fetch_markets("inter-vs-juventus-mar-14")
        assert len(italian) == 1
        assert italian[0].market_type is MarketType.FT_1X2

    def test_yes_price_becomes_single_mappable_side(self) -> None:
        adapter = PolymarketAdapter(_settings(), _registry(), mode=FIXTURE_MODE)
        market = adapter.fetch_markets("inter-vs-juventus-mar-14")[0]
        assert len(market.outcomes) == 1
        [side] = market.outcomes
        assert side.outcome_kind is OutcomeKind.HOME
        assert side.decimal_odds == Decimal("2.272727")


class TestRegistryGates:
    def test_unknown_source_refused(self) -> None:
        with pytest.raises(PolicyViolation):
            registry.build_adapter("unknown_source")

    def test_crocobet_live_refused_but_manual_allowed(self) -> None:
        with pytest.raises(PolicyViolation):
            registry.build_adapter("crocobet", mode="live")
        adapter = registry.build_adapter("crocobet", mode=FIXTURE_MODE)
        assert adapter is not None

    def test_mode_summary_runs_keyless(self) -> None:
        summary = registry.adapter_mode_summary(_settings())
        assert summary["crocobet"] == FIXTURE_MODE
        assert summary["api_football"] == FIXTURE_MODE  # no key configured

    def test_fixture_adapters_all_construct(self) -> None:
        adapters = registry.build_fixture_adapters()
        assert set(adapters) >= {"api_football", "football_data_org", "polymarket_gamma"}
        for source_id, adapter in adapters.items():
            if not hasattr(adapter, "healthcheck"):
                continue  # manual-CSV adapter exposes CSV state, not a health ping
            report = adapter.healthcheck()
            assert report.ok and report.mode == FIXTURE_MODE, source_id
