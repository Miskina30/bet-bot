"""Frozen-fixture loading for adapters running in ``mode="fixture"``.

Fixture mode is the offline path: an adapter reads a labelled, redacted payload
from ``tests/fixtures`` instead of a network response, and every record it
produces is tagged ``is_synthetic=True`` so nothing offline can be mistaken for a
live quote.

Resolution order for the fixture directory:

1. an explicit ``directory`` argument,
2. ``ACADEMIC_EDGE_FIXTURE_DIR``,
3. ``<repo root>/tests/fixtures`` (via ``academic_edge_domain.policy.repo_root``),
4. ``<cwd>/tests/fixtures``.

Tests can also inject payloads directly (``overrides``); that is how the contract
tests mutate a frozen payload to prove drift raises
:class:`~academic_edge_connectors.base.ParserDriftError`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from academic_edge_domain.policy import repo_root

from academic_edge_connectors.base import AdapterUnavailable

__all__ = [
    "FIXTURE_DIR_ENV",
    "FIXTURE_SUBDIR",
    "FixtureStore",
    "default_fixture_dirs",
    "resolve_fixture_directory",
]

FIXTURE_DIR_ENV = "ACADEMIC_EDGE_FIXTURE_DIR"
FIXTURE_SUBDIR = Path("tests") / "fixtures"


def default_fixture_dirs() -> list[Path]:
    """Candidate fixture directories, most specific first."""
    candidates = [repo_root() / FIXTURE_SUBDIR, Path.cwd() / FIXTURE_SUBDIR]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def resolve_fixture_directory(directory: Path | None = None) -> Path | None:
    """First existing fixture directory, or ``None`` when none is available.

    An explicit path or env var that does not exist resolves to ``None`` rather
    than silently falling through to a different directory, so a misconfigured
    CI job fails as "fixture missing" instead of reading the wrong payload.
    """
    if directory is not None:
        return directory if directory.is_dir() else None
    env_value = os.environ.get(FIXTURE_DIR_ENV)
    if env_value:
        env_path = Path(env_value)
        return env_path if env_path.is_dir() else None
    for candidate in default_fixture_dirs():
        if candidate.is_dir():
            return candidate
    return None


class FixtureStore:
    """Reads frozen payloads from disk, with optional in-memory overrides."""

    def __init__(
        self,
        *,
        directory: Path | None = None,
        overrides: Mapping[str, bytes] | None = None,
        source_id: str = "fixture",
    ) -> None:
        self.directory = resolve_fixture_directory(directory)
        self.overrides: dict[str, bytes] = dict(overrides or {})
        self.source_id = source_id
        self.read_count = 0

    def has(self, name: str) -> bool:
        """True when the payload is available as an override or a file."""
        return name in self.overrides or self.path(name) is not None

    def path(self, name: str) -> Path | None:
        """Absolute path of a fixture file, or ``None`` when it does not exist."""
        if self.directory is None:
            return None
        candidate = self.directory / name
        return candidate if candidate.is_file() else None

    def read_bytes(self, name: str) -> bytes:
        """Read a payload; in-memory overrides win over files.

        Raises :class:`AdapterUnavailable` when the fixture is missing: fixture
        mode must never silently fall back to the network or to fabricated data.
        """
        override = self.overrides.get(name)
        if override is not None:
            self.read_count += 1
            return override
        path = self.path(name)
        if path is None:
            searched = self.directory if self.directory is not None else default_fixture_dirs()
            raise AdapterUnavailable(
                f"{self.source_id}: frozen fixture {name!r} not found in {searched}; "
                f"set {FIXTURE_DIR_ENV} to the directory that holds it"
            )
        self.read_count += 1
        return path.read_bytes()

    def read_text(self, name: str) -> str:
        """Read a payload as UTF-8 text (the BOM is tolerated)."""
        return self.read_bytes(name).decode("utf-8-sig")
