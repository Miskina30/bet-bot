"""Request-scoped dependencies: engine, database session, policy registry."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from academic_edge_domain.db import build_engine, build_session_factory
from academic_edge_domain.policy import SourcePolicyRegistry, load_registry
from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from academic_edge_api.settings import Settings, get_settings


@lru_cache(maxsize=8)
def cached_engine(db_url: str) -> Engine:
    """One engine per distinct database URL (process-wide, thread-safe)."""
    return build_engine(Settings(database_url=db_url))


def get_engine(settings: Annotated[Settings, Depends(get_settings)]) -> Engine:
    return cached_engine(settings.resolve_db_url())


def get_session(request: Request) -> Iterator[Session]:
    """Yield a request-scoped session, committing on success."""
    engine: Engine = request.app.state.engine
    factory = build_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@lru_cache(maxsize=1)
def cached_registry() -> SourcePolicyRegistry:
    return load_registry()


def get_registry() -> SourcePolicyRegistry:
    return cached_registry()
