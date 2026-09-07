"""Project legacy run selections onto authoritative cumulative scoreboards."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.event_scores import cumulative_score


def verified_runs(game: Any, events: Iterable[Any], runs: Iterable[Any]) -> list[dict[str, Any]]:
    """Retain selected sequence windows only when their scoring can be verified.

    Cached run points were derived from shot metadata, which is incomplete in
    the legacy feed. Recalculate from the score before the inclusive starting
    event to the score after the inclusive ending event. Never certify a window
    crossing a backward score correction or an unknown event boundary.
    """
    rows = sorted(events, key=lambda event: event.sequence)
    boundaries = {}
    previous = (0, 0)
    corrections = 0
    for index, event in enumerate(rows):
        current = cumulative_score(event, previous)
        before_corrections = corrections
        if any(after < before for before, after in zip(previous, current, strict=True)):
            corrections += 1
        boundaries[event.sequence] = (
            index,
            event,
            previous,
            current,
            before_corrections,
            corrections,
        )
        previous = current

    output = []
    for run in runs:
        start = boundaries.get(run.start_sequence)
        end = boundaries.get(run.end_sequence)
        if start is None or end is None or start[0] > end[0] or start[4] != end[5]:
            continue
        if run.team_id not in {game.home_team_id, game.away_team_id}:
            continue
        home_points, away_points = (
            after - before for before, after in zip(start[2], end[3], strict=True)
        )
        points_for, points_against = (
            (home_points, away_points)
            if run.team_id == game.home_team_id
            else (away_points, home_points)
        )
        if points_for <= points_against:
            continue
        first, last = start[1], end[1]
        output.append(
            {
                "id": getattr(run, "id", None) or 0,
                "game_id": game.id,
                "team_id": run.team_id,
                "period": first.period,
                "end_period": last.period,
                "start_sequence": first.sequence,
                "end_sequence": last.sequence,
                "start_clock": first.clock,
                "end_clock": last.clock,
                "points_for": points_for,
                "points_against": points_against,
                "score_delta": points_for - points_against,
                "event_count": end[0] - start[0] + 1,
                "summary": (
                    f"{run.team_id} scored {points_for}–{points_against} in the selected interval "
                    f"from Q{first.period} {first.clock} to Q{last.period} {last.clock} "
                    f"(events {first.sequence}–{last.sequence}, inclusive)."
                ),
            }
        )
    return output
