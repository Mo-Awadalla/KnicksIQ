"""Read-time cumulative scores for legacy play-by-play placeholder rows."""

from __future__ import annotations

from typing import Any


def cumulative_score(event: Any, previous: tuple[int, int]) -> tuple[int, int]:
    """Carry missing 0-0 rows forward while preserving recorded score corrections.

    NBA non-scoring rows can omit the scoreboard, which older imports stored as
    zeroes. A real game cannot return to 0-0 after scoring. Do not clamp either
    team's nonzero score: reviews can legitimately reduce a recorded score.
    """
    current = (event.home_score, event.away_score)
    return previous if current == (0, 0) else current
