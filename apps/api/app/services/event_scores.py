"""Read-time cumulative scores for legacy play-by-play placeholder rows."""

from __future__ import annotations

from typing import Any


def cumulative_score(event: Any, previous: tuple[int, int]) -> tuple[int, int]:
    """Project source observations without mutating the raw normalized row.

    Explicit observations include zero-valued corrections. Missing pairs carry
    the previous state. Only legacy rows with unknown presence use the historical
    0-0 sentinel rule; their original ingest discarded source missingness.
    """
    current = (event.home_score, event.away_score)
    observed = getattr(event, "score_observed", None)
    if observed is False or (observed is None and current == (0, 0)):
        return previous
    return current
