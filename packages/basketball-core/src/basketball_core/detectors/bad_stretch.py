"""Bad stretch detector.

Bad stretches are Knicks-centric views of opponent impactful runs.
The impactful-run detector decides whether a scoreboard swing mattered;
this module adds Knicks causes such as turnovers and missed shots.
"""

from __future__ import annotations

from dataclasses import dataclass

from basketball_core.detectors.impactful_run import (
    ImpactfulRunConfig,
    detect_impactful_runs,
)
from basketball_core.models.event import EventType, GameEvent
from basketball_core.models.run import BadStretch


@dataclass(frozen=True)
class BadStretchConfig:
    window_seconds: int = 4 * 60
    min_run_points: int = 8
    min_swing_points: int = 8
    min_dry_seconds: int = 180
    min_turnovers: int = 2
    knicks_team_id: str = "NYK"
    home_team_id: str | None = None
    away_team_id: str | None = None
    season_type: str = "regular"


def _events_in_range(
    events: list[GameEvent], start_sequence: int, end_sequence: int
) -> list[GameEvent]:
    context_start = max(1, start_sequence - 3)
    return [event for event in events if context_start <= event.sequence <= end_sequence]


def _cause_counts(events: list[GameEvent], knicks_team_id: str) -> dict[str, int]:
    return {
        "knicks_turnovers": sum(
            1
            for event in events
            if event.team_id == knicks_team_id and event.event_type == EventType.TURNOVER
        ),
        "knicks_missed_shots": sum(
            1
            for event in events
            if event.team_id == knicks_team_id and event.event_type == EventType.MISSED_SHOT
        ),
        "opponent_fast_breaks": 0,
    }


def _likely_causes(
    counts: dict[str, int], reasons: list[str], config: BadStretchConfig
) -> list[str]:
    causes: list[str] = []
    if "huge_swing" in reasons or "clutch" in reasons or "entered_pressure_zone" in reasons:
        causes.append("opponent scoring swing")
    else:
        causes.append("opponent scoring run")
    if counts["knicks_turnovers"] >= config.min_turnovers:
        causes.append("multiple turnovers")
    if counts["knicks_missed_shots"] >= 4:
        causes.append("poor shot quality")
    if "garbage_time" in reasons:
        causes.append("low leverage")
    return causes


def detect_bad_stretches(
    events: list[GameEvent],
    config: BadStretchConfig | None = None,
) -> list[BadStretch]:
    cfg = config or BadStretchConfig()
    if not events:
        return []

    sorted_events = sorted(events, key=lambda event: event.sequence)
    runs = detect_impactful_runs(
        sorted_events,
        ImpactfulRunConfig(
            min_net_swing=cfg.min_swing_points,
            max_window_seconds=cfg.window_seconds,
            knicks_team_id=cfg.knicks_team_id,
            home_team_id=cfg.home_team_id,
            away_team_id=cfg.away_team_id,
            season_type=cfg.season_type,
        ),
    )

    stretches: list[BadStretch] = []
    for run in runs:
        if run.team_id == cfg.knicks_team_id:
            continue
        run_events = _events_in_range(sorted_events, run.start_sequence, run.end_sequence)
        counts = _cause_counts(run_events, cfg.knicks_team_id)
        causes = _likely_causes(counts, run.reasons, cfg)
        stretches.append(
            BadStretch(
                game_id=run.game_id,
                period=run.period,
                start_clock=run.start_clock,
                end_clock=run.end_clock,
                score_delta=-run.score_delta,
                summary=(
                    f"Knicks were outscored {run.points_for}-{run.points_against} "
                    f"from Q{run.period} {run.start_clock} to "
                    f"Q{run.end_period} {run.end_clock}. {run.summary}"
                ),
                likely_causes=causes,
                knicks_turnovers=counts["knicks_turnovers"],
                knicks_missed_shots=counts["knicks_missed_shots"],
                opponent_fast_breaks=counts["opponent_fast_breaks"],
            )
        )

    stretches.sort(key=lambda stretch: (stretch.score_delta, stretch.period, stretch.start_clock))
    return stretches[:5]
