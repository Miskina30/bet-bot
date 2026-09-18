"""Server-Sent Events: live opportunity pushes for the dashboard.

``GET /v1/stream/opportunities`` emits one JSON event per opportunity (newest
first), then a heartbeat comment every 15 seconds. Clients resume with the
``Last-Event-ID`` header: the server replays anything newer than that id.
Nothing here is a wager or an order -- it is a read-only push of the same rows
the REST endpoints return.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from academic_edge_api.deps import get_session
from academic_edge_api.routers.insights import _opportunity_out
from academic_edge_api.security import current_role
from academic_edge_domain import models

router = APIRouter()
HEARTBEAT_SECONDS = 15


def _opportunity_event(opportunity: models.Opportunity, session: Session) -> dict[str, str]:
    payload = _opportunity_out(session, opportunity).model_dump(mode="json")
    return {
        "event": "opportunity",
        "id": str(opportunity.id),
        "data": json.dumps(payload, default=str),
    }


def _event_stream(
    session: Session, since_id: str | None, max_events: int
) -> Iterator[dict[str, str]]:
    statement = select(models.Opportunity).order_by(models.Opportunity.detected_at.desc())
    if since_id:
        try:
            anchor = session.get(models.Opportunity, UUID(since_id))
        except ValueError:
            anchor = None
        if anchor is not None:
            statement = statement.where(models.Opportunity.detected_at > anchor.detected_at)
    rows = list(session.scalars(statement.limit(max_events)).all())
    session.close()
    for row in rows:
        yield {"event": "opportunity", "id": str(row.id), "data": row_as_json(row)}
    # no heartbeat here: EventSourceResponse handles ping via ping_interval


def row_as_json(opportunity: models.Opportunity) -> str:
    """Serialise without a session (legs are embedded in the row)."""
    return json.dumps(
        {
            "id": str(opportunity.id),
            "event_id": str(opportunity.event_id),
            "market_id": str(opportunity.market_id),
            "opportunity_type": str(opportunity.opportunity_type),
            "is_actionable": opportunity.is_actionable,
            "net_edge_bps": opportunity.net_edge_bps,
            "gross_edge_bps": opportunity.gross_edge_bps,
            "confidence": opportunity.confidence,
            "best_legs": opportunity.best_legs,
            "detected_at": opportunity.detected_at.isoformat(),
            "reasons": opportunity.reasons,
            "warnings": opportunity.warnings,
            "is_synthetic": opportunity.is_synthetic,
        },
        default=str,
    )


@router.get("/stream/opportunities", summary="SSE feed of opportunities")
def stream_opportunities(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[object, Depends(current_role)],
    max_events: int = 100,
) -> EventSourceResponse:
    last_event_id = request.headers.get("Last-Event-ID")
    generator = _event_stream(session, last_event_id, max_events)
    return EventSourceResponse(generator, ping=HEARTBEAT_SECONDS)