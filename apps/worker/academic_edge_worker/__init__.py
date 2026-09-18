"""Academic Edge worker: ingest pipeline, seed, and CLI entry points."""

from academic_edge_worker.seed import seed_database

__all__ = ["seed_database"]