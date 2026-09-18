"""Read endpoints for health, sources, events, markets and quotes."""

from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from academic_edge_api.deps import get_registry, get_session
from academic_edge_api.observability import Timer, log_event, new_correlation_id
from academic_edge_api.pagination import Page, clamp_page_size, decode_request_cursor
from academic_edge_api.schemas import (
    EventOut,
    HealthOut,
    MarketOut,
    QuoteOut,
    SourceHealthOut,
)
from academic_edge_api.security import current_role
from academic_edge_api.services import (
    event_provider_ids,
    freshness_of,
    lookup_names,
)
from academic_edge_api.settings import Settings, get_settings
from academic_edge_domain import models
from academic_edge_domain.db import ping
from academic_edge_domain.ids import encode_cursor
from academic_edge_domain.policy import SourcePolicyRegistry
from academic_edge_domain.time import seconds_between, utcnow

router = APIRouter()


@router.get("/health", response_model=HealthOut, summary="Liveness and mode")
def health(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    role: Annotated[object, Depends(current_role)],
) -> HealthOut:
    return HealthOut(
        ok=True,
        env=settings.academic_edge_env,
        fixture_mode=settings.fixture_only,
        dev_auth=not settings.role_keys,
        database="ok" if ping(session) else "degraded",
        time_utc=utcnow(),
    )


@router.get("/sources/health", response_model=list[SourceHealthOut], summary="Per-source health")
def sources_health(
    session: Annotated[Session, Depends(get_session)],
    registry: Annotated[SourcePolicyRegistry, Depends(get_registry)],
    role: Annotated[object, Depends(current_role)],
) -> list[SourceHealthOut]:
    checked_at = utcnow()
    seen: dict[str, models.SourceHealthSnapshot] = {}
    for snapshot in session.scalars(
        select(models.SourceHealthSnapshot).order_by(
            models.SourceHealthSnapshot.source_id,
            models.SourceHealthSnapshot.checked_at.desc(),
        )
    ).all():
        seen.setdefault(snapshot.source_id, snapshot)

    rows: list[SourceHealthOut] = []
    for policy in registry.enabled_sources():
        snapshot = seen.get(policy.source_id)
        rows.append(
            SourceHealthOut(
                source_id=policy.source_id,
                display_name=policy.display_name,
                ok=snapshot.ok if snapshot else False,
                mode="live" if snapshot and snapshot.mode == "live" else "fixture",
                checked_at=snapshot.checked_at if snapshot else checked_at,
                latency_ms=snapshot.latency_ms if snapshot else None,
                quota_used=snapshot.quota_used if snapshot else None,
                quota_limit=snapshot.quota_limit if snapshot else None,
                parser_drift=bool(snapshot and snapshot.parser_drift_count > 0),
                message=snapshot.message if snapshot else "no health check recorded yet",
            )
        )
    return rows


@router.get("/events", response_model=Page, summary="List canonical events")
def list_events(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    role: Annotated[object, Depends(current_role)],
    competition: str | None = Query(default=None, description="Competition name substring."),
    status: str | None = Query(default=None, description="Event status filter."),
    from_time: dt.datetime | None = Query(default=None, alias="from"),
    to_time: dt.datetime | None = Query(default=None, alias="to"),
    include_synthetic: bool = Query(default=True),
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    size = clamp_page_size(page_size)
    decoded = decode_request_cursor(cursor)
    statement = select(models.Event).order_by(
        models.Event.start_time_utc.desc(), models.Event.id.desc()
    )
    if decoded is not None:
        before, last_id = decoded
        statement = statement.where(
            (models.Event.start_time_utc < before)
            | ((models.Event.start_time_utc == before) & (models.Event.id < last_id))
        )
    if status:
        statement = statement.where(models.Event.status == status)
    if from_time:
        statement = statement.where(models.Event.start_time_utc >= from_time)
    if to_time:
        statement = statement.where(models.Event.start_time_utc <= to_time)
    if not include_synthetic:
        statement = statement.where(models.Event.is_synthetic.is_(False))
    statement = statement.limit(size + 1)

    rows = list(session.scalars(statement).all())
    has_more = len(rows) > size
    rows = rows[:size]

    items: list[dict[str, object]] = []
    for event in rows:
        comp, home, away, venue, season = lookup_names(session, event)
        if competition and competition.casefold() not in comp.casefold():
            continue
        items.append(
            EventOut(
                id=event.id,
                competition=comp,
                season=season,
                home=home,
                away=away,
                venue=venue,
                start_time_utc=event.start_time_utc,
                status=event.status,
                round_label=event.round_label,
                home_score=event.home_score,
                away_score=event.away_score,
                is_synthetic=event.is_synthetic,
                provider_ids=event_provider_ids(session, event.id),
            ).model_dump(mode="json")
        )
    next_cursor = encode_cursor(rows[-1].start_time_utc, rows[-1].id) if has_more and rows else None
    return Page(items=items, next_cursor=next_cursor, partial=False)


@router.get("/events/{event_id}", response_model=EventOut, summary="One canonical event")
def get_event(
    event_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
) -> EventOut:
    event = session.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"event {event_id} not found")
    comp, home, away, venue, season = lookup_names(session, event)
    return EventOut(
        id=event.id,
        competition=comp,
        season=season,
        home=home,
        away=away,
        venue=venue,
        start_time_utc=event.start_time_utc,
        status=event.status,
        round_label=event.round_label,
        home_score=event.home_score,
        away_score=event.away_score,
        is_synthetic=event.is_synthetic,
        provider_ids=event_provider_ids(session, event.id),
    )


@router.get("/markets", response_model=Page, summary="List canonical markets")
def list_markets(
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
    event_id: UUID | None = Query(default=None),
    market_type: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    size = clamp_page_size(page_size)
    decoded = decode_request_cursor(cursor)
    statement = select(models.Market).order_by(
        models.Market.created_at.desc(), models.Market.id.desc()
    )
    if decoded is not None:
        before, last_id = decoded
        statement = statement.where(
            (models.Market.created_at < before)
            | ((models.Market.created_at == before) & (models.Market.id < last_id))
        )
    if event_id:
        statement = statement.where(models.Market.event_id == event_id)
    if market_type:
        statement = statement.where(models.Market.market_type == market_type)
    statement = statement.limit(size + 1)

    rows = list(session.scalars(statement).all())
    has_more = len(rows) > size
    rows = rows[:size]
    items = [
        MarketOut(
            id=market.id,
            event_id=market.event_id,
            market_type=market.market_type,
            period=market.period,
            line_value=str(market.line_value),
            team_scope=market.team_scope,
            overtime_included=market.overtime_included,
            settlement_version=market.settlement_version,
            identity_key=market.identity_key,
            settlement_rule=market.settlement_rule,
            display_name=market.display_name,
            is_synthetic=market.is_synthetic,
        ).model_dump(mode="json")
        for market in rows
    ]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return Page(items=items, next_cursor=next_cursor, partial=False)


@router.get("/quotes/latest", response_model=Page, summary="Best current price per outcome")
def latest_quotes(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    role: Annotated[object, Depends(current_role)],
    market_id: UUID | None = Query(default=None, description="Required in the MVP."),
    outcome_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    if market_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "market_id is required in the MVP")
    size = clamp_page_size(page_size)
    statement = (
        select(models.Quote)
        .where(models.Quote.market_id == market_id)
        .order_by(models.Quote.observed_at.desc())
    )
    if outcome_id:
        statement = statement.where(models.Quote.outcome_id == outcome_id)
    quotes = list(session.scalars(statement.limit(size * 4)).all())

    now = utcnow()
    seen: dict[UUID, models.Quote] = {}
    for quote in quotes:
        seen.setdefault(quote.outcome_id, quote)
    outcome_rows = {row.id: row for row in session.scalars(select(models.Outcome)).all()}
    items = []
    for quote in list(seen.values())[:size]:
        outcome = outcome_rows.get(quote.outcome_id)
        items.append(
            QuoteOut(
                id=quote.id,
                market_id=quote.market_id,
                outcome_id=quote.outcome_id,
                outcome_kind=outcome.outcome_kind if outcome else "home",
                source_id=quote.source_id,
                venue_kind=quote.venue_kind,
                venue_name=quote.venue_name,
                decimal_odds=str(quote.decimal_odds),
                available_size=str(quote.available_size),
                currency=quote.currency,
                observed_at=quote.observed_at,
                age_seconds=round(max(0.0, seconds_between(now, quote.observed_at)), 3),
                provider_timestamp=quote.provider_timestamp,
                latency_ms=quote.latency_ms,
                freshness=freshness_of(
                    quote.observed_at, now, settings.pricing_max_quote_age_seconds
                ),
                is_synthetic=quote.is_synthetic,
            ).model_dump(mode="json")
        )
    return Page(items=items, next_cursor=None, partial=False)