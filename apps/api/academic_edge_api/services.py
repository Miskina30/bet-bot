"""Shared query helpers: canonical rows -> response schemas.

Every mapper keeps the contract's promises: UUIDs as strings only at the
serialisation edge, decimals as strings, UTC timestamps, and ``is_synthetic``
always present. Nothing builds a response from raw provider bytes.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from academic_edge_domain import models
from academic_edge_domain.enums import FreshnessLabel
from academic_edge_domain.time import seconds_between, utcnow


def event_provider_ids(session: Session, event_id: uuid.UUID) -> dict[str, str]:
    """source_id -> provider event id for one canonical event."""
    rows = session.scalars(
        select(models.ProviderEventMap).where(
            models.ProviderEventMap.canonical_event_id == event_id
        )
    ).all()
    return {row.source_id: row.provider_event_id for row in rows}


def lookup_names(
    session: Session, event: models.Event
) -> tuple[str, str, str, str | None, str | None]:
    """(competition, home, away, venue, season) display names for an event."""
    competition = session.get(models.Competition, event.competition_id)
    home = session.get(models.Participant, event.home_participant_id)
    away = session.get(models.Participant, event.away_participant_id)
    venue = session.get(models.Venue, event.venue_id) if event.venue_id else None
    season = session.get(models.Season, event.season_id) if event.season_id else None
    return (
        competition.name if competition else "?",
        home.name if home else "?",
        away.name if away else "?",
        venue.name if venue else None,
        season.label if season else None,
    )


def freshness_of(observed_at: dt.datetime, now: dt.datetime, max_age_seconds: int) -> FreshnessLabel:
    """fresh (< 1/3), aging (< window), stale (>= window)."""
    age = max(0.0, seconds_between(now, observed_at))
    third = max_age_seconds / 3.0
    if age < third:
        return FreshnessLabel.FRESH
    if age < max_age_seconds:
        return FreshnessLabel.AGING
    return FreshnessLabel.STALE


def competition_name_by_id(session: Session, competition_id: uuid.UUID) -> str:
    row = session.get(models.Competition, competition_id)
    return row.name if row else "?"


def outcome_counts(session: Session, market_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count()).select_from(models.Outcome).where(models.Outcome.market_id == market_id)
        )
        or 0
    )


def latest_quotes(
    session: Session, market_id: uuid.UUID, as_of: dt.datetime
) -> list[models.Quote]:
    """Newest quote per outcome for one market (as of ``as_of``)."""
    quotes = (
        session.scalars(
            select(models.Quote)
            .where(models.Quote.market_id == market_id, models.Quote.observed_at <= as_of)
            .order_by(models.Quote.observed_at.desc())
        )
        .all()
    )
    seen: set[uuid.UUID] = set()
    newest: list[models.Quote] = []
    for quote in quotes:
        if quote.outcome_id in seen:
            continue
        seen.add(quote.outcome_id)
        newest.append(quote)
    return sorted(newest, key=lambda q: str(q.outcome_id))