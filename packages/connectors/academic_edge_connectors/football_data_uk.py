"""football-data.co.uk adapter: public historical CSV with closing odds.

Scope is ``bulk_static_download`` (see ``config/source_policies.yaml``): we
download well-known static CSV files at most daily, never scrape pages and never
touch a betting page.

Two entry points matter:

* :class:`FootballDataUkAdapter` - the :class:`ProviderAdapter` used by ingest;
* :func:`load_historical_matches` - a small, documented helper the forecasting
  package depends on.  It turns CSV *text* into :class:`HistoricalMatch` records
  with ``None`` for any missing price (never ``0``, which downstream pricing
  would turn into a fake edge).

Column contract (verbatim provider columns; nothing else is read):

======================  ====================================================
``Div, Date, Time``     division code and kickoff
``HomeTeam, AwayTeam``  participants
``FTHG, FTAG, FTR``     full-time goals and result (H/D/A)
``B365H/B365D/B365A``   Bet365 full-time 1X2
``PSH/PSD/PSA``         Pinnacle full-time 1X2
``PSCH/PSCD/PSCA``      Pinnacle full-time 1X2, *closing*
``P>2.5, P<2.5``        Pinnacle over/under 2.5 goals
``B365>2.5, B365<2.5``  Bet365 over/under 2.5 goals
======================  ====================================================
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
from academic_edge_domain.enums import AutomationScope, MarketType, OutcomeKind, VenueKind
from academic_edge_domain.policy import SourcePolicyRegistry
from academic_edge_domain.settings import Settings
from academic_edge_domain.time import (
    UTC,
    TimestampParseError,
    ensure_utc,
    parse_timestamp,
    utcnow,
)

from academic_edge_connectors.base import (
    AdapterUnavailable,
    ConnectorError,
    ParserDriftError,
    Provenance,
    ProviderEvent,
)
from academic_edge_connectors.contracts import (
    HealthReport,
    ProviderMarket,
    ProviderOutcome,
    ProviderUpdate,
    build_provenance,
)
from academic_edge_connectors.fixture_io import FixtureStore
from academic_edge_connectors.http import FIXTURE_MODE, LIVE_MODE, ProviderHttpClient
from academic_edge_connectors.parsing import (
    parse_csv_rows,
    require_columns,
    require_int,
    require_odds,
    require_str,
)

__all__ = [
    "CLOSING_ODDS_SOURCES",
    "DEFAULT_DIVISION",
    "DEFAULT_FIXTURE_NAME",
    "HISTORICAL_1X2_PRECEDENCE",
    "HISTORICAL_TOTALS_PRECEDENCE",
    "REQUIRED_COLUMNS",
    "SOURCE_ID",
    "ClosingOddsSource",
    "FootballDataUkAdapter",
    "HistoricalMatch",
    "build_csv_url",
    "load_historical_matches",
    "load_historical_matches_from_file",
    "season_code",
    "season_code_from_start_year",
]

LOGGER = logging.getLogger(__name__)

SOURCE_ID = "football_data_uk"
SCOPE = AutomationScope.BULK_STATIC_DOWNLOAD
DEFAULT_DIVISION = "E0"
DEFAULT_FIXTURE_NAME = "football_data_uk_E0_sample.csv"
DEFAULT_STREAM_INTERVAL_SECONDS = 6 * 60 * 60.0

#: Columns whose absence means the payload is not a football-data.co.uk results
#: file at all - contract drift, not "an old file without odds".
REQUIRED_COLUMNS: tuple[str, ...] = (
    "Div",
    "Date",
    "HomeTeam",
    "AwayTeam",
    "FTHG",
    "FTAG",
    "FTR",
)

#: Odds columns the historical loader prefers, in order: the explicitly closing
#: Pinnacle columns first, then Pinnacle, then Bet365.
HISTORICAL_1X2_PRECEDENCE: tuple[tuple[str, str, str], ...] = (
    ("PSCH", "PSCD", "PSCA"),
    ("PSH", "PSD", "PSA"),
    ("B365H", "B365D", "B365A"),
)
HISTORICAL_TOTALS_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("P>2.5", "P<2.5"),
    ("B365>2.5", "B365<2.5"),
)

#: Values the provider uses for "no price here"; ``0`` is not a valid price, so
#: it is treated as missing rather than parsed into ``Decimal("0")``.
MISSING_ODDS_MARKERS = frozenset({"", "-", "n/a", "na", "0", "0.0", "0.00"})

#: Totals markets are the 2.5 line by definition of the column names.
TOTALS_LINE = Decimal("2.5")


@dataclass(frozen=True, slots=True)
class ClosingOddsSource:
    """One venue's column group inside a football-data.co.uk CSV.

    ``columns`` are aligned positionally with ``outcome_kinds``::

        ClosingOddsSource("B365", BOOKMAKER, FT_1X2,
                          ("B365H", "B365D", "B365A"),
                          (HOME, DRAW, AWAY))
    """

    venue_name: str
    venue_kind: VenueKind
    market_type: MarketType
    columns: tuple[str, ...]
    outcome_kinds: tuple[OutcomeKind, ...]

    def __post_init__(self) -> None:
        if len(self.columns) != len(self.outcome_kinds):
            raise ConnectorError(
                f"{self.venue_name}/{self.market_type}: {len(self.columns)} columns for "
                f"{len(self.outcome_kinds)} outcomes"
            )


CLOSING_ODDS_SOURCES: tuple[ClosingOddsSource, ...] = (
    ClosingOddsSource(
        "B365",
        VenueKind.BOOKMAKER,
        MarketType.FT_1X2,
        ("B365H", "B365D", "B365A"),
        (OutcomeKind.HOME, OutcomeKind.DRAW, OutcomeKind.AWAY),
    ),
    ClosingOddsSource(
        "Pinnacle",
        VenueKind.BOOKMAKER,
        MarketType.FT_1X2,
        ("PSH", "PSD", "PSA"),
        (OutcomeKind.HOME, OutcomeKind.DRAW, OutcomeKind.AWAY),
    ),
    ClosingOddsSource(
        "Pinnacle Closing",
        VenueKind.BOOKMAKER,
        MarketType.FT_1X2,
        ("PSCH", "PSCD", "PSCA"),
        (OutcomeKind.HOME, OutcomeKind.DRAW, OutcomeKind.AWAY),
    ),
    ClosingOddsSource(
        "Pinnacle",
        VenueKind.BOOKMAKER,
        MarketType.FT_TOTALS_2_5,
        ("P>2.5", "P<2.5"),
        (OutcomeKind.OVER, OutcomeKind.UNDER),
    ),
    ClosingOddsSource(
        "B365",
        VenueKind.BOOKMAKER,
        MarketType.FT_TOTALS_2_5,
        ("B365>2.5", "B365<2.5"),
        (OutcomeKind.OVER, OutcomeKind.UNDER),
    ),
)


@dataclass(frozen=True, slots=True)
class HistoricalMatch:
    """One completed match with closing odds, for forecasting/backtesting.

    Every odds field is ``None`` when the CSV carried no usable price for that
    selection - never ``0``.  ``competition_code`` and ``division`` are both the
    provider's ``Div`` value (e.g. ``"E0"``): the payload does not contain a
    competition name, and inventing one would poison later matchers.
    """

    played_on: dt.date
    competition_code: str
    division: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    odds_home: Decimal | None
    odds_draw: Decimal | None
    odds_away: Decimal | None
    odds_over_2_5: Decimal | None
    odds_under_2_5: Decimal | None
    source_id: str = SOURCE_ID

    @property
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    @property
    def result(self) -> str:
        """``"H"``, ``"D"`` or ``"A"`` - the provider's own ``FTR`` vocabulary."""
        if self.home_goals > self.away_goals:
            return "H"
        if self.home_goals < self.away_goals:
            return "A"
        return "D"

    @property
    def both_teams_scored(self) -> bool:
        return self.home_goals > 0 and self.away_goals > 0

    @property
    def went_over_2_5(self) -> bool:
        return self.total_goals > 2


def season_code_from_start_year(start_year: int) -> str:
    """``2026`` -> ``"2627"``: the provider names a season by both end years."""
    if not 1900 <= start_year <= 2999:
        raise ValueError(f"implausible season start year: {start_year}")
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_code(season: str | int) -> str:
    """Normalise a season label into the ``yyyyss`` path segment.

    Accepted: ``2026``/``"2026"`` (start year), ``"2026/2027"``,
    ``"2026-2027"``, ``"2026-27"`` and an already-normalised ``"2627"``.
    """
    if isinstance(season, int):
        return season_code_from_start_year(season)
    text = season.strip()
    if not text:
        raise ValueError("season must not be empty")
    head = re.split(r"[/-]", text, maxsplit=1)[0].strip()
    if len(head) == 4 and head.isdigit():
        if re.search(r"[/-]", text):
            return season_code_from_start_year(int(head))
        # A bare 4-digit value is a start year when it looks like one (2026);
        # otherwise it is already the two-end-year code (2627).
        return season_code_from_start_year(int(head)) if head[:2] in {"19", "20"} else head
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) == 4:
        return digits
    raise ValueError(f"cannot interpret season {season!r}; expected e.g. '2026/2027' or '2627'")


def build_csv_url(*, base_url: str, season: str | int, division: str = DEFAULT_DIVISION) -> str:
    """Build the documented static CSV URL for a season/division."""
    clean_division = division.strip()
    if not clean_division:
        raise ValueError("division must not be empty")
    return f"{base_url.rstrip('/')}/mmz4281/{season_code(season)}/{clean_division}.csv"


@dataclass(frozen=True, slots=True)
class ParsedResultsCsv:
    """Everything one results CSV yields, in canonical shape."""

    events: tuple[ProviderEvent, ...]
    markets: tuple[ProviderMarket, ...]
    historical: tuple[HistoricalMatch, ...]


def _parse_date(text: str, *, where: str) -> dt.date:
    """Parse a provider ``Date`` cell (``dd/mm/yyyy`` or ``dd/mm/yy``)."""
    try:
        return parse_timestamp(text).date()
    except TimestampParseError:
        pass
    for fmt in ("%d/%m/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    raise ParserDriftError(f"{where}: cannot parse Date {text!r}")


def _parse_kickoff(
    row: Mapping[str, str], *, played_on: dt.date, where: str
) -> tuple[dt.datetime, bool]:
    """Return ``(kickoff_utc, time_was_absent)``.

    The file carries ``Date`` always and ``Time`` only for some seasons.  When
    ``Time`` is absent the kickoff is reported at 00:00 UTC *and* flagged in the
    event extras (``kickoff_time_absent``) so no caller mistakes it for a real
    kickoff time.
    """
    raw = (row.get("Time") or "").strip()
    if not raw:
        return dt.datetime.combine(played_on, dt.time(0, 0), tzinfo=UTC), True
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return dt.datetime.combine(
                played_on, dt.datetime.strptime(raw, fmt).time(), tzinfo=UTC
            ), False
        except ValueError:
            continue
    raise ParserDriftError(f"{where}: cannot parse Time {raw!r}")


def _optional_odds(row: Mapping[str, str], column: str, *, where: str) -> Decimal | None:
    """Return a price from an odds column, or ``None`` when it is absent.

    The provider uses empty cells and literal ``0`` for "no price"; both map to
    ``None`` (never to ``Decimal("0")``, which would be an unquotable price).
    A *present but unparseable* or ``<= 1.0`` value is contract drift.
    """
    raw = row.get(column)
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in MISSING_ODDS_MARKERS:
        return None
    return require_odds(text, where=f"{where}.{column}")


def _optional_goals(row: Mapping[str, str], column: str, *, where: str) -> int | None:
    """Return a goal count, or ``None`` when the cell is empty."""
    raw = (row.get(column) or "").strip()
    if not raw:
        return None
    value = require_int({column: raw}, column, where=f"{where}.{column}")
    if value < 0:
        raise ParserDriftError(f"{where}.{column}: goal counts cannot be negative ({value})")
    return value


def _event_key(*, division: str, played_on: dt.date, home_team: str, away_team: str) -> str:
    """Deterministic event id derived from the row's own columns.

    The CSV has no id column, so the key is ``Div:YYYY-MM-DD:Home-Away``.  It is
    derived only from provider data and is stable across re-downloads.
    """
    return f"{division}:{played_on.isoformat()}:{home_team}-{away_team}"


def _market_key(*, event_key: str, source: ClosingOddsSource) -> str:
    return f"{event_key}:{source.venue_name}:{source.market_type}"


def _row_markets(
    row: Mapping[str, str],
    *,
    event_key: str,
    kickoff_utc: dt.datetime,
    observed_at: dt.datetime,
    provenance: Provenance,
    is_synthetic: bool,
    where: str,
) -> list[ProviderMarket]:
    """Build every market the row can support; incomplete venues are skipped.

    A venue is only emitted when **all** of its columns carry a usable price: a
    1X2 market missing its draw leg is not a market, and fabricating the missing
    leg is exactly what the brief forbids.  Skips are logged with the columns
    involved so the gap stays visible.
    """
    markets: list[ProviderMarket] = []
    for source in CLOSING_ODDS_SOURCES:
        prices = [_optional_odds(row, column, where=where) for column in source.columns]
        if any(price is None for price in prices):
            LOGGER.debug(
                "%s: skipping %s %s for %s - incomplete closing-odds columns %s",
                where,
                source.venue_name,
                source.market_type,
                event_key,
                list(source.columns),
            )
            continue
        market_key = _market_key(event_key=event_key, source=source)
        outcomes = tuple(
            ProviderOutcome(
                provider_outcome_id=f"{market_key}:{kind}",
                outcome_kind=kind,
                decimal_odds=price,
                available_size=None,
                quoted_at=kickoff_utc,
                currency=None,
                is_synthetic=is_synthetic,
                extras={"provider_column": column},
            )
            for kind, column, price in zip(
                source.outcome_kinds, source.columns, prices, strict=True
            )
        )
        markets.append(
            ProviderMarket(
                provider_market_id=market_key,
                provider_event_id=event_key,
                venue_name=source.venue_name,
                venue_kind=source.venue_kind,
                market_type=source.market_type,
                outcomes=outcomes,
                line=TOTALS_LINE if source.market_type is MarketType.FT_TOTALS_2_5 else None,
                observed_at=observed_at,
                is_synthetic=is_synthetic,
                provenance=provenance,
                extras={
                    "provider_columns": list(source.columns),
                    # The file stores *closing* prices only and carries no quote
                    # timestamp, so the kickoff time is used and labelled as such.
                    "quote_time_source": "kickoff",
                },
            )
        )
    return markets


def _prefer_odds(
    row: Mapping[str, str], groups: Sequence[tuple[str, ...]], *, where: str
) -> tuple[Decimal | None, ...]:
    """First column group whose every cell carries a usable price.

    Returns an all-``None`` tuple of the right arity when no group is complete,
    so callers get "no price" rather than a partial, mismatched vector.
    """
    for group in groups:
        prices = [_optional_odds(row, column, where=where) for column in group]
        if all(price is not None for price in prices):
            return tuple(prices)
    return tuple(None for _ in groups[0])


def _build_row_records(
    row: Mapping[str, str],
    *,
    where: str,
    source_label: str,
    season_label: str | None,
    observed_at: dt.datetime,
    is_synthetic: bool,
    redaction_note: str | None,
) -> tuple[ProviderEvent, HistoricalMatch, list[ProviderMarket]] | None:
    """Turn one CSV row into ``(event, historical match, markets)``.

    Returns ``None`` when the row has no full-time result (an unplayed or
    abandoned fixture): the file is a *results* file, so such rows are skipped
    instead of being published with invented scores.  Missing or unparseable
    *required* cells still raise :class:`ParserDriftError`.
    """
    division = require_str(row, "Div", where=where)
    played_on = _parse_date(require_str(row, "Date", where=where), where=where)
    home_team = require_str(row, "HomeTeam", where=where)
    away_team = require_str(row, "AwayTeam", where=where)
    home_goals = _optional_goals(row, "FTHG", where=where)
    away_goals = _optional_goals(row, "FTAG", where=where)
    if home_goals is None or away_goals is None:
        return None

    kickoff_utc, time_absent = _parse_kickoff(row, played_on=played_on, where=where)
    event_key = _event_key(
        division=division, played_on=played_on, home_team=home_team, away_team=away_team
    )
    full_time_result = (row.get("FTR") or "").strip() or None

    provenance = build_provenance(
        source_id=SOURCE_ID,
        endpoint=source_label,
        observed_at=observed_at,
        # One CSV yields many records and carries no payload timestamp, so the raw
        # bytes stay on the adapter (``last_payload_bytes``) instead of being
        # duplicated per record.
        provider_timestamp=None,
        raw_bytes=None,
        raw_content_type="text/csv",
        is_synthetic=is_synthetic,
        redacted=redaction_note is not None,
        redaction_notes=redaction_note,
    )

    event = ProviderEvent(
        provider_event_id=event_key,
        competition_name=division,
        competition_provider_id=division,
        home_name=home_team,
        away_name=away_team,
        start_time_utc=kickoff_utc,
        season_label=season_label,
        status="finished",
        home_score=home_goals,
        away_score=away_goals,
        provenance=provenance,
        extras={
            "division_code": division,
            "provider_full_time_result": full_time_result,
            "kickoff_time_absent": time_absent,
        },
    )

    markets = _row_markets(
        row,
        event_key=event_key,
        kickoff_utc=kickoff_utc,
        observed_at=observed_at,
        provenance=provenance,
        is_synthetic=is_synthetic,
        where=where,
    )

    odds_1x2 = _prefer_odds(row, HISTORICAL_1X2_PRECEDENCE, where=where)
    odds_totals = _prefer_odds(row, HISTORICAL_TOTALS_PRECEDENCE, where=where)
    historical = HistoricalMatch(
        played_on=played_on,
        competition_code=division,
        division=division,
        home_team=home_team,
        away_team=away_team,
        home_goals=home_goals,
        away_goals=away_goals,
        odds_home=odds_1x2[0],
        odds_draw=odds_1x2[1],
        odds_away=odds_1x2[2],
        odds_over_2_5=odds_totals[0],
        odds_under_2_5=odds_totals[1],
    )
    return event, historical, markets


def parse_results_csv(
    csv_text: str,
    *,
    source_label: str = SOURCE_ID,
    season_label: str | None = None,
    is_synthetic: bool = False,
    observed_at: dt.datetime | None = None,
    redaction_note: str | None = None,
) -> ParsedResultsCsv:
    """Parse a football-data.co.uk results CSV into canonical DTOs.

    ``is_synthetic`` must be ``True`` whenever the text came from a frozen
    fixture rather than a real download, so every downstream record stays
    labelled.  Rows without a full-time result are skipped and counted.
    """
    observed = ensure_utc(observed_at) if observed_at is not None else utcnow()
    header, rows = parse_csv_rows(csv_text, where=source_label)
    require_columns(header, REQUIRED_COLUMNS, where=source_label)

    events: list[ProviderEvent] = []
    markets: list[ProviderMarket] = []
    historical: list[HistoricalMatch] = []
    skipped = 0
    for index, row in enumerate(rows, start=2):
        where = f"{source_label} row {index}"
        records = _build_row_records(
            row,
            where=where,
            source_label=source_label,
            season_label=season_label,
            observed_at=observed,
            is_synthetic=is_synthetic,
            redaction_note=redaction_note,
        )
        if records is None:
            skipped += 1
            LOGGER.debug("%s: skipped (no full-time result)", where)
            continue
        event, match, row_markets = records
        events.append(event)
        historical.append(match)
        markets.extend(row_markets)

    LOGGER.info(
        "%s: parsed %d match(es), %d market(s); skipped %d row(s) without a result",
        source_label,
        len(events),
        len(markets),
        skipped,
    )
    return ParsedResultsCsv(
        events=tuple(events), markets=tuple(markets), historical=tuple(historical)
    )


def load_historical_matches(csv_text: str) -> list[HistoricalMatch]:
    """Load completed matches with closing odds from football-data.co.uk CSV text.

    Entry point for the forecasting/backtesting package; it is deliberately plain
    and dependency-free:

    * ``played_on`` is a UTC date, ``competition_code``/``division`` are the
      provider's ``Div`` value (e.g. ``"E0"``);
    * every odds field is a :class:`~decimal.Decimal` ``> 1.0`` or ``None`` when
      the file has no usable price - ``None``, never ``0``;
    * odds precedence is Pinnacle-closing (``PSC*``) > Pinnacle (``PS*``) >
      Bet365 (``B365*``) for 1X2, and Pinnacle (``P>*``) > Bet365 (``B365>*``)
      for the 2.5 totals line;
    * rows without a full-time result are skipped, and a payload whose header is
      missing required columns raises
      :class:`~academic_edge_connectors.base.ParserDriftError`.
    """
    return list(parse_results_csv(csv_text, source_label="load_historical_matches").historical)


def load_historical_matches_from_file(path: str | Path) -> list[HistoricalMatch]:
    """Read a saved CSV file (UTF-8, BOM tolerated) and load its matches."""
    return load_historical_matches(Path(path).read_text(encoding="utf-8-sig"))


def _season_label_from_code(code: str) -> str | None:
    """``"2627"`` -> ``"2026/2027"``; ``None`` when the code is not two years."""
    if len(code) != 4 or not code.isdigit():
        return None
    head, tail = int(code[:2]), int(code[2:])
    # Two-digit years below 70 are 20xx, above are 19xx - the provider's own
    # files never reach back further than the 1990s.
    start_year = 2000 + head if head < 70 else 1900 + head
    end_year = 2000 + tail if tail < 70 else 1900 + tail
    return f"{start_year}/{end_year}"


class FootballDataUkAdapter:
    """football-data.co.uk static results CSV (scope ``bulk_static_download``).

    * ``mode="live"`` passes the source-policy gate and downloads
      ``/mmz4281/{yyyyss}/{division}.csv`` with the token bucket from policy.
    * ``mode="fixture"`` reads the frozen, redacted sample in ``tests/fixtures``
      and labels every record ``is_synthetic=True``; it never opens a socket.

    The payload is cached per ``(season, division)`` because the source policy
    asks for at most a daily refresh while the worker polls more often.
    """

    source_id = SOURCE_ID
    scope = SCOPE

    def __init__(
        self,
        settings: Settings,
        policy_registry: SourcePolicyRegistry,
        *,
        mode: str = FIXTURE_MODE,
        division: str = DEFAULT_DIVISION,
        season: str | int | None = None,
        fixture_name: str = DEFAULT_FIXTURE_NAME,
        fixture_store: FixtureStore | None = None,
        overrides: Mapping[str, bytes] | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if mode not in {LIVE_MODE, FIXTURE_MODE}:
            raise ValueError(f"mode must be 'live' or 'fixture', got {mode!r}")
        self.settings = settings
        self.mode = mode
        self.division = division
        self.season = season
        self.fixture_name = fixture_name
        self.store = (
            fixture_store
            if fixture_store is not None
            else FixtureStore(overrides=overrides, source_id=SOURCE_ID)
        )
        self._rng = rng if rng is not None else random.Random()
        self._sleeper = sleeper
        self._cache: dict[str, tuple[bytes, str]] = {}
        self.last_payload_bytes: bytes | None = None
        self.http: ProviderHttpClient | None = None

        if mode == LIVE_MODE:
            if not settings.football_data_uk_enabled:
                raise AdapterUnavailable(
                    f"{SOURCE_ID}: FOOTBALL_DATA_UK_ENABLED is false; refusing to build a "
                    "live client (the fixture/manual path stays available)"
                )
            self.http = ProviderHttpClient(
                source_id=SOURCE_ID,
                policy_registry=policy_registry,
                scope=SCOPE,
                mode=LIVE_MODE,
                base_url=settings.football_data_uk_base_url,
                transport=transport,
                clock=clock,
                sleeper=sleeper,
                rng=rng,
            )

    # -- internals ---------------------------------------------------------

    def _load_payload(
        self, *, season: str | int | None, division: str
    ) -> tuple[bytes, str, str | None]:
        """Return ``(raw_bytes, source_label, season_label)`` for a division/season.

        ``source_label`` is the URL that was fetched or the fixture filename, and
        is what provenance records.
        """
        code = season_code(season) if season is not None else "fixture"
        cache_key = f"{code}/{division}"
        cached = self._cache.get(cache_key)
        label = _season_label_from_code(code)
        if cached is not None:
            return cached[0], cached[1], label

        if self.mode == FIXTURE_MODE:
            raw = self.store.read_bytes(self.fixture_name)
            source_label = self.fixture_name
        else:
            client = self.http
            if client is None:  # pragma: no cover - guarded in __init__
                raise AdapterUnavailable(f"{SOURCE_ID}: live client is not available")
            path = f"/mmz4281/{code}/{division}.csv"
            result = client.get(path)
            source_label = build_csv_url(
                base_url=self.settings.football_data_uk_base_url,
                season=code,
                division=division,
            )
            if not result.ok:
                raise AdapterUnavailable(
                    f"{SOURCE_ID}: HTTP {result.status_code} downloading {source_label}"
                )
            raw = result.content

        self._cache[cache_key] = (raw, source_label)
        self.last_payload_bytes = raw
        return raw, source_label, label

    def _parse(
        self,
        *,
        season: str | int | None,
        division: str,
        observed_at: dt.datetime | None = None,
    ) -> ParsedResultsCsv:
        """Download/read and parse one results CSV into canonical DTOs."""
        raw, source_label, label = self._load_payload(season=season, division=division)
        synthetic = self.mode == FIXTURE_MODE
        return parse_results_csv(
            raw.decode("utf-8-sig"),
            source_label=source_label,
            season_label=label,
            is_synthetic=synthetic,
            observed_at=observed_at,
            redaction_note=(
                "frozen/redacted contract fixture - not live data" if synthetic else None
            ),
        )

    def _resolve_target(
        self, season: str | int | None, division: str | None
    ) -> tuple[str | int | None, str]:
        """Resolve the ``(season, division)`` pair, refusing an unlabelled live read."""
        resolved_season = season if season is not None else self.season
        if resolved_season is None and self.mode == LIVE_MODE:
            raise ValueError(
                f"{SOURCE_ID}: a season is required for live reads, e.g. season='2026/2027'"
            )
        return resolved_season, division or self.division

    # -- ProviderAdapter API ----------------------------------------------

    def discover_events(
        self,
        *,
        window_start: dt.datetime | None = None,
        window_end: dt.datetime | None = None,
        competition_code: str | None = None,
        limit: int | None = None,
        season: str | int | None = None,
        division: str | None = None,
    ) -> list[ProviderEvent]:
        """List completed matches, optionally filtered to a kickoff window.

        ``competition_code`` is the provider's own division code (its ``Div``
        column, e.g. ``E0``) and selects which file to read; the window bounds are
        inclusive and compared in UTC.
        """
        resolved_season, resolved_division = self._resolve_target(
            season, competition_code or division
        )
        parsed = self._parse(season=resolved_season, division=resolved_division)
        events = list(parsed.events)
        if window_start is not None:
            start = ensure_utc(window_start)
            events = [event for event in events if event.start_time_utc >= start]
        if window_end is not None:
            end = ensure_utc(window_end)
            events = [event for event in events if event.start_time_utc <= end]
        events.sort(key=lambda event: event.start_time_utc)
        if limit is not None:
            events = events[: max(0, limit)]
        return events

    def fetch_event(
        self,
        provider_event_id: str,
        *,
        season: str | int | None = None,
        division: str | None = None,
    ) -> ProviderEvent | None:
        """Fetch one match by its derived id (``Div:YYYY-MM-DD:Home-Away``)."""
        resolved_season, resolved_division = self._resolve_target(season, division)
        parsed = self._parse(season=resolved_season, division=resolved_division)
        for event in parsed.events:
            if event.provider_event_id == provider_event_id:
                return event
        LOGGER.info("%s: event %s is not in %s", SOURCE_ID, provider_event_id, resolved_division)
        return None

    def fetch_markets(
        self,
        provider_event_id: str,
        *,
        season: str | int | None = None,
        division: str | None = None,
    ) -> list[ProviderMarket]:
        """Return every closing-odds market the file holds for one match."""
        resolved_season, resolved_division = self._resolve_target(season, division)
        parsed = self._parse(season=resolved_season, division=resolved_division)
        return [
            market for market in parsed.markets if market.provider_event_id == provider_event_id
        ]

    def stream_updates(
        self,
        *,
        interval_seconds: float | None = None,
        max_iterations: int | None = None,
        season: str | int | None = None,
        division: str | None = None,
    ) -> Iterator[ProviderUpdate]:
        """Yield one update per match, earliest kickoff first.

        The file is static and the source policy allows at most a daily refresh,
        so this generator does **not** poll: ``interval_seconds`` merely paces the
        yields when the caller asks for pacing, and ``max_iterations`` bounds how
        many updates are produced.
        """
        resolved_season, resolved_division = self._resolve_target(season, division)
        parsed = self._parse(season=resolved_season, division=resolved_division)
        markets_by_event: dict[str, list[ProviderMarket]] = {}
        for market in parsed.markets:
            markets_by_event.setdefault(market.provider_event_id, []).append(market)
        synthetic = self.mode == FIXTURE_MODE
        ordered = sorted(parsed.events, key=lambda item: item.start_time_utc)
        for emitted, event in enumerate(ordered, start=1):
            if max_iterations is not None and emitted > max_iterations:
                return
            yield ProviderUpdate(
                provider_event_id=event.provider_event_id,
                observed_at=utcnow(),
                markets=tuple(markets_by_event.get(event.provider_event_id, ())),
                event=event,
                sequence=emitted,
                is_synthetic=synthetic,
            )
            more_expected = max_iterations is None or emitted < max_iterations
            if interval_seconds and interval_seconds > 0 and more_expected:
                self._sleeper(interval_seconds * (1.0 + self._rng.uniform(-0.1, 0.1)))

    def historical_matches(
        self, *, season: str | int | None = None, division: str | None = None
    ) -> list[HistoricalMatch]:
        """Load the season's matches for the forecasting/backtesting pipeline.

        A thin wrapper over :func:`load_historical_matches` so the worker reuses
        the same download/caching path instead of re-implementing it.
        """
        resolved_season, resolved_division = self._resolve_target(season, division)
        return list(self._parse(season=resolved_season, division=resolved_division).historical)

    def healthcheck(self) -> HealthReport:
        """Fetch and parse the configured file; never raises.

        This source serves static files and reports no quota, so the quota fields
        stay ``None`` and the report carries row counts instead.
        """
        checked_at = utcnow()
        synthetic = self.mode == FIXTURE_MODE
        try:
            parsed = self._parse(season=self.season, division=self.division)
        except (ConnectorError, ValueError) as exc:
            return HealthReport(
                source_id=SOURCE_ID,
                ok=False,
                mode=self.mode,
                checked_at=checked_at,
                detail={"error": str(exc)},
                is_synthetic=synthetic,
            )
        last_result = self.http.last_result if self.http is not None else None
        return HealthReport(
            source_id=SOURCE_ID,
            ok=True,
            mode=self.mode,
            checked_at=checked_at,
            latency_ms=last_result.elapsed_ms if last_result is not None else None,
            detail={
                "division": self.division,
                "events": len(parsed.events),
                "markets": len(parsed.markets),
                "payload_bytes": len(self.last_payload_bytes or b""),
                "note": "static CSV source: the provider reports no quota",
            },
            is_synthetic=synthetic,
        )

    def close(self) -> None:
        """Close the live HTTP client (no-op in fixture mode)."""
        if self.http is not None:
            self.http.close()
