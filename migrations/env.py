"""Alembic environment for Academic Edge.

Loads the canonical SQLAlchemy metadata from ``academic_edge_domain.models``
and supports both the local SQLite profile and the Postgres 16 production
profile via ``DATABASE_URL``. No secrets are committed: the URL comes from the
environment or ``.env`` through the domain settings.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context

# Make packages importable from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
paths = [
    "apps/worker",
    "apps/api",
    "packages/domain",
    "packages/connectors",
    "packages/resolver",
    "packages/pricing",
    "packages/features",
    "packages/forecasting",
]
for p in paths:
    full = os.path.join(os.path.dirname(os.path.dirname(__file__)), p)
    if full not in sys.path:
        sys.path.insert(0, full)

from academic_edge_domain import models  # noqa: F401  (registers tables)
from academic_edge_domain.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()