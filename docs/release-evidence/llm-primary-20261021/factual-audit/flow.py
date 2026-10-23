"""Play-by-play facts recomputed from raw game_events rows."""

from __future__ import annotations

from dataclasses import dataclass

from oracle_db import Game, Play, clock_seconds


@dataclass
class Run:
    team: str
    points: int
    start: Play
    end: Play


def plays_for(oracle, game: Game, periods: list[int] | None = None) -> list[Play]:
    plays = oracle.plays[game.id]
    if periods:
        return [p for p in plays if p.period in periods]
    return plays


def runs(plays: list[Play], include_opening: bool) -> list[Run]:
    candidates = plays if include_opening else plays[1:]
    out: list[Run] = []
    for play in candidates:
        if out and out[-1].team == play.team:
            out[-1].points += play.points
            out[-1].end = play
        else:
            out.append(Run(play.team, play.points, play, play))
    return out


def go_ahead(plays: list[Play], game: Game) -> Play | None:
    if not plays:
        return None
    winner = "NYK" if game.win else "OPP"
    wanted = 1 if winner == "NYK" else -1
    index = len(plays) - 1
    while index >= 0 and plays[index].margin_after * wanted > 0:
        index -= 1
    candidate = index + 1
    return plays[candidate] if candidate < len(plays) else None


def comeback(plays: list[Play], include_opening: bool) -> dict | None:
    if not plays or not any(p.margin_after < 0 for p in plays):
        return None
    low_index = min(range(len(plays)), key=lambda i: (plays[i].margin_after, i))
    if plays[low_index].margin_after >= 0:
        return None
    end_index = next(
        (i for i in range(low_index + 1, len(plays)) if plays[i].margin_after >= 0),
        None,
    )
    if end_index is None:
        return None
    low, end = plays[low_index], plays[end_index]
    in_window = [
        run for run in runs(plays, include_opening)
        if run.team == "NYK" and run.start.sequence >= low.sequence and run.end.sequence <= end.sequence
    ]
    run = max(in_window, key=lambda r: (r.points, -r.start.sequence), default=None)
    return {
        "deficit": -low.margin_after,
        "low": low,
        "end": end,
        "nyk_points": end.nyk_after - low.nyk_after,
        "opp_points": end.opp_after - low.opp_after,
        "run": run,
    }


def lost_lead(plays: list[Play], game: Game) -> dict | None:
    ahead = go_ahead(plays, game)
    if game.win or ahead is None or not plays:
        return None
    peak = max(plays, key=lambda p: (p.margin_after, -p.sequence))
    if peak.margin_after <= 0:
        return None
    return {"lead": peak.margin_after, "peak": peak, "go_ahead": ahead}


def biggest_run(plays: list[Play], team: str, include_opening: bool) -> Run | None:
    return max(
        (run for run in runs(plays, include_opening) if run.team == team),
        key=lambda r: (r.points, -r.start.sequence),
        default=None,
    )


def play_at(plays: list[Play], period: int | None, clock: str | None) -> Play | None:
    found = plays_at(plays, period, clock)
    return found[0] if found else None


def plays_at(plays: list[Play], period: int | None, clock: str | None) -> list[Play]:
    if clock is None:
        return []
    return [
        play for play in plays
        if (period is None or play.period == period)
        and normalize_clock(play.clock) == normalize_clock(clock)
    ]


def normalize_clock(clock: str) -> str:
    try:
        minutes, seconds = clock.split(":")
        return f"{int(minutes)}:{int(seconds):02d}"
    except ValueError:
        return clock


def first_play_with_score(plays: list[Play], nyk: int, opp: int) -> Play | None:
    for play in plays:
        if (play.after if hasattr(play, "after") else (play.nyk_after, play.opp_after)) == (nyk, opp):
            return play
    return None


def first_tie(plays: list[Play], nyk: int | None = None, opp: int | None = None) -> Play | None:
    for play in plays:
        if play.margin_after != 0:
            continue
        if nyk is not None and (play.nyk_after, play.opp_after) != (nyk, opp):
            continue
        return play
    return None


def snapshot_matches(play: Play, first: int, second: int) -> bool:
    return {play.nyk_after, play.opp_after} == {first, second} or (
        play.nyk_after == first and play.opp_after == second
    ) or (play.nyk_after == second and play.opp_after == first)
