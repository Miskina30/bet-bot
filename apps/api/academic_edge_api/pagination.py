"""Keyset cursor pagination shared by every list endpoint.

Cursors are opaque base64url ``(observed_at, id)`` pairs (see
``academic_edge_domain.ids``). Responses carry ``next_cursor`` (``None`` at the
end) plus a ``partial`` flag the worker sets when a source failed to answer, so
the UI can render a "partial source" state instead of pretending the list is
complete.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, TypeVar

from academic_edge_domain.ids import CursorError, decode_cursor, encode_cursor
from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


class Page(BaseModel):
    """Envelope for every list response."""

    items: list[Any] = Field(default_factory=list, description="Page items, newest first.")
    next_cursor: str | None = Field(
        default=None, description="Opaque cursor for the next page; null at the end."
    )
    partial: bool = Field(
        default=False, description="True when a source failed and the list may be incomplete."
    )

    model_config = {"extra": "forbid"}


def clamp_page_size(size: int | None) -> int:
    """Bound the page size; ``None`` means the default."""
    if size is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(size, MAX_PAGE_SIZE))


def decode_request_cursor(cursor: str | None) -> tuple[dt.datetime, uuid.UUID] | None:
    """Parse the ``?cursor=`` parameter, returning ``None`` for the first page."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except CursorError as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid cursor: {exc}") from exc


def next_page_cursor(items: list[Any], page_size: int) -> str | None:
    """Build ``next_cursor`` from the last row when the page is full."""
    if len(items) < page_size:
        return None
    last = items[-1]
    observed = last.get("observed_at") or last.get("detected_at") or last.get("raised_at")
    if observed is None:
        return None
    return encode_cursor(observed, last["id"])


ItemT = TypeVar("ItemT")
