"""Name normalisation for event resolution.

Resolution quality lives or dies on normalisation done *conservatively*: we strip
tokens that are pure club-name noise, but never a token that can distinguish two
real clubs. ``Manchester United`` and ``Manchester City`` must stay different
after normalisation (the golden test asserts this), so tokens like
``united``/``city``/``dynamo``/``real``/``inter`` are NEVER stripped.
"""

from __future__ import annotations

import re
import unicodedata

# Pure noise tokens (legal/organisational forms). Deliberately short and safe:
# none of these can be the distinguishing word of a real club name.
_NOISE_TOKENS = frozenset(
    {
        "fc",
        "cf",
        "sc",
        "afc",
        "cfc",
        "ac",
        "as",
        "ss",
        "us",
        "ud",
        "cd",
        "ca",
        "fk",
        "sk",
        "bk",
        "if",
        "ik",
        "sv",
        "tsv",
        "vfb",
        "vfl",
        "spb",
        "club",
        "the",
        "of",
        "and",
        "et",
        "de",
        "des",
        "du",
        "la",
        "le",
        "los",
        "las",
        "el",
        "il",
        "kf",  # 'kf' = klubb/fotball variants
    }
)

# Common provider abbreviations that are unambiguous in football feeds.
# Conservative by design: only expand tokens whose full form is effectively
# unique in club naming, never generic ones.
_ABBREVIATIONS = {
    "utd": "united",
    "man": "manchester",  # in feeds, "Man City"/"Man Utd" always mean Manchester
    "ath": "athletic",
    "munchen": "munich",
    "univ": "universidad",
}

# Multi-word aliases: canonicalise known alternative club names BEFORE token
# expansion. This is the seed table; learned aliases live in the
# participant_alias table and are applied by the resolver service layer.
_ALIAS_PHRASES = {
    "psg": "paris saint germain",
    "internazionale": "inter",
    "inter milan": "inter",
    "fc inter": "inter",
    "athletic bilbao": "athletic club",
    "athletic club bilbao": "athletic club",
}

_PHRASE_RE = re.compile(r"\b(" + "|".join(sorted(_ALIAS_PHRASES, key=len, reverse=True)) + r")\b")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _expand_abbreviations(text: str) -> str:
    """Canonicalise alias phrases, then expand unambiguous abbreviations."""
    text = _PHRASE_RE.sub(lambda m: _ALIAS_PHRASES[m.group(0)], text)
    return " ".join(_ABBREVIATIONS.get(token, token) for token in text.split())


def _fold_unicode(text: str) -> str:
    """NFKD-fold, drop combining marks, casefold."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.casefold()


def strip_common_suffixes(text: str) -> str:
    """Remove noise tokens, keeping at least one meaningful token."""
    tokens = [t for t in text.split() if t]
    meaningful = [t for t in tokens if t not in _NOISE_TOKENS]
    return " ".join(meaningful if meaningful else tokens)


def normalize_name(text: str | None) -> str:
    """Normalise a participant name for comparison.

    Order matters: alias phrases are canonicalised FIRST (so "Athletic Bilbao"
    and "Athletic Club" converge before any token is stripped), then pure-noise
    tokens are dropped, then unambiguous abbreviations are expanded. Empty/None
    input normalises to ``""`` and will never match anything.
    """
    if not text:
        return ""
    folded = _fold_unicode(text)
    folded = _PUNCT_RE.sub(" ", folded)
    folded = _WS_RE.sub(" ", folded).strip()
    folded = _expand_abbreviations(folded)
    folded = strip_common_suffixes(folded)
    return _expand_abbreviations(folded)


def normalize_competition(text: str | None) -> str:
    """Normalise a competition name (same rules, plus common synonym folding)."""
    if not text:
        return ""
    name = normalize_name(text)
    replacements = {
        "premier league": "premier league",
        "primera division": "laliga",
        "primera": "laliga",
        "serie a": "seriea",
        "bundesliga": "bundesliga",
        "ligue 1": "ligue1",
        "champions league": "ucl",
        "uefa champions league": "ucl",
    }
    for needle, replacement in replacements.items():
        if needle in name:
            name = name.replace(needle, replacement)
            break
    return name


def canonical_key(kind: str, *parts: str | None) -> str:
    """Deterministic identity key, e.g. ``participant|real|madrid``.

    ``None`` parts become empty strings so keys stay stable; callers must not
    rely on a key built from empty parts being meaningful.
    """
    cleaned = [normalize_name(p) for p in parts if p]
    return "|".join([kind.strip().lower(), *cleaned])
