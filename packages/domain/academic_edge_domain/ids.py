"""Identifiers and cursor helpers.

Canonical entities get UUID4 primary keys so identifiers are stable across
environments and safe to expose in URLs. ``deterministic_id`` is used for
entities that must be idempotent under re-ingestion (e.g. an event identity
derived from provider+key), which is what makes the pipeline replayable.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from academic_edge_domain.time import ensure_utc

_ID_NAMESPACE = uuid.UUID("6f2a1c9e-6ab5-4a1f-9c3e-2a7f5b9d4e11")


class CursorError(ValueError):
    """Raised when an API cursor is malformed or has been tampered with."""


def new_id() -> uuid.UUID:
    """Random UUID4 for canonical entities."""
    return uuid.uuid4()


def deterministic_id(kind: str, *parts: str) -> uuid.UUID:
    """Stable UUID5 derived from ``kind`` + ``parts`` (idempotent upserts)."""
    joined = "\x1f".join([kind, *parts])
    return uuid.uuid5(_ID_NAMESPACE, joined)


def encode_cursor(observed_at: dt.datetime, row_id: uuid.UUID) -> str:
    """Encode a keyset-pagination cursor as opaque base64url JSON.

    Cursors are ``(observed_at, id)`` -- a strict total order that survives
    inserts at the head, unlike OFFSET pagination.
    """
    payload = {"t": ensure_utc(observed_at).isoformat(), "id": str(row_id)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[dt.datetime, uuid.UUID]:
    """Decode a cursor produced by :func:`encode_cursor`."""
    if not cursor:
        raise CursorError("empty cursor")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload: Any = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor is not valid base64url JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"t", "id"}:
        raise CursorError("cursor payload has unexpected shape")
    try:
        observed_at = dt.datetime.fromisoformat(str(payload["t"]))
        row_id = uuid.UUID(str(payload["id"]))
    except (TypeError, ValueError) as exc:
        raise CursorError("cursor fields are invalid") from exc
    return ensure_utc(observed_at), row_id


def content_fingerprint(*parts: object) -> str:
    """SHA-256 hex digest over the JSON-normalised ``parts`` (raw-archive keys)."""
    canonical = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
