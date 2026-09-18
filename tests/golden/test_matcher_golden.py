"""Matcher golden set, including adversarial false-positive traps.

The brief's precision target is >= 99.5% on auto-accepted pairs. Against a
golden set that means *zero* false auto-accepts: any single wrong
AUTO_ACCEPTED decision fails this suite.
"""

from __future__ import annotations

import datetime as dt

import pytest
from academic_edge_domain.enums import HardRejectReason, ReviewStatus
from academic_edge_resolver import CandidateEvent, ResolverConfig, best_match, match_event

UTC = dt.UTC
KICKOFF = dt.datetime(2026, 3, 14, 15, 0, tzinfo=UTC)
CONFIG = ResolverConfig()

# key: (competition, home, away, kickoff offset minutes, venue, round)
CANONICAL = {
    "mun_city": (
        "Premier League",
        "Manchester United",
        "Manchester City",
        0,
        "Old Trafford",
        "Matchweek 28",
    ),
    "shef_un_wed": (
        "Championship",
        "Sheffield United",
        "Sheffield Wednesday",
        0,
        "Bramall Lane",
        "Round 35",
    ),
    "barca_real": ("LaLiga", "Barcelona", "Real Madrid", 0, "Estadi Olimpic", "Jornada 27"),
    "bayen_dort": (
        "Bundesliga",
        "FC Bayern Munchen",
        "Borussia Dortmund",
        0,
        "Allianz Arena",
        "Spieltag 24",
    ),
    "inter_juve": ("Serie A", "Inter", "Juventus", 0, "San Siro", "Giornata 27"),
    "psg_lille": ("Ligue 1", "Paris Saint Germain", "Lille", 0, "Parc des Princes", "Journee 24"),
    "atletico_betis": ("LaLiga", "Atletico Madrid", "Real Betis", 0, "Metropolitano", "Jornada 27"),
    "sport_cp_rio": ("Liga Portugal", "Sporting CP", "Rio Ave", 0, "Jose Alvalade", "Jornada 24"),
    "barca_b": ("LaLiga 2", "Barcelona B", "Amorebieta", 0, "Johan Cruyff", "Jornada 30"),
    "athletic_real": ("LaLiga", "Athletic Bilbao", "Real Sociedad", 0, "San Mames", "Jornada 27"),
}


class _Row:
    """Duck-typed canonical event satisfying the ExistingEventLike protocol."""

    def __init__(
        self,
        event_id: str,
        competition: str,
        home: str,
        away: str,
        kickoff: dt.datetime,
        venue: str | None,
        rnd: str | None,
    ) -> None:
        self.id = event_id
        self.competition_name = competition
        self.home_name = home
        self.away_name = away
        self.start_time_utc = kickoff
        self.venue_name = venue
        self.round_label = rnd

    def __repr__(self) -> str:  # pragma: no cover - test failure aid
        return f"<Row {self.id}: {self.home_name} v {self.away_name}>"


def _existing(key: str) -> _Row:
    comp, home, away, offset, venue, rnd = CANONICAL[key]
    return _Row(key, comp, home, away, KICKOFF + dt.timedelta(minutes=offset), venue, rnd)


def _candidate(
    event_id: str,
    competition: str,
    home: str,
    away: str,
    *,
    offset_minutes: int = 0,
    venue: str | None = None,
    rnd: str | None = None,
) -> CandidateEvent:
    return CandidateEvent(
        provider_event_id=event_id,
        source_id="api_football",
        competition_name=competition,
        home_name=home,
        away_name=away,
        start_time_utc=KICKOFF + dt.timedelta(minutes=offset_minutes),
        venue_name=venue,
        round_label=rnd,
    )


# (candidate, existing_key, expected status, hard rejects that MUST appear)
GOLDEN: list[tuple[CandidateEvent, str, ReviewStatus, set[HardRejectReason]]] = [
    # ---- true positives: must match ------------------------------------------
    (
        _candidate("g1", "Premier League", "Manchester Utd", "Man City", venue="Old Trafford"),
        "mun_city",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    (
        _candidate("g2", "Premier League", "Man United", "Manchester City"),
        "mun_city",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    (
        _candidate("g3", "Bundesliga", "Bayern Munich", "Borussia Dortmund", venue="Allianz Arena"),
        "bayen_dort",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    (
        _candidate("g4", "Serie A", "Internazionale", "Juventus", venue="San Siro"),
        "inter_juve",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    (
        _candidate("g5", "Ligue 1", "PSG", "Lille", venue="Parc des Princes"),
        "psg_lille",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    (
        _candidate("g6", "Liga Portugal", "Sporting CP", "Rio Ave"),
        "sport_cp_rio",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    (
        _candidate("g7", "LaLiga", "Atletico Madrid", "Real Betis"),
        "atletico_betis",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    # kickoff 5 minutes apart must still match
    (
        _candidate(
            "g8",
            "Premier League",
            "Manchester United",
            "Manchester City",
            offset_minutes=5,
            venue="Old Trafford",
        ),
        "mun_city",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
    # ---- adversarial false-positive traps: must NOT auto-accept ---------------
    (
        _candidate("a1", "Premier League", "Manchester City", "Manchester United", venue="Etihad"),
        "mun_city",
        ReviewStatus.REJECTED,
        {HardRejectReason.HOME_AWAY_INVERSION},
    ),
    (
        _candidate("a2", "Championship", "Sheffield Wednesday", "Sheffield United"),
        "shef_un_wed",
        ReviewStatus.REJECTED,
        {HardRejectReason.HOME_AWAY_INVERSION},
    ),
    (
        _candidate(
            "a3", "Championship", "Sheffield Wednesday", "Sheffield United", venue="Hillsborough"
        ),
        "mun_city",
        ReviewStatus.REJECTED,
        {HardRejectReason.COMPETITION_MISMATCH},
    ),
    # Barcelona SC (Ecuador) vs Barcelona (Spain): names alone look identical,
    # the COMPETITION is what separates them -- and it must.
    (
        _candidate("a4", "Liga Pro Ecuador", "Barcelona SC", "Real Madrid", venue="Monumental"),
        "barca_real",
        ReviewStatus.REJECTED,
        {HardRejectReason.COMPETITION_MISMATCH},
    ),
    (
        _candidate("a5", "LaLiga", "Real Sociedad", "Real Madrid", venue="Anoeta"),
        "barca_real",
        ReviewStatus.REJECTED,
        {HardRejectReason.PARTICIPANT_MISMATCH},
    ),
    (
        _candidate("a6", "MLS", "Inter Miami", "Juventus", venue="Chase Stadium"),
        "inter_juve",
        ReviewStatus.REJECTED,
        {HardRejectReason.COMPETITION_MISMATCH, HardRejectReason.PARTICIPANT_MISMATCH},
    ),
    # kickoff 6 hours apart: outside the window whatever the names say
    (
        _candidate(
            "a7",
            "Premier League",
            "Manchester United",
            "Manchester City",
            offset_minutes=360,
            venue="Old Trafford",
        ),
        "mun_city",
        ReviewStatus.REJECTED,
        {HardRejectReason.START_TIME_OUT_OF_WINDOW},
    ),
    # reserve team must not auto-accept the senior side
    (
        _candidate("a8", "LaLiga", "Barcelona B", "Real Madrid"),
        "barca_real",
        ReviewStatus.REJECTED,
        {HardRejectReason.PARTICIPANT_MISMATCH},
    ),
    # ---- genuine review cases: right clubs, imperfect evidence ---------------
    # same club under its alias ("Athletic Bilbao" -> "athletic club"), kickoff
    # 30 minutes apart: enough time drift to lose auto-accept, clearly not a reject
    (
        _candidate(
            "r2", "LaLiga", "Athletic Club", "Real Sociedad", offset_minutes=30, venue="San Mames"
        ),
        "athletic_real",
        ReviewStatus.REVIEW_REQUIRED,
        set(),
    ),
    # same clubs, same everything, but the away side spelled differently and
    # venue missing: still comfortably auto-accepted
    (
        _candidate("r3", "LaLiga", "Athletic Bilbao", "Real Sociedad"),
        "athletic_real",
        ReviewStatus.AUTO_ACCEPTED,
        set(),
    ),
]


@pytest.mark.golden
class TestMatcherGoldenSet:
    def test_case_count_is_meaningful(self) -> None:
        assert len(GOLDEN) >= 15

    def test_every_case_matches_expectation(self) -> None:
        for candidate, existing_key, expected, must_reject in GOLDEN:
            decision = match_event(candidate, _existing(existing_key), CONFIG)
            assert decision.status is expected, (
                f"{candidate.provider_event_id} vs {existing_key}: expected {expected}, "
                f"got {decision.status} (score={decision.score}, "
                f"rejects={[str(r) for r in decision.hard_rejects]}, "
                f"scores={decision.component_scores})"
            )
            if must_reject:
                missing = must_reject - set(decision.hard_rejects)
                assert not missing, (
                    f"{candidate.provider_event_id}: missing expected rejects "
                    f"{[str(r) for r in missing]}"
                )

    def test_zero_false_auto_accepts_precision_target(self) -> None:
        """Brief target: >= 99.5% precision on alert candidates (zero tolerance here)."""
        false_accepts = [
            candidate.provider_event_id
            for candidate, existing_key, expected, _ in GOLDEN
            if expected is not ReviewStatus.AUTO_ACCEPTED
            and match_event(candidate, _existing(existing_key), CONFIG).status
            is ReviewStatus.AUTO_ACCEPTED
        ]
        assert not false_accepts, f"false auto-accepts: {false_accepts}"

    def test_recall_on_true_positives(self) -> None:
        for candidate, existing_key, expected, _ in GOLDEN:
            if expected is not ReviewStatus.AUTO_ACCEPTED:
                continue
            decision = match_event(candidate, _existing(existing_key), CONFIG)
            assert decision.status is ReviewStatus.AUTO_ACCEPTED, (
                f"missed true positive {candidate.provider_event_id}: {decision.status} "
                f"score={decision.score} rejects={[str(r) for r in decision.hard_rejects]}"
            )

    def test_best_match_prefers_non_rejected(self) -> None:
        candidate = _candidate(
            "bm1", "Premier League", "Manchester United", "Manchester City", venue="Old Trafford"
        )
        decision = best_match(candidate, [_existing("mun_city"), _existing("barca_real")], CONFIG)
        assert decision is not None
        assert decision.matched_event_id == "mun_city"

    def test_best_match_returns_none_when_empty(self) -> None:
        assert best_match(_candidate("bm2", "X", "A", "B"), [], CONFIG) is None

    def test_config_rejects_bad_weights(self) -> None:
        with pytest.raises(ValueError):
            ResolverConfig(weights={"participant": 0.9, "time": 0.9})


def _key_for(candidate: CandidateEvent) -> str:
    for key, (_comp, home, away, _off, _venue, _rnd) in CANONICAL.items():
        if candidate.home_name in (home, away) or candidate.away_name in (home, away):
            return key
    raise KeyError(candidate.home_name)
