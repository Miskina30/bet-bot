"""Crocobet adapter: **MANUAL CSV IMPORT ONLY** - no network code of any kind.

``config/source_policies.yaml`` records Crocobet as ``automation_allowed: false``
with ``automation_scope: manual_csv_only``.  This module therefore contains:

* no ``httpx`` import, no socket, no URL handling, no HTML parsing;
* a constructor that calls
  :meth:`academic_edge_domain.policy.SourcePolicyRegistry.require_manual_import`
  and raises :class:`~academic_edge_domain.policy.PolicyViolation` when it is
  handed *any* session, client, transport or base URL, so a future contributor
  cannot quietly turn this into a scraper;
* a strict parser for the operator-supplied CSV contract.

Manual CSV columns (verbatim, one row per *selection*):

``event_name, kickoff_utc, home_team, away_team, market, selection, odds,
currency, exported_at``

``event_name`` is the operator's own free-text label for the competition/match
and is carried through as ``competition_name`` with an
``provider_event_name`` extra so the resolver can treat it as untrusted text.
Manual data is real operator data, not synthetic: ``is_synthetic`` stays
``False``, and the audit trail records the manual-import policy.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from academic_edge_domain.enums import AutomationScope, MarketType, OutcomeKind, VenueKind
from academic_edge_domain.policy import PolicyViolation, SourcePolicyRegistry
from academic_edge_domain.settings import Settings
from academic_edge_domain.time import ensure_utc, utcnow

from academic_edge_connectors.base import ParserDriftError, ProviderEvent
from academic_edge_connectors.contracts import (
    ProviderMarket,
    ProviderOutcome,
    build_provenance,
)
from academic_edge_connectors.fixture_io import FixtureStore
from academic_edge_connectors.parsing import (
    parse_csv_rows,
    require_columns,
    require_odds,
    require_str,
    require_timestamp,
)

__all__ = [
    "DEFAULT_FIXTURE_NAME",
    "MANUAL_MODE",
    "MARKET_ALIASES",
    "NETWORK_ENABLED",
    "REQUIRED_COLUMNS",
    "SELECTION_ALIASES",
    "SOURCE_ID",
    "SUPPORTED_SELECTIONS",
    "VENUE_NAME",
    "CrocobetManualCsvAdapter",
    "ParsedManualCsv",
    "parse_manual_csv_text",
]

LOGGER = logging.getLogger(__name__)

SOURCE_ID = "crocobet"
VENUE_NAME = "Crocobet"
DEFAULT_FIXTURE_NAME = "crocobet_manual_sample.csv"

#: This connector has no live mode at all; the value keeps the
#: :class:`~academic_edge_connectors.contracts.ProviderAdapter` shape honest by
#: explicitly *not* claiming to be live.
MANUAL_MODE = "fixture"

#: Load-bearing constant: proves at a glance that no code path here can fetch.
NETWORK_ENABLED = False

REQUIRED_COLUMNS: tuple[str, ...] = (
    "event_name",
    "kickoff_utc",
    "home_team",
    "away_team",
    "market",
    "selection",
    "odds",
    "currency",
    "exported_at",
)

#: Operator market labels mapped onto canonical market types.  Keys are matched
#: case-insensitively after trimming.
MARKET_ALIASES: dict[str, MarketType] = {
    "1x2": MarketType.FT_1X2,
    "ft_1x2": MarketType.FT_1X2,
    "match winner": MarketType.FT_1X2,
    "match_winner": MarketType.FT_1X2,
    "winner": MarketType.FT_1X2,
    "totals 2.5": MarketType.FT_TOTALS_2_5,
    "over/under 2.5": MarketType.FT_TOTALS_2_5,
    "over_under_2.5": MarketType.FT_TOTALS_2_5,
    "ft_totals_2_5": MarketType.FT_TOTALS_2_5,
    "o/u 2.5": MarketType.FT_TOTALS_2_5,
    "btts": MarketType.FT_BTTS,
    "both teams to score": MarketType.FT_BTTS,
    "both_teams_to_score": MarketType.FT_BTTS,
    "gg/ng": MarketType.FT_BTTS,
}

#: Selection labels per canonical market type (case-insensitive).
SELECTION_ALIASES: dict[str, OutcomeKind] = {
    "home": OutcomeKind.HOME,
    "1": OutcomeKind.HOME,
    "h": OutcomeKind.HOME,
    "draw": OutcomeKind.DRAW,
    "x": OutcomeKind.DRAW,
    "d": OutcomeKind.DRAW,
    "away": OutcomeKind.AWAY,
    "2": OutcomeKind.AWAY,
    "a": OutcomeKind.AWAY,
    "over 2.5": OutcomeKind.OVER,
    "over2.5": OutcomeKind.OVER,
    "o 2.5": OutcomeKind.OVER,
    "over": OutcomeKind.OVER,
    "under 2.5": OutcomeKind.UNDER,
    "under2.5": OutcomeKind.UNDER,
    "u 2.5": OutcomeKind.UNDER,
    "under": OutcomeKind.UNDER,
    "yes": OutcomeKind.YES,
    "y": OutcomeKind.YES,
    "gg": OutcomeKind.YES,
    "no": OutcomeKind.NO,
    "n": OutcomeKind.NO,
    "ng": OutcomeKind.NO,
}

#: Which outcome kinds are legal inside each market family.
SUPPORTED_SELECTIONS: dict[MarketType, frozenset[OutcomeKind]] = {
    MarketType.FT_1X2: frozenset({OutcomeKind.HOME, OutcomeKind.DRAW, OutcomeKind.AWAY}),
    MarketType.FT_TOTALS_2_5: frozenset({OutcomeKind.OVER, OutcomeKind.UNDER}),
    MarketType.FT_BTTS: frozenset({OutcomeKind.YES, OutcomeKind.NO}),
}

TOTALS_LINE = Decimal("2.5")


@dataclass(frozen=True, slots=True)
class ParsedManualCsv:
    """Everything one operator CSV yields, in canonical shape."""

    events: tuple[ProviderEvent, ...]
    markets: tuple[ProviderMarket, ...]
    exported_at: dt.datetime | None = None


def _market_type(raw: str, *, where: str) -> MarketType:
    key = raw.strip().lower()
    try:
        return MARKET_ALIASES[key]
    except KeyError as exc:
        raise ParserDriftError(
            f"{where}: unknown market {raw!r}; expected one of {sorted(MARKET_ALIASES)}"
        ) from exc


def _outcome_kind(raw: str, *, market_type: MarketType, where: str) -> OutcomeKind:
    key = raw.strip().lower()
    kind = SELECTION_ALIASES.get(key)
    if kind is None:
        raise ParserDriftError(
            f"{where}: unknown selection {raw!r}; expected one of {sorted(SELECTION_ALIASES)}"
        )
    if kind not in SUPPORTED_SELECTIONS[market_type]:
        raise ParserDriftError(
            f"{where}: selection {raw!r} is not part of {market_type} "
            f"(allowed: {sorted(str(kind) for kind in SUPPORTED_SELECTIONS[market_type])})"
        )
    return kind


def _event_key(*, home_team: str, away_team: str, kickoff_utc: dt.datetime) -> str:
    """Deterministic event id built only from the CSV's own columns."""
    return f"crocobet:{kickoff_utc.isoformat()}:{home_team}-{away_team}"


def _is_naive_timestamp(raw: str) -> bool:
    """True when the text carries no explicit UTC marker (``Z`` or an offset).

    Epoch numbers are absolute, so they are never naive.  The flag lands in the
    event extras and lets a reviewer see where we had to assume UTC.
    """
    text = raw.strip()
    if text.isdigit():
        return False
    if text.endswith(("Z", "z")):
        return False
    return not re.search(r"[+-]\d{2}:?\d{2}$", text)


def parse_manual_csv_text(
    csv_text: str,
    *,
    observed_at: dt.datetime | None = None,
    source_label: str = DEFAULT_FIXTURE_NAME,
) -> ParsedManualCsv:
    """Parse the operator's manual CSV export into canonical DTOs.

    Ingestion reaches this through :class:`CrocobetManualCsvAdapter`, which
    enforces the manual-import policy; the function itself is pure (text in,
    records out) so the manual-import job and the contract tests can reuse it.

    Rules, all strict because the file is an operator contract:

    * every column in :data:`REQUIRED_COLUMNS` must be present;
    * market/selection labels resolve through the documented alias tables - an
      unknown label is drift, never silently ignored;
    * ``odds`` must be decimal odds ``> 1.0`` and ``currency`` non-empty;
    * ``kickoff_utc``/``exported_at`` are parsed to aware UTC
      (``academic_edge_domain.time``); a value without an explicit UTC marker is
      read as UTC and flagged in the event extras as ``kickoff_was_naive``;
    * a duplicated selection inside one market is drift.
    """
    observed = ensure_utc(observed_at) if observed_at is not None else utcnow()
    header, rows = parse_csv_rows(csv_text, where=source_label)
    require_columns(header, REQUIRED_COLUMNS, where=source_label)

    events: dict[str, ProviderEvent] = {}
    market_outcomes: dict[tuple[str, MarketType], list[ProviderOutcome]] = {}
    exported_ats: list[dt.datetime] = []

    for index, row in enumerate(rows, start=2):
        where = f"{source_label} row {index}"
        event_name = require_str(row, "event_name", where=where)
        kickoff_raw = require_str(row, "kickoff_utc", where=where)
        kickoff_utc = require_timestamp(kickoff_raw, where=f"{where}.kickoff_utc")
        home_team = require_str(row, "home_team", where=where)
        away_team = require_str(row, "away_team", where=where)
        market_type = _market_type(require_str(row, "market", where=where), where=where)
        outcome_kind = _outcome_kind(
            require_str(row, "selection", where=where), market_type=market_type, where=where
        )
        odds = require_odds(require_str(row, "odds", where=where), where=f"{where}.odds")
        currency = require_str(row, "currency", where=where)
        exported_at = require_timestamp(
            require_str(row, "exported_at", where=where), where=f"{where}.exported_at"
        )
        exported_ats.append(exported_at)

        event_key = _event_key(home_team=home_team, away_team=away_team, kickoff_utc=kickoff_utc)
        if event_key not in events:
            events[event_key] = ProviderEvent(
                provider_event_id=event_key,
                competition_name=event_name,
                competition_provider_id=None,
                home_name=home_team,
                away_name=away_team,
                start_time_utc=kickoff_utc,
                status="scheduled",
                provenance=build_provenance(
                    source_id=SOURCE_ID,
                    endpoint=source_label,
                    observed_at=observed,
                    provider_timestamp=exported_at,
                    raw_content_type="text/csv",
                    is_synthetic=False,
                    redaction_notes="operator-supplied manual export",
                ),
                extras={
                    "provider_event_name": event_name,
                    "manual_import": True,
                    "operator_exported_at": exported_at.isoformat(),
                    "kickoff_was_naive": _is_naive_timestamp(kickoff_raw),
                },
            )

        market_key = (event_key, market_type)
        outcomes = market_outcomes.setdefault(market_key, [])
        if any(existing.outcome_kind is outcome_kind for existing in outcomes):
            raise ParserDriftError(
                f"{where}: duplicate {market_type} selection {outcome_kind} for {event_key}"
            )
        outcomes.append(
            ProviderOutcome(
                provider_outcome_id=f"{event_key}:{market_type}:{outcome_kind}",
                outcome_kind=outcome_kind,
                decimal_odds=odds,
                available_size=None,
                quoted_at=exported_at,
                currency=currency,
                is_synthetic=False,
                extras={"manual_import": True},
            )
        )

    markets: list[ProviderMarket] = []
    for (event_key, market_type), outcomes in market_outcomes.items():
        markets.append(
            ProviderMarket(
                provider_market_id=f"{event_key}:{market_type}",
                provider_event_id=event_key,
                venue_name=VENUE_NAME,
                venue_kind=VenueKind.BOOKMAKER,
                market_type=market_type,
                outcomes=tuple(outcomes),
                line=TOTALS_LINE if market_type is MarketType.FT_TOTALS_2_5 else None,
                observed_at=observed,
                is_synthetic=False,
                provenance=events[event_key].provenance,
                extras={
                    "manual_import": True,
                    # The export timestamp is the only price timestamp available,
                    # so staleness logic is told exactly where it came from.
                    "quote_time_source": "operator_exported_at",
                },
            )
        )

    LOGGER.info(
        "%s: parsed %d event(s) and %d market(s) from %s",
        SOURCE_ID,
        len(events),
        len(markets),
        source_label,
    )
    return ParsedManualCsv(
        events=tuple(events.values()),
        markets=tuple(markets),
        exported_at=max(exported_ats) if exported_ats else None,
    )


class CrocobetManualCsvAdapter:
    """Manual-import adapter for operator-supplied Crocobet CSV exports.

    There is **no** automated Crocobet path in this build.  Construction calls
    ``require_manual_import("crocobet")`` and refuses any session-like argument
    with :class:`PolicyViolation`; the payload is in-memory text, a local file the
    operator dropped in the inbox, or the frozen sample.  No HTTP, no HTML, no
    browser automation - and no code here that could grow into some.
    """

    source_id = SOURCE_ID
    mode = MANUAL_MODE
    scope = AutomationScope.MANUAL_CSV_ONLY
    venue_name = VENUE_NAME
    network_enabled = NETWORK_ENABLED

    def __init__(
        self,
        policy_registry: SourcePolicyRegistry,
        *,
        settings: Settings | None = None,
        csv_text: str | None = None,
        csv_path: str | Path | None = None,
        fixture_store: FixtureStore | None = None,
        fixture_name: str = DEFAULT_FIXTURE_NAME,
        overrides: Mapping[str, bytes] | None = None,
        session: object | None = None,
        http_client: object | None = None,
        transport: object | None = None,
        base_url: str | None = None,
    ) -> None:
        # Hard gate: "crocobet" must exist and be manual_csv_only.
        self.policy = policy_registry.require_manual_import(SOURCE_ID)
        forbidden = {
            "session": session,
            "http_client": http_client,
            "transport": transport,
            "base_url": base_url,
        }
        supplied = sorted(name for name, value in forbidden.items() if value is not None)
        if supplied:
            raise PolicyViolation(
                f"{SOURCE_ID} is manual-CSV only: refusing to construct with {supplied}. "
                "There is no network code path for this source - see "
                "config/source_policies.yaml and docs/sources-and-terms.md."
            )
        self.settings = settings
        self.store = (
            fixture_store
            if fixture_store is not None
            else FixtureStore(overrides=overrides, source_id=SOURCE_ID)
        )
        self.fixture_name = fixture_name
        self._csv_text = csv_text
        self._csv_path = Path(csv_path) if csv_path is not None else None
        self._parsed: ParsedManualCsv | None = None
        self._source_label: str | None = None
        self.last_payload_bytes: bytes | None = None

    # -- payload loading (local sources only) ------------------------------

    def _load(self) -> ParsedManualCsv:
        """Load and parse the operator payload once per adapter instance.

        Sources, in order: in-memory text, an operator file path, the frozen
        sample.  Every one of them is local bytes; nothing is fetched.
        """
        if self._parsed is not None:
            return self._parsed
        if self._csv_text is not None:
            text, label = self._csv_text, "manual-csv:text"
        elif self._csv_path is not None:
            text = self._csv_path.read_text(encoding="utf-8-sig")
            label = str(self._csv_path)
        else:
            text = self.store.read_text(self.fixture_name)
            label = self.fixture_name
        self.last_payload_bytes = text.encode("utf-8")
        self._source_label = label
        self._parsed = parse_manual_csv_text(text, source_label=label)
        return self._parsed
