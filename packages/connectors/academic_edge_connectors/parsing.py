"""Shared provider-payload parsing guards.

Every adapter funnels raw provider text through these helpers.  The rule from the
brief is simple: **never invent provider fields**.  When a payload does not carry
a field the frozen contract promises, we raise
:class:`academic_edge_connectors.base.ParserDriftError` instead of substituting a
default, so a vendor schema change becomes a loud, diagnosable failure (the raw
bytes are still archived by the caller before parsing).

Nothing here performs I/O: the helpers take already-decoded values or bytes and
are pure functions, which keeps the contract tests fast and offline.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from academic_edge_domain.time import TimestampParseError, parse_timestamp

from academic_edge_connectors.base import ParserDriftError

__all__ = [
    "json_list",
    "optional_decimal",
    "optional_int",
    "optional_str",
    "optional_timestamp",
    "parse_csv_rows",
    "parse_json_bytes",
    "require_columns",
    "require_decimal",
    "require_field",
    "require_int",
    "require_list",
    "require_object",
    "require_odds",
    "require_str",
    "require_timestamp",
]


def require_object(value: Any, *, where: str) -> dict[str, Any]:
    """Return ``value`` as a mapping, or raise when it is not a JSON object."""
    if not isinstance(value, dict):
        raise ParserDriftError(f"{where}: expected a JSON object, got {type(value).__name__}")
    return value


def require_list(value: Any, *, where: str) -> list[Any]:
    """Return ``value`` as a list, or raise when it is not a JSON array."""
    if not isinstance(value, list):
        raise ParserDriftError(f"{where}: expected a JSON array, got {type(value).__name__}")
    return value


def require_field(obj: Mapping[str, Any], key: str, *, where: str) -> Any:
    """Return a required field; a missing *or null* value counts as drift."""
    if key not in obj or obj[key] is None:
        raise ParserDriftError(f"{where}: required field {key!r} is missing or null")
    return obj[key]


def require_str(obj: Mapping[str, Any], key: str, *, where: str) -> str:
    """Return a required non-empty string field."""
    raw = require_field(obj, key, where=where)
    text = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if not text:
        raise ParserDriftError(f"{where}: required string field {key!r} is empty")
    return text


def optional_str(obj: Mapping[str, Any], key: str, *, where: str) -> str | None:
    """Return an optional string field (``None`` when absent/null/blank)."""
    raw = obj.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ParserDriftError(
            f"{where}: field {key!r} should be a string, got {type(raw).__name__}"
        )
    text = raw.strip()
    return text or None


def require_int(obj: Mapping[str, Any], key: str, *, where: str) -> int:
    """Return a required integer field (numeric strings are accepted)."""
    raw = require_field(obj, key, where=where)
    if isinstance(raw, bool):
        raise ParserDriftError(f"{where}: field {key!r} should be an integer, got bool")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    raise ParserDriftError(f"{where}: field {key!r} should be an integer, got {raw!r}")


def optional_int(obj: Mapping[str, Any], key: str, *, where: str) -> int | None:
    """Return an optional integer field; a present-but-invalid value is drift."""
    if obj.get(key) is None:
        return None
    return require_int(obj, key, where=where)


def require_decimal(value: Any, *, where: str) -> Decimal:
    """Return a finite :class:`~decimal.Decimal` from a provider number/string."""
    if isinstance(value, bool) or value is None:
        raise ParserDriftError(f"{where}: expected a number, got {value!r}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ParserDriftError(f"{where}: expected a number, got an empty string")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ParserDriftError(f"{where}: {value!r} is not a number") from exc
    else:
        raise ParserDriftError(f"{where}: expected a number, got {type(value).__name__}")
    if not result.is_finite():
        raise ParserDriftError(f"{where}: {value!r} is not a finite number")
    return result


def require_odds(value: Any, *, where: str) -> Decimal:
    """Return decimal odds, raising drift when the value is not ``> 1.0``.

    ``1.0`` is not a price in this system (see ``academic_edge_pricing.odds``), so
    a provider quoting it is contract drift and is never silently accepted.
    """
    odds = require_decimal(value, where=where)
    if odds <= Decimal("1"):
        raise ParserDriftError(f"{where}: decimal odds must be > 1.0, got {odds}")
    return odds


def optional_decimal(obj: Mapping[str, Any], key: str, *, where: str) -> Decimal | None:
    """Return an optional numeric field; a present-but-invalid value is drift."""
    if obj.get(key) is None:
        return None
    return require_decimal(obj[key], where=f"{where}.{key}")


def require_timestamp(value: Any, *, where: str) -> dt.datetime:
    """Parse a provider timestamp into aware UTC, or raise drift."""
    if value is None:
        raise ParserDriftError(f"{where}: required timestamp is missing")
    try:
        return parse_timestamp(value)
    except TimestampParseError as exc:
        raise ParserDriftError(f"{where}: cannot parse provider timestamp {value!r}") from exc


def optional_timestamp(obj: Mapping[str, Any], key: str, *, where: str) -> dt.datetime | None:
    """Return an optional timestamp field; a present-but-invalid value is drift."""
    if obj.get(key) is None:
        return None
    return require_timestamp(obj[key], where=f"{where}.{key}")


def json_list(value: Any, *, where: str) -> list[str]:
    """Decode a provider field that is *sometimes* a JSON-encoded string.

    Polymarket delivers ``outcomes`` / ``outcomePrices`` / ``clobTokenIds`` as
    JSON text inside a JSON string (``"[\\"Yes\\", \\"No\\"]"``), while other
    payloads return a real array.  Both shapes are accepted; anything else is
    drift.  Every element is returned as a string so parallel arrays keep their
    indices aligned.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParserDriftError(f"{where}: field is not valid JSON: {value!r}") from exc
    else:
        decoded = value
    if not isinstance(decoded, list):
        raise ParserDriftError(
            f"{where}: expected a JSON array (or array-encoded string), "
            f"got {type(decoded).__name__}"
        )
    return [str(item) for item in decoded]


def parse_json_bytes(payload: bytes, *, where: str) -> Any:
    """Decode provider JSON bytes (UTF-8, optional BOM) or raise drift."""
    raw = payload[3:] if payload[:3] == b"\xef\xbb\xbf" else payload
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParserDriftError(f"{where}: payload is not valid UTF-8") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParserDriftError(f"{where}: payload is not valid JSON ({exc.msg})") from exc


def parse_csv_rows(text: str, *, where: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV text into ``(header, rows)``, padding ragged rows.

    Header cells are stripped, blank lines are dropped and short rows are padded
    with empty strings so a row missing its final delimiter does not shift
    columns.  A payload without a header row is drift.
    """
    cleaned = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(cleaned, newline=""))
    parsed = [row for row in reader if any(cell.strip() for cell in row)]
    if not parsed:
        raise ParserDriftError(f"{where}: CSV payload is empty")
    header = [cell.strip() for cell in parsed[0]]
    rows: list[dict[str, str]] = []
    for raw_row in parsed[1:]:
        padded = [*raw_row, *("" for _ in range(max(0, len(header) - len(raw_row))))]
        rows.append({name: padded[index].strip() for index, name in enumerate(header)})
    return header, rows


def require_columns(header: Sequence[str], required: Sequence[str], *, where: str) -> None:
    """Assert that a CSV header carries every required column name."""
    missing = [column for column in required if column not in header]
    if missing:
        raise ParserDriftError(
            f"{where}: CSV header is missing required column(s) {missing}; got {list(header)}"
        )
