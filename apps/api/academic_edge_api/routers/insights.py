"""Read endpoints for opportunities, review, predictions, models, alerts, ledger."""

from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from academic_edge_api.deps import get_session
from academic_edge_api.pagination import Page, clamp_page_size, decode_request_cursor
from academic_edge_api.schemas import (
    AlertAcknowledgeIn,
    AlertOut,
    ModelMetricsOut,
    OpportunityLegOut,
    OpportunityOut,
    PaperLedgerOut,
    PredictionOut,
    ReviewDecisionIn,
    ReviewItemOut,
)
from academic_edge_api.security import current_role, require_role
from academic_edge_domain import models
from academic_edge_domain.enums import AlertStatus, FreshnessLabel, ReviewStatus, Role
from academic_edge_domain.ids import encode_cursor
from academic_edge_domain.time import seconds_between, utcnow

router = APIRouter()


def _opportunity_out(session: Session, opportunity: models.Opportunity) -> OpportunityOut:
    market = session.get(models.Market, opportunity.market_id)
    outcome_rows = session.scalars(
        select(models.Outcome).where(models.Outcome.market_id == opportunity.market_id)
    ).all()
    now = utcnow()
    legs: list[OpportunityLegOut] = []
    for leg in opportunity.best_legs or []:
        observed_raw = leg.get("observed_at")
        observed = (
            dt.datetime.fromisoformat(observed_raw) if observed_raw else opportunity.detected_at
        )
        age = max(0.0, seconds_between(now, observed))
        legs.append(
            OpportunityLegOut(
                outcome_kind=leg.get("outcome_kind", "home"),
                label=leg.get("label", "?"),
                source_id=leg.get("source_id", "?"),
                venue_name=leg.get("venue_name", "?"),
                decimal_odds=str(leg.get("decimal_odds", "0")),
                stake=str(leg.get("stake", "0")),
                payoff=str(leg.get("payoff", "0")),
                age_seconds=round(age, 3),
                freshness=leg.get("freshness", FreshnessLabel.FRESH.value),
                available_size=str(leg.get("available_size", "0")),
            )
        )

    model_version = None
    if opportunity.model_version_id:
        model_row = session.get(models.ModelVersion, opportunity.model_version_id)
        if model_row:
            model_version = f"{model_row.name}@{model_row.version}"
    friction = opportunity.friction or {}

    return OpportunityOut(
        id=opportunity.id,
        event_id=opportunity.event_id,
        market_id=opportunity.market_id,
        opportunity_type=opportunity.opportunity_type,
        is_actionable=opportunity.is_actionable,
        net_edge_bps=opportunity.net_edge_bps,
        gross_edge_bps=opportunity.gross_edge_bps,
        confidence=opportunity.confidence,
        best_legs=legs,
        friction=friction,
        de_vig_method=friction.get("de_vig_method"),
        model_probability=friction.get("model_probability"),
        model_version=model_version,
        uncertainty=friction.get("uncertainty"),
        total_stake=str(opportunity.total_stake),
        expected_profit=str(opportunity.expected_profit),
        currency=opportunity.currency,
        detected_at=opportunity.detected_at,
        expires_at=opportunity.expires_at,
        reasons=list(opportunity.reasons or []),
        warnings=list(opportunity.warnings or []),
        settlement_rule=market.settlement_rule if market else "?",
        is_synthetic=opportunity.is_synthetic,
    )


@router.get("/opportunities", response_model=Page, summary="Opportunity board")
def list_opportunities(
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
    type: str | None = Query(default=None, alias="type"),
    min_net_edge_bps: int | None = Query(default=None),
    actionable_only: bool = Query(default=False),
    include_synthetic: bool = Query(default=True),
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    size = clamp_page_size(page_size)
    decoded = decode_request_cursor(cursor)
    statement = select(models.Opportunity).order_by(
        models.Opportunity.detected_at.desc(), models.Opportunity.id.desc()
    )
    if decoded is not None:
        before, last_id = decoded
        statement = statement.where(
            (models.Opportunity.detected_at < before)
            | ((models.Opportunity.detected_at == before) & (models.Opportunity.id < last_id))
        )
    if type:
        statement = statement.where(models.Opportunity.opportunity_type == type)
    if min_net_edge_bps is not None:
        statement = statement.where(models.Opportunity.net_edge_bps >= min_net_edge_bps)
    if actionable_only:
        statement = statement.where(models.Opportunity.is_actionable.is_(True))
    if not include_synthetic:
        statement = statement.where(models.Opportunity.is_synthetic.is_(False))
    statement = statement.limit(size + 1)

    rows = list(session.scalars(statement).all())
    has_more = len(rows) > size
    rows = rows[:size]
    items = [_opportunity_out(session, row).model_dump(mode="json") for row in rows]
    next_cursor = encode_cursor(rows[-1].detected_at, rows[-1].id) if has_more and rows else None
    return Page(items=items, next_cursor=next_cursor, partial=False)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityOut, summary="Opportunity detail")
def get_opportunity(
    opportunity_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
) -> OpportunityOut:
    row = session.get(models.Opportunity, opportunity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"opportunity {opportunity_id} not found")
    return _opportunity_out(session, row)


def _review_out(session: Session, row: models.ProviderEventMap) -> ReviewItemOut:
    evidence = row.evidence or {}
    return ReviewItemOut(
        map_id=row.id,
        source_id=row.source_id,
        provider_event_id=row.provider_event_id,
        competition=str(evidence.get("competition", "?")),
        candidate_home=str(evidence.get("candidate_home", "?")),
        candidate_away=str(evidence.get("candidate_away", "?")),
        candidate_start_time_utc=row.last_seen_at or row.created_at,
        matched_event_id=row.canonical_event_id,
        score=str(round(float(row.match_score), 6)),
        status=row.review_status,
        hard_rejects=list(row.hard_reject_reasons or []),
        component_scores=dict(evidence.get("component_scores", {})),
        evidence=evidence,
    )


@router.get("/resolver/review", response_model=Page, summary="Resolver review queue")
def review_queue(
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    size = clamp_page_size(page_size)
    statement = select(models.ProviderEventMap).order_by(
        models.ProviderEventMap.created_at.desc(), models.ProviderEventMap.id.desc()
    )
    decoded = decode_request_cursor(cursor)
    if decoded is not None:
        before, last_id = decoded
        statement = statement.where(
            (models.ProviderEventMap.created_at < before)
            | ((models.ProviderEventMap.created_at == before) & (models.ProviderEventMap.id < last_id))
        )
    if status:
        statement = statement.where(models.ProviderEventMap.review_status == status)
    statement = statement.limit(size + 1)

    rows = list(session.scalars(statement).all())
    has_more = len(rows) > size
    rows = rows[:size]
    items = [_review_out(session, row).model_dump(mode="json") for row in rows]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return Page(items=items, next_cursor=next_cursor, partial=False)


@router.post("/resolver/review/{map_id}/decision", response_model=ReviewItemOut, summary="Manual resolution decision")
def review_decision(
    map_id: UUID,
    body: ReviewDecisionIn,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[Role, Depends(require_role(Role.ANALYST))],
) -> ReviewItemOut:
    row = session.get(models.ProviderEventMap, map_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"review item {map_id} not found")
    if body.action == "accept":
        row.review_status = ReviewStatus.MANUALLY_LINKED
    else:
        row.review_status = ReviewStatus.REJECTED
    row.decided_at = utcnow()
    row.decided_by = role.value
    evidence = dict(row.evidence or {})
    evidence["manual_note"] = body.note
    row.evidence = evidence
    session.add(
        models.AuditLog(
            action="resolution_decision",
            actor=role.value,
            actor_role=role,
            source_id=row.source_id,
            event_id=row.canonical_event_id,
            occurred_at=utcnow(),
            detail={"map_id": str(map_id), "action": body.action, "note": body.note},
        )
    )
    session.flush()
    return _review_out(session, row)


@router.get("/predictions/{event_id}", response_model=list[PredictionOut], summary="Model probabilities for one event")
def predictions_for_event(
    event_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
) -> list[PredictionOut]:
    rows = session.scalars(
        select(models.Prediction)
        .where(models.Prediction.event_id == event_id)
        .order_by(models.Prediction.created_at.desc())
    ).all()
    items: list[PredictionOut] = []
    for row in rows:
        model_row = session.get(models.ModelVersion, row.model_version_id)
        items.append(
            PredictionOut(
                event_id=row.event_id,
                model=f"{model_row.name}@{model_row.version}" if model_row else "?",
                market_type=row.market_type,
                outcome_kind=row.outcome_kind,
                probability=str(row.probability),
                fair_odds=str(row.fair_odds),
                uncertainty=row.uncertainty,
                abstained=row.abstained,
                abstain_reason=row.abstain_reason,
                market_free=row.market_free,
                as_of=row.as_of,
                explanation=row.explanation or {},
                is_synthetic=row.is_synthetic,
            )
        )
    return items


@router.get("/models/metrics", response_model=list[ModelMetricsOut], summary="Walk-forward metrics per model")
def models_metrics(
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
) -> list[ModelMetricsOut]:
    rows = session.scalars(
        select(models.ModelVersion).order_by(models.ModelVersion.created_at.desc())
    ).all()
    return [
        ModelMetricsOut(
            model=f"{row.name}@{row.version}",
            algorithm=row.algorithm,
            trained_at=row.trained_at,
            train_window={
                "start": row.train_window_start.isoformat() if row.train_window_start else None,
                "end": row.train_window_end.isoformat() if row.train_window_end else None,
            },
            calibration_window={
                "start": row.calibration_window_start.isoformat()
                if row.calibration_window_start
                else None,
                "end": row.calibration_window_end.isoformat() if row.calibration_window_end else None,
            },
            metrics=row.metrics or {},
            is_active=row.is_active,
            is_synthetic=row.is_synthetic,
        )
        for row in rows
    ]


def _alert_out(session: Session, row: models.Alert) -> AlertOut:
    rule = session.get(models.AlertRule, row.alert_rule_id)
    return AlertOut(
        id=row.id,
        rule=rule.name if rule else "?",
        event_id=row.event_id,
        market_id=row.market_id,
        opportunity_id=row.opportunity_id,
        status=row.status,
        severity=row.severity,
        message=row.message,
        raised_at=row.raised_at,
        evidence=row.evidence or {},
        is_synthetic=row.is_synthetic,
    )


@router.get("/alerts", response_model=Page, summary="Alert inbox")
def list_alerts(
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
    status_filter: AlertStatus | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    size = clamp_page_size(page_size)
    statement = select(models.Alert).order_by(models.Alert.raised_at.desc(), models.Alert.id.desc())
    decoded = decode_request_cursor(cursor)
    if decoded is not None:
        before, last_id = decoded
        statement = statement.where(
            (models.Alert.raised_at < before)
            | ((models.Alert.raised_at == before) & (models.Alert.id < last_id))
        )
    if status_filter:
        statement = statement.where(models.Alert.status == status_filter)
    statement = statement.limit(size + 1)

    rows = list(session.scalars(statement).all())
    has_more = len(rows) > size
    rows = rows[:size]
    items = [_alert_out(session, row).model_dump(mode="json") for row in rows]
    next_cursor = encode_cursor(rows[-1].raised_at, rows[-1].id) if has_more and rows else None
    return Page(items=items, next_cursor=next_cursor, partial=False)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut, summary="Acknowledge an alert")
def acknowledge_alert(
    alert_id: UUID,
    body: AlertAcknowledgeIn,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[Role, Depends(require_role(Role.ANALYST))],
) -> AlertOut:
    row = session.get(models.Alert, alert_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"alert {alert_id} not found")
    row.status = AlertStatus.ACKNOWLEDGED
    row.acknowledged_at = utcnow()
    row.acknowledged_by = role.value
    session.add(
        models.AuditLog(
            action="alert_acknowledged",
            actor=role.value,
            actor_role=role,
            event_id=row.event_id,
            occurred_at=utcnow(),
            detail={"alert_id": str(alert_id), "note": body.note},
        )
    )
    session.flush()
    return _alert_out(session, row)


@router.get("/paper-ledger", response_model=Page, summary="Paper-trading ledger (research only)")
def paper_ledger(
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
    cursor: str | None = Query(default=None),
    page_size: int | None = Query(default=None, ge=1),
) -> Page:
    size = clamp_page_size(page_size)
    statement = select(models.PaperLedgerEntry).order_by(
        models.PaperLedgerEntry.placed_at.desc(), models.PaperLedgerEntry.id.desc()
    )
    decoded = decode_request_cursor(cursor)
    if decoded is not None:
        before, last_id = decoded
        statement = statement.where(
            (models.PaperLedgerEntry.placed_at < before)
            | ((models.PaperLedgerEntry.placed_at == before) & (models.PaperLedgerEntry.id < last_id))
        )
    statement = statement.limit(size + 1)

    rows = list(session.scalars(statement).all())
    has_more = len(rows) > size
    rows = rows[:size]
    items = [
        PaperLedgerOut(
            id=row.id,
            event_id=row.event_id,
            market_id=row.market_id,
            outcome_id=row.outcome_id,
            source_id=row.source_id,
            stake=str(row.stake),
            decimal_odds=str(row.decimal_odds),
            currency=row.currency,
            status=row.status,
            placed_at=row.placed_at,
            settled_at=row.settled_at,
            pnl=str(row.pnl) if row.pnl is not None else None,
            is_synthetic=row.is_synthetic,
        ).model_dump(mode="json")
        for row in rows
    ]
    next_cursor = encode_cursor(rows[-1].placed_at, rows[-1].id) if has_more and rows else None
    return Page(items=items, next_cursor=next_cursor, partial=False)