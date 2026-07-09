"""Scoring run detector.

A "scoring run" is a stretch of play where one team outscored the other
by at least `min_run_points`. We compute runs by walking the event
stream and looking for spans of consecutive scoring events by a single
team, unbroken by an opponent score or period change.

A run is closed when:
- the opponent scores (run ends), OR
- the period ends.

The opponent's scoring event is the *terminator* of the run — it is
NOT counted in the run's points_against. A run reports the points
the running team scored, the events they used to do it, and the
clock window they spanned. `points_against` is the points the
opponent scored in the SAME window before the run started (useful
context, defaults to 0 for runs that begin at a period start).

This is a pure function — no I/O, no DB — so it can be unit tested
with a sequence of mock events.
"""

from __future__ import annotations

from dataclasses import dataclass

from basketball_core.models.event import GameEvent
from basketball_core.models.run import ScoringRun


@dataclass(frozen=True)
class ScoringRunConfig:
    min_run_points: int = 6
    min_events: int = 1
    knicks_team_id: str = "NYK"


def detect_scoring_runs(
    events: list[GameEvent],
    config: ScoringRunConfig | None = None,
) -> list[ScoringRun]:
    """Detect all scoring runs in a chronological list of events.

    A run is a maximal span of events by a single team in which the
    team scores at least `min_run_points` and is not interrupted by
    an opponent score or period change.
    """
    cfg = config or ScoringRunConfig()
    if not events:
        return []

    runs: list[ScoringRun] = []
    sorted_events = sorted(events, key=lambda e: e.sequence)
    game_id = sorted_events[0].game_id

    n = len(sorted_events)
    i = 0
    while i < n:
        ev = sorted_events[i]

        # Period boundaries don't start a run themselves; skip them.
        if ev.event_type.value in ("period_start", "period_end"):
            i += 1
            continue

        # A run begins at a scoring event by some team.
        if ev.points_scored == 0 or ev.team_id is None:
            i += 1
            continue

        run_team_id = ev.team_id
        start = i
        start_clock = ev.clock
        period = ev.period
        points_for = 0
        points_against = 0
        # Track the index of the last event that *belongs to* the run
        # (i.e. the last event credited to the running team before
        # a terminator or period change). The terminator event itself
        # is excluded from the run's clock window.
        last_run_event_idx = i
        j = i
        # Walk forward counting only the running team's points.
        # Stop when the opponent scores, the period changes, or we
        # reach the end of the stream.
        while j < n:
            cur = sorted_events[j]
            if cur.period != period:
                break
            if cur.event_type.value == "period_end":
                break
            if cur.team_id == run_team_id:
                points_for += cur.points_scored
                last_run_event_idx = j
                j += 1
            elif cur.team_id is not None and cur.points_scored > 0:
                # Opponent scoring — terminator, not part of the run.
                break
            else:
                # Defensive/offensive rebounds, fouls, timeouts, etc.
                # They don't break the run; they just don't add points.
                j += 1

        end_event = sorted_events[last_run_event_idx]
        event_count = last_run_event_idx - start + 1
        score_delta = points_for - points_against

        if score_delta >= cfg.min_run_points and event_count >= cfg.min_events:
            runs.append(
                ScoringRun(
                    game_id=game_id,
                    team_id=run_team_id,
                    period=period,
                    start_sequence=sorted_events[start].sequence,
                    end_sequence=end_event.sequence,
                    start_clock=start_clock,
                    end_clock=end_event.clock,
                    points_for=points_for,
                    points_against=points_against,
                    score_delta=score_delta,
                    event_count=event_count,
                    summary=(
                        f"{run_team_id} {points_for}-{points_against} run "
                        f"in Q{period} from {start_clock} to {end_event.clock}"
                    ),
                )
            )

        # Advance: skip past the terminator event too (if any). j
        # points to the terminator, so +1 to scan from the next event.
        i = j + 1

    return [r for r in runs if r.score_delta > 0]


def detect_knicks_runs(
    events: list[GameEvent],
    config: ScoringRunConfig | None = None,
) -> list[ScoringRun]:
    """Return only the scoring runs credited to the Knicks."""
    cfg = config or ScoringRunConfig()
    return [r for r in detect_scoring_runs(events, cfg) if r.team_id == cfg.knicks_team_id]


def detect_opponent_runs(
    events: list[GameEvent],
    config: ScoringRunConfig | None = None,
) -> list[ScoringRun]:
    """Return only the scoring runs credited to the opponent."""
    cfg = config or ScoringRunConfig()
    return [r for r in detect_scoring_runs(events, cfg) if r.team_id != cfg.knicks_team_id]
