"""Entity resolution: normalisation, similarity and event matching."""

from __future__ import annotations

from academic_edge_resolver.matcher import (
    CandidateEvent,
    MatchDecision,
    ResolverConfig,
    best_match,
    match_event,
)
from academic_edge_resolver.normalize import canonical_key, normalize_competition, normalize_name
from academic_edge_resolver.similarity import (
    jaro_winkler,
    levenshtein_ratio,
    name_similarity,
    token_set_ratio,
)

__all__ = [
    "CandidateEvent",
    "MatchDecision",
    "ResolverConfig",
    "best_match",
    "canonical_key",
    "jaro_winkler",
    "levenshtein_ratio",
    "match_event",
    "name_similarity",
    "normalize_competition",
    "normalize_name",
    "token_set_ratio",
]
