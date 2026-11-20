"""Typo-tolerant name matching, mirroring the frontend's src/lib/fuzzySearch.js."""
from __future__ import annotations

import re
from typing import Iterable


def compact_text(value) -> str:
    """Lower-case letters and digits only, so "Mama-Njeri" and "mama njeri" compare equal."""
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i in range(1, len(left) + 1):
        diagonal, previous[0] = previous[0], i
        for j in range(1, len(right) + 1):
            above = previous[j]
            previous[j] = diagonal if left[i - 1] == right[j - 1] else 1 + min(diagonal, above, previous[j - 1])
            diagonal = above
    return previous[len(right)]


def match_names(named_ids: Iterable[tuple[int, str]], term: str) -> tuple[list[int], bool]:
    """Return (matching ids, typo_matched).

    Substring matches (ignoring spaces, dashes and case) win. Only when nothing matches that way
    are names within a couple of typos returned, and typo_matched is True so the caller can say so.
    """
    rows = [(row_id, name) for row_id, name in named_ids if name]
    plain, compact = str(term or '').strip().lower(), compact_text(term)
    if not plain:
        return [], False

    exact = [row_id for row_id, name in rows if plain in name.lower() or (compact and compact in compact_text(name))]
    if exact or len(compact) < 3:
        return exact, False

    allowed_typos = max(1, len(compact) // 3)
    close = []
    for row_id, name in rows:
        candidates = [compact_text(part) for part in [name, *name.split()] if compact_text(part)]
        if candidates and min(edit_distance(compact, candidate) for candidate in candidates) <= allowed_typos:
            close.append(row_id)
    return close, bool(close)
