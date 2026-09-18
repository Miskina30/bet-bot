"""Demo seed: labelled synthetic fixture universe (keyless demo, no network).

Creates a canonical dataset where every row is ``is_synthetic=True`` and every
venue name is prefixed ``FIXTURE:``. Refuses to run against a DB URL that does
not look local, because synthetic demo data must never reach a shared database.
"""

from __future__ import annotations

import datetime as dt
import zlib
from decimal import Decimal
from typing import Any

from academic_edge_domain.db import Base
from academic_edge_domain.settings import get_settings
from academic_edge_domain.time import utcnow


def seed_database(*, db_url: str | None = None) -> dict[str, int]:
    """Populate the database with labelled synthetic demo data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    settings = get_settings()
    url = db_url or settings.resolve_db_url()
    _refuse_production(url)
    engine = create_engine(url, echo=False)
    import academic_edge_domain.models  # noqa: F401  (registers tables on Base)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        counts = _seed(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    engine.dispose()
    return counts


def _refuse_production(db_url: str) -> None:
    lowered = db_url.lower()
    if "sqlite" not in lowered and "localhost" not in lowered and "127.0.0.1" not in lowered:
        raise RuntimeError(f"seed refuses {db_url!r}: demo data is synthetic.")


def _fixture_price(source_id: str, outcome_kind: str) -> Decimal:
    """Deterministic pseudo-price: crc32 is stable across processes, so the
demo is reproducible. Never pretend this is a live market."""
    key = f"{source_id}:{outcome_kind}".encode()
    return Decimal("2.0") + Decimal(str((zlib.crc32(key) % 90) / 100.0))

def _seed(session: Any) -> dict[str, int]:
    from academic_edge_domain.enums import (
        AlertSeverity,
        FreshnessLabel,
        MarketPeriod,
        MarketType,
        OutcomeKind,
        Sport,
        TeamScope,
        VenueKind,
    )
    from academic_edge_domain.models import (
        AlertRule,
        AuditLog,
        Competition,
        Event,
        Market,
        Outcome,
        Participant,
        Quote,
        Season,
        SportRow,
        Venue,
    )
    from academic_edge_domain.policy import load_registry, sync_registry_to_db

    now = utcnow()
    counts: dict[str, int] = {}

    registry = load_registry()
    sync_registry_to_db(session, registry)
    counts["source_policies"] = len(registry.policies)

    sport = SportRow(code=Sport.FOOTBALL, name="Association Football")
    session.add(sport)
    session.flush()

    comp1 = Competition(
        sport_id=sport.id, canonical_key="premier-league", name="Premier League",
        country="England", is_synthetic=True,
    )
    comp2 = Competition(
        sport_id=sport.id, canonical_key="serie-a", name="Serie A",
        country="Italy", is_synthetic=True,
    )
    session.add_all([comp1, comp2])
    session.flush()

    season1 = Season(competition_id=comp1.id, label="2025/26", is_current=True)
    season2 = Season(competition_id=comp2.id, label="2025/26", is_current=True)
    session.add_all([season1, season2])
    session.flush()

    venue1 = Venue(
        canonical_key="old-trafford", name="FIXTURE: Old Trafford",
        city="Manchester", country="England",
    )
    venue2 = Venue(
        canonical_key="san-siro", name="FIXTURE: San Siro",
        city="Milan", country="Italy",
    )
    session.add_all([venue1, venue2])
    session.flush()

    teams = [
        ("Manchester United", "England"),
        ("Manchester City", "England"),
        ("Inter", "Italy"),
        ("Juventus", "Italy"),
        ("Arsenal", "England"),
        ("Liverpool", "England"),
        ("AC Milan", "Italy"),
        ("Napoli", "Italy"),
    ]
    participants: dict[str, Any] = {}
    for name, country in teams:
        participant = Participant(
            sport_id=sport.id,
            canonical_key=name.lower().replace(" ", "-"),
            name=name,
            short_name=name[:3].upper(),
            country=country,
            is_synthetic=True,
        )
        session.add(participant)
        participants[name] = participant
    session.flush()
    counts["participants"] = len(participants)
    kickoff = now.replace(hour=15, minute=0, second=0, microsecond=0)
    event_specs = [
        ("Manchester United", "Manchester City", venue1, kickoff, comp1, season1),
        ("Inter", "Juventus", venue2, kickoff, comp2, season2),
        ("Arsenal", "Liverpool", venue1, kickoff + dt.timedelta(days=1), comp1, season1),
        ("AC Milan", "Napoli", venue2, kickoff + dt.timedelta(days=1), comp2, season2),
    ]
    events: list[Any] = []
    for home_name, away_name, venue, start, comp, season in event_specs:
        event = Event(
            sport_id=sport.id,
            competition_id=comp.id,
            season_id=season.id,
            home_participant_id=participants[home_name].id,
            away_participant_id=participants[away_name].id,
            venue_id=venue.id,
            start_time_utc=start,
            status="scheduled",
            is_synthetic=True,
        )
        session.add(event)
        events.append(event)
    session.flush()
    counts["events"] = len(events)

    market_specs = [
        (MarketType.FT_1X2, [OutcomeKind.HOME, OutcomeKind.DRAW, OutcomeKind.AWAY]),
        (MarketType.FT_TOTALS_2_5, [OutcomeKind.OVER, OutcomeKind.UNDER]),
        (MarketType.FT_BTTS, [OutcomeKind.YES, OutcomeKind.NO]),
    ]
    quote_venues = [
        ("api_football", VenueKind.BOOKMAKER, "FIXTURE: Bookmaker Alpha"),
        ("polymarket_gamma", VenueKind.PREDICTION_MARKET, "FIXTURE: Polymarket"),
    ]

    markets_created = 0
    outcomes_created = 0
    quotes_created = 0
    for event in events:
        for market_type, kinds in market_specs:
            line = (
                Decimal("2.5")
                if market_type == MarketType.FT_TOTALS_2_5
                else Decimal("0")
            )
            identity = (
                f"{event.id}:{market_type.value}:full_time:{line}"
                ":neutral:false:v1"
            )
            market = Market(
                event_id=event.id,
                sport_id=event.sport_id,
                market_type=market_type,
                period=MarketPeriod.FULL_TIME,
                line_value=line,
                team_scope=TeamScope.NEUTRAL,
                overtime_included=False,
                settlement_version="v1",
                identity_key=identity,
                settlement_rule="Full-time result excluding extra time.",
                display_name=market_type.value,
                is_synthetic=True,
            )
            session.add(market)
            session.flush()
            markets_created += 1

            outcomes = [
                Outcome(market_id=market.id, outcome_kind=kind, label=kind.value)
                for kind in kinds
            ]
            session.add_all(outcomes)
            session.flush()
            outcomes_created += len(outcomes)

            for source_id, venue_kind, venue_name in quote_venues:
                for outcome in outcomes:
                    session.add(
                        Quote(
                            market_id=market.id,
                            outcome_id=outcome.id,
                            source_id=source_id,
                            venue_kind=venue_kind,
                            venue_name=venue_name,
                            decimal_odds=_fixture_price(
                                source_id, str(outcome.outcome_kind)
                            ),
                            currency="EUR",
                            observed_at=now - dt.timedelta(seconds=30),
                            received_at=now,
                            freshness=FreshnessLabel.FRESH,
                            is_synthetic=True,
                        )
                    )
                    quotes_created += 1
    session.flush()
    counts["markets"] = markets_created
    counts["outcomes"] = outcomes_created
    counts["quotes"] = quotes_created

    session.add(
        AlertRule(
            name="default_arb",
            description="Alert on arbitrage opportunities",
            opportunity_types=["arbitrage"],
            market_types=["ft_1x2", "ft_totals_2_5", "ft_btts"],
            min_net_edge_bps=0,
            min_confidence=0.5,
            max_quote_age_seconds=300,
            severity=AlertSeverity.ACTIONABLE,
            created_by="system",
        )
    )
    counts["alert_rules"] = 1

    session.add(
        AuditLog(
            action="manual_import",
            actor="system",
            occurred_at=now,
            detail={"action": "seed", "events": len(events), "synthetic": True},
        )
    )
    session.flush()
    return counts
