"""Impactful run detector.

An impactful run is a net scoreboard swing, not necessarily unanswered
points. This catches stretches like 16-2 as first-class runs while
still showing a plain 8-0.
"""

from __future__ import annotations

from dataclasses import dataclass

from basketball_core.models.event import EventType, GameEvent
from basketball_core.models.run import ImpactfulRun

_PERIOD_SECONDS = 12 * 60


@dataclass(frozen=True)
class ImpactfulRunConfig:
    min_net_swing: int = 8
    clutch_min_net_swing: int = 5
    highlight_net_swing: int = 14
    max_window_seconds: int = 4 * 60
    clutch_remaining_seconds: int = 6 * 60
    pressure_margin: int = 6
    knicks_team_id: str = "NYK"
    home_team_id: str | None = None
    away_team_id: str | None = None
    season_type: str = "regular"


def _clock_to_seconds(clock: str) -> int:
    try:
        minutes, seconds = clock.split(":")
        return int(minutes) * 60 + int(seconds)
    except (AttributeError, ValueError):
        return 0


def _seconds_elapsed(period: int, clock: str) -> int:
    return (period - 1) * _PERIOD_SECONDS + (_PERIOD_SECONDS - _clock_to_seconds(clock))


def _remaining_seconds(event: GameEvent) -> int:
    return _clock_to_seconds(event.clock)


def _is_scoring_event(event: GameEvent) -> bool:
    return event.team_id is not None and event.points_scored > 0


def _score_before(event: GameEvent, config: ImpactfulRunConfig) -> tuple[int, int]:
    home_score = event.home_score
    away_score = event.away_score
    if event.team_id == config.home_team_id:
        home_score -= event.points_scored
    elif event.team_id == config.away_team_id:
        away_score -= event.points_scored
    return home_score, away_score


def _margin_for_team(home_score: int, away_score: int, team_id: str, config: ImpactfulRunConfig) -> int | None:
    if config.home_team_id is None or config.away_team_id is None:
        return None
    if team_id == config.home_team_id:
        return home_score - away_score
    if team_id == config.away_team_id:
        return away_score - home_score
    return None


def _crossed_pressure_zone(
    start_margin: int | None,
    end_margin: int | None,
    pressure_margin: int,
) -> bool:
    if start_margin is None or end_margin is None:
        return False
    return abs(start_margin) > pressure_margin and abs(end_margin) <= pressure_margin


def _lead_changed(start_margin: int | None, end_margin: int | None) -> bool:
    if start_margin is None or end_margin is None:
        return False
    return start_margin < 0 < end_margin or start_margin > 0 > end_margin


def _tie_created_or_broken(start_margin: int | None, end_margin: int | None) -> bool:
    if start_margin is None or end_margin is None:
        return False
    return start_margin != 0 and end_margin == 0


def _is_late_game(event: GameEvent, config: ImpactfulRunConfig) -> bool:
    return event.period >= 4 and _remaining_seconds(event) <= config.clutch_remaining_seconds


def _classify_leverage(
    start_event: GameEvent,
    end_event: GameEvent,
    start_margin: int | None,
    end_margin: int | None,
    config: ImpactfulRunConfig,
) -> str:
    late = _is_late_game(start_event, config) or _is_late_game(end_event, config)
    if not late:
        return "normal"
    if (
        start_margin is not None
        and end_margin is not None
        and abs(start_margin) > config.pressure_margin
        and abs(end_margin) > config.pressure_margin
        and not _lead_changed(start_margin, end_margin)
        and not _tie_created_or_broken(start_margin, end_margin)
    ):
        return "garbage_time"
    if (
        start_margin is not None
        and end_margin is not None
        and (abs(start_margin) <= config.pressure_margin or abs(end_margin) <= config.pressure_margin)
    ):
        return "clutch"
    return "late"


def _impact_score(
    *,
    net_swing: int,
    leverage: str,
    start_margin: int | None,
    end_margin: int | None,
    config: ImpactfulRunConfig,
) -> tuple[int, list[str], bool]:
    score = net_swing
    reasons: list[str] = []
    if net_swing >= config.highlight_net_swing:
        score += 6
        reasons.append("huge_swing")
    if _lead_changed(start_margin, end_margin):
        score += 8
        reasons.append("lead_change")
    if _tie_created_or_broken(start_margin, end_margin):
        score += 6
        reasons.append("tie_created_or_broken")
    if _crossed_pressure_zone(start_margin, end_margin, config.pressure_margin):
        score += 5
        reasons.append("entered_pressure_zone")
    if leverage == "clutch":
        score += 4
        reasons.append("clutch")
    if config.season_type == "playoffs":
        score += 3
        reasons.append("playoffs")
    if leverage == "garbage_time":
        score -= 8
        reasons.append("garbage_time")
    is_highlight = (
        "huge_swing" in reasons
        or "lead_change" in reasons
        or "tie_created_or_broken" in reasons
        or "entered_pressure_zone" in reasons
        or "clutch" in reasons
        or ("playoffs" in reasons and net_swing >= config.min_net_swing)
    ) and leverage != "garbage_time"
    return score, reasons, is_highlight


def detect_impactful_runs(
    events: list[GameEvent],
    config: ImpactfulRunConfig | None = None,
) -> list[ImpactfulRun]:
    cfg = config or ImpactfulRunConfig()
    if not events:
        return []

    sorted_events = sorted(events, key=lambda event: event.sequence)
    scoring_indices = [idx for idx, event in enumerate(sorted_events) if _is_scoring_event(event)]
    if not scoring_indices:
        return []

    candidates: list[tuple[ImpactfulRun, tuple[int, int]]] = []
    game_id = sorted_events[0].game_id
    for scoring_start_pos, start_idx in enumerate(scoring_indices):
        start_event = sorted_events[start_idx]
        start_elapsed = _seconds_elapsed(start_event.period, start_event.clock)
        team_points: dict[str, int] = {}
        scoring_events_for_team: dict[str, int] = {}

        for end_idx in scoring_indices[scoring_start_pos:]:
            end_event = sorted_events[end_idx]
            if _seconds_elapsed(end_event.period, end_event.clock) - start_elapsed > cfg.max_window_seconds:
                break
            if end_event.team_id is None:
                continue
            team_points[end_event.team_id] = team_points.get(end_event.team_id, 0) + end_event.points_scored
            scoring_events_for_team[end_event.team_id] = scoring_events_for_team.get(end_event.team_id, 0) + 1

            if len(team_points) == 0:
                continue
            run_team_id = max(team_points, key=lambda team_id: team_points[team_id])
            points_for = team_points[run_team_id]
            points_against = sum(points for team_id, points in team_points.items() if team_id != run_team_id)
            net_swing = points_for - points_against
            if scoring_events_for_team.get(run_team_id, 0) < 2:
                continue

            start_home, start_away = _score_before(start_event, cfg)
            start_margin = _margin_for_team(start_home, start_away, run_team_id, cfg)
            end_margin = _margin_for_team(end_event.home_score, end_event.away_score, run_team_id, cfg)
            leverage = _classify_leverage(start_event, end_event, start_margin, end_margin, cfg)
            min_swing = cfg.clutch_min_net_swing if leverage == "clutch" else cfg.min_net_swing
            if net_swing < min_swing:
                continue

            impact_score, reasons, is_highlight = _impact_score(
                net_swing=net_swing,
                leverage=leverage,
                start_margin=start_margin,
                end_margin=end_margin,
                config=cfg,
            )
            summary = (
                f"{run_team_id} {points_for}-{points_against} impactful run "
                f"from Q{start_event.period} {start_event.clock} to "
                f"Q{end_event.period} {end_event.clock}"
            )
            if start_margin is not None and end_margin is not None:
                summary += f" (margin {start_margin:+d} to {end_margin:+d})"

            candidates.append(
                (
                    ImpactfulRun(
                        game_id=game_id,
                        team_id=run_team_id,
                        period=start_event.period,
                        end_period=end_event.period,
                        start_sequence=start_event.sequence,
                        end_sequence=end_event.sequence,
                        start_clock=start_event.clock,
                        end_clock=end_event.clock,
                        points_for=points_for,
                        points_against=points_against,
                        score_delta=net_swing,
                        event_count=end_idx - start_idx + 1,
                        start_margin=start_margin,
                        end_margin=end_margin,
                        impact_score=impact_score,
                        is_highlight=is_highlight,
                        leverage=leverage,
                        reasons=reasons,
                        summary=summary,
                    ),
                    (start_idx, end_idx),
                )
            )

    selected = _collapse_overlapping_candidates(candidates)
    selected.sort(key=lambda run: (run.period, run.start_sequence))
    return selected


def _collapse_overlapping_candidates(
    candidates: list[tuple[ImpactfulRun, tuple[int, int]]],
) -> list[ImpactfulRun]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            -item[0].score_delta,
            -item[0].impact_score,
            item[1][1] - item[1][0],
            item[1][0],
        ),
    )
    selected: list[tuple[ImpactfulRun, tuple[int, int]]] = []
    for run, run_range in ranked:
        if any(_ranges_overlap(run_range, selected_range) for _, selected_range in selected):
            continue
        selected.append((run, run_range))
    return [run for run, _ in selected]


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return max(left[0], right[0]) <= min(left[1], right[1])
