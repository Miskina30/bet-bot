"""String similarity for entity matching.

Pure stdlib, deterministic, symmetric. :func:`name_similarity` blends three
complementary measures and short-circuits to exactly 1.0 when the *normalised*
names are identical -- which is what makes ``PSG`` vs ``Paris Saint-Germain``
match once aliases/normalisation agree, without hand-tuned fuzz.
"""

from __future__ import annotations

from collections import Counter


def _jaro(a: str, b: str) -> float:
    """Jaro similarity in [0, 1]."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    len_a, len_b = len(a), len(b)
    match_distance = max(len_a, len_b) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    a_matches = [False] * len_a
    b_matches = [False] * len_b
    matches = 0
    for i, char in enumerate(a):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len_b)
        for j in range(start, end):
            if b_matches[j] or b[j] != char:
                continue
            a_matches[i] = b_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0

    transpositions = 0
    b_index = 0
    for i in range(len_a):
        if not a_matches[i]:
            continue
        while not b_matches[b_index]:
            b_index += 1
        if a[i] != b[b_index]:
            transpositions += 1
        b_index += 1
    transpositions //= 2

    m = float(matches)
    return (m / len_a + m / len_b + (m - transpositions) / m) / 3.0


def jaro_winkler(a: str, b: str, *, prefix_scale: float = 0.1, max_prefix: int = 4) -> float:
    """Jaro-Winkler: boosts strings sharing a common prefix."""
    base = _jaro(a, b)
    if base == 0.0:
        return 0.0
    prefix = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        prefix += 1
        if prefix == max_prefix:
            break
    return base + prefix * prefix_scale * (1.0 - base)


def levenshtein_ratio(a: str, b: str) -> float:
    """``1 - distance / max(len)`` in [0, 1]."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    distance = previous[-1]
    return 1.0 - distance / max(len(a), len(b))


def token_set_ratio(a: str, b: str) -> float:
    """Jaccard-style overlap of token multisets, in [0, 1].

    Multiset (not set) intersection so repeated tokens are not over-credited.
    """
    tokens_a = Counter(a.split())
    tokens_b = Counter(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = sum((tokens_a & tokens_b).values())
    total = max(sum(tokens_a.values()), sum(tokens_b.values()))
    return overlap / total


def name_similarity(a: str | None, b: str | None) -> float:
    """Blended similarity of two (already normalised) names.

    Exact normalised equality is 1.0. Otherwise:
    ``0.60 * jaro_winkler + 0.25 * token_set + 0.15 * levenshtein``.

    Weights favour prefix-consistent spelling agreement, which is what real
    provider aliases differ by ("Athletic Club" vs "Athletic Bilbao").
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return round(
        0.60 * jaro_winkler(a, b) + 0.25 * token_set_ratio(a, b) + 0.15 * levenshtein_ratio(a, b),
        6,
    )


def similarity_symmetric(a: str, b: str) -> float:
    """Guard for callers worried about argument order (all measures here are symmetric)."""
    forward = name_similarity(a, b)
    backward = name_similarity(b, a)
    return max(forward, backward)
