"""Database plumbing: engine, session factory, declarative base."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Sequence
from typing import Any

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from academic_edge_domain.settings import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for every canonical entity."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"

    def as_dict(self) -> dict[str, Any]:
        """Column-oriented view used by audit/replay tooling."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


def build_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    """Create an engine for the configured database.

    SQLite is a first-class *local* target (zero-dependency demo/test profile).
    Postgres 16 is the production target; nothing in this function is Postgres
    specific, and migrations are dialect-neutral.
    """
    cfg = settings or get_settings()
    url = cfg.resolve_db_url()
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(
        url, echo=echo, future=True, pool_pre_ping=True, connect_args=connect_args
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL keeps a reader (API) and writer (worker) happy in the local profile.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory with sane defaults for a web/worker process."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True, autoflush=False)


@contextlib.contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine) -> None:
    """Create the schema directly (tests/bootstrap). Alembic owns production."""
    from academic_edge_domain import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop the schema (tests only)."""
    from academic_edge_domain import models  # noqa: F401

    Base.metadata.drop_all(engine)


def truncate_all(session: Session, tables: Sequence[str] | None = None) -> None:
    """Delete all rows, child-table order first (test helper)."""

    ordered = list(reversed(Base.metadata.sorted_tables))
    targets = [t for t in ordered if tables is None or t.name in set(tables)]
    for table in targets:
        session.execute(table.delete())


def ping(session: Session) -> bool:
    """Cheap liveness probe used by /v1/health and CLI doctor."""
    try:
        session.execute(select(1)).scalar_one()
    except Exception:  # pragma: no cover - depends on external DB state
        return False
    return True
