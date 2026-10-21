"""Deterministic play-by-play flow primitives for the analyst get_game_flow tool.

Definitions
-----------
scoring play
    A ``made_shot`` or ``free_throw`` whose recorded cumulative scoreboard changed.
    Points come from ``shot_type`` (3pt = 3, 2pt = 2, ft = 1) when known, otherwise
    from the increase in the recorded score. Rows whose recorded score is ``(0, 0)``
    carry the previous scoreboard forward because the source feed stores missing
    scoreboards as zeroes.
score state
    The carried scoreboard and the NYK margin (NYK minus opponent) after each scoring
    play, in ``(period, sequence)`` order.
largest lead
    The maximum and minimum NYK margin over all score states. A positive maximum is
    the Knicks' largest lead; a negative minimum is the opponent's largest lead
    (reported as a positive number of points).
lead change
    A scoring play after which the leading team differs from the last team that held
    a lead. A tie does not itself change the lead; the next go-ahead score is the
    change. The opening score does not count as a change.
tie
    A scoring play that turns a non-zero margin into exactly zero. The initial 0-0
    state is not a tie.
scoring run
    A maximal sequence of consecutive scoring plays by one team, unbroken by an
    opponent scoring play. Non-scoring events and period boundaries do not break a
    run. The game's opening scoring play establishes the baseline and is not itself
    credited to a run (matching the independent audit SQL). A run reports the points
    the team scored on its plays, its start and end period/clock, and the scoreboard
    before the first play and after the last play.
go-ahead for good
    The first scoring play in the winner's final uninterrupted lead: from that play
    onward the winner never trails and never ties. If the winner led after the first
    scoring play and never relinquished it, that play is the go-ahead.
clutch window
    Scoring plays in period 4 with at most 5:00 remaining, plus every overtime play,
    where either the margin entering the play or the margin after it is at most 5.
deficit erased
    For a win, the largest opponent lead at any score state and the first later state
    where NYK ties or leads. The comeback scoring is NYK's and the opponent's points
    between those two states.
lead lost
    For a loss, the largest NYK lead at any score state; the winner's go-ahead for
    good is reported separately so a lead lost is not confused with the final swing.
period net
    Per period, NYK points minus opponent points over the scoring plays in it, with
    the margin entering the first play and leaving the last play.

The release's precomputed ``scoring_runs`` and ``bad_stretches`` tables are empty
(verified against 46,500 event rows), so runs are rebuilt here from game_events.
Everything is release-pinned by the dispatcher's game selection; game_events is
joined by game id only.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.game_event import GameEvent

if TYPE_CHECKING:
    from app.models.game import Game

SCORING_EVENTS = frozenset({"made_shot", "free_throw"})
CLUTCH_SECONDS = 5 * 60
CLUTCH_MARGIN = 5
SHOT_POINTS = {"3pt": 3, "2pt": 2, "ft": 1}


@dataclass(frozen=True)
class Play:
    """One scoring play with the scoreboard before and after it."""

    event: GameEvent
    team_id: str
    points: int
    home_before: int
    away_before: int
    home_after: int
    away_after: int
    nyk_before: int
    opp_before: int
    nyk_after: int
    opp_after: int

    @property
    def period(self) -> int:
        return self.event.period

    @property
    def clock(self) -> str:
        return self.event.clock

    @property
    def sequence(self) -> int:
        return self.event.sequence

    @property
    def margin_before(self) -> int:
        return self.nyk_before - self.opp_before

    @property
    def margin_after(self) -> int:
        return self.nyk_after - self.opp_after


@dataclass
class Run:
    team_id: str
    points: int
    start: Play
    end: Play


@dataclass
class PeriodNet:
    period: int
    nyk_points: int
    opp_points: int
    margin_before: int
    margin_after: int
    start: Play
    end: Play

    @property
    def net(self) -> int:
        return self.nyk_points - self.opp_points


@dataclass
class Comeback:
    deficit: int
    low: Play
    first_tie_or_lead: Play
    nyk_points: int
    opp_points: int
    run: Run | None


@dataclass
class LostLead:
    lead: int
    peak: Play
    winner_go_ahead: Play


@dataclass
class GameFlow:
    game: Game
    opponent: str
    winner: str | None
    plays: list[Play]
    runs: list[Run]
    final_nyk: int
    final_opp: int
    largest_lead_nyk: int
    largest_lead_nyk_play: Play | None
    largest_lead_opp: int
    largest_lead_opp_play: Play | None
    lead_changes: int
    change_plays: list[Play]
    ties: int
    tie_plays: list[Play]
    best_run_nyk: Run | None
    best_run_opp: Run | None
    go_ahead: Play | None
    go_ahead_run: Run | None
    clutch_plays: list[Play]
    clutch_lead_changes: int
    clutch_change_plays: list[Play]
    comeback: Comeback | None
    lost_lead: LostLead | None
    period_nets: list[PeriodNet]


def event_type(event: GameEvent) -> str:
    return str(getattr(event.event_type, "value", event.event_type))


def clock_seconds(clock: str) -> int:
    try:
        minutes, seconds = clock.split(":")
        return int(minutes) * 60 + int(seconds)
    except (AttributeError, ValueError):
        return 0


def _event_points(event: GameEvent, home_delta: int, away_delta: int) -> int:
    shot_type = getattr(event.shot_type, "value", event.shot_type)
    if event_type(event) == "free_throw":
        return 1 if event.shot_result == "made" else 0
    if event.shot_result == "missed":
        return 0
    if shot_type in SHOT_POINTS:
        return SHOT_POINTS[shot_type]
    return max(home_delta, away_delta, 0)


def _scoring_team(game: Game, event: GameEvent, home_delta: int, away_delta: int) -> str | None:
    if home_delta > 0 and away_delta <= 0:
        return game.home_team_id
    if away_delta > 0 and home_delta <= 0:
        return game.away_team_id
    if home_delta > 0 and away_delta > 0:
        team_id = event.team_id
        if team_id in (game.home_team_id, game.away_team_id):
            return team_id
        return game.home_team_id
    return None


def _plays_for_game(game: Game, events: list[GameEvent], periods: list[int]) -> list[Play]:
    nyk_home = game.home_team_id == "NYK"
    previous = (0, 0)
    plays: list[Play] = []
    for event in events:
        current = (event.home_score, event.away_score)
        if current == (0, 0):
            current = previous
        home_delta = current[0] - previous[0]
        away_delta = current[1] - previous[1]
        if event_type(event) not in SCORING_EVENTS:
            previous = current
            continue
        points = _event_points(event, home_delta, away_delta)
        team_id = _scoring_team(game, event, home_delta, away_delta)
        if points <= 0 or team_id is None:
            previous = current
            continue
        if periods and event.period not in periods:
            previous = current
            continue
        home_before, away_before = previous
        nyk_before = home_before if nyk_home else away_before
        opp_before = away_before if nyk_home else home_before
        nyk_after = current[0] if nyk_home else current[1]
        opp_after = current[1] if nyk_home else current[0]
        plays.append(
            Play(
                event=event,
                team_id=team_id,
                points=points,
                home_before=home_before,
                away_before=away_before,
                home_after=current[0],
                away_after=current[1],
                nyk_before=nyk_before,
                opp_before=opp_before,
                nyk_after=nyk_after,
                opp_after=opp_after,
            )
        )
        previous = current
    return plays


def _runs(plays: list[Play], *, include_opening: bool) -> list[Run]:
    candidates = plays if include_opening else plays[1:]
    runs: list[Run] = []
    for play in candidates:
        if runs and runs[-1].team_id == play.team_id:
            runs[-1].points += play.points
            runs[-1].end = play
        else:
            runs.append(Run(team_id=play.team_id, points=play.points, start=play, end=play))
    return runs


def _lead_counts(plays: list[Play]) -> tuple[int, list[Play], int, list[Play]]:
    changes: list[Play] = []
    ties: list[Play] = []
    last_leader: str | None = None
    previous_margin = 0
    for play in plays:
        margin = play.margin_after
        if margin == 0:
            if previous_margin != 0:
                ties.append(play)
        else:
            leader = "NYK" if margin > 0 else "OPP"
            if last_leader is not None and leader != last_leader:
                changes.append(play)
            last_leader = leader
        previous_margin = margin
    return len(changes), changes, len(ties), ties


def _go_ahead(plays: list[Play], winner: str | None) -> Play | None:
    if not plays or winner not in {"NYK", "OPP"}:
        return None
    wanted = 1 if winner == "NYK" else -1
    index = len(plays) - 1
    while index >= 0 and plays[index].margin_after * wanted > 0:
        index -= 1
    candidate = index + 1
    return plays[candidate] if candidate < len(plays) else None


def _run_containing(runs: list[Run], play: Play | None) -> Run | None:
    if play is None:
        return None
    for run in runs:
        if run.start.sequence <= play.sequence <= run.end.sequence and run.team_id == play.team_id:
            return run
    return None


def _comeback(plays: list[Play], runs: list[Run], winner: str | None) -> Comeback | None:
    if winner != "NYK" or not plays:
        return None
    low_index = min(range(len(plays)), key=lambda index: plays[index].margin_after)
    if plays[low_index].margin_after >= 0:
        return None
    end_index = next(
        (index for index in range(low_index + 1, len(plays)) if plays[index].margin_after >= 0),
        None,
    )
    if end_index is None:
        return None
    low, end = plays[low_index], plays[end_index]
    in_window = [
        run
        for run in runs
        if run.team_id == "NYK"
        and run.start.sequence >= low.sequence
        and run.end.sequence <= end.sequence
    ]
    run = max(in_window, key=lambda item: (item.points, -item.start.sequence), default=None)
    return Comeback(
        deficit=-low.margin_after,
        low=low,
        first_tie_or_lead=end,
        nyk_points=end.nyk_after - low.nyk_after,
        opp_points=end.opp_after - low.opp_after,
        run=run,
    )


def _lost_lead(plays: list[Play], winner: str | None, go_ahead: Play | None) -> LostLead | None:
    if winner != "OPP" or not plays or go_ahead is None:
        return None
    peak = max(plays, key=lambda play: (play.margin_after, -play.sequence))
    if peak.margin_after <= 0:
        return None
    return LostLead(lead=peak.margin_after, peak=peak, winner_go_ahead=go_ahead)


def _period_nets(plays: list[Play]) -> list[PeriodNet]:
    grouped: dict[int, list[Play]] = defaultdict(list)
    for play in plays:
        grouped[play.period].append(play)
    output: list[PeriodNet] = []
    for period in sorted(grouped):
        rows = grouped[period]
        nyk_points = sum(play.points for play in rows if play.team_id == "NYK")
        opp_points = sum(play.points for play in rows if play.team_id != "NYK")
        output.append(
            PeriodNet(
                period=period,
                nyk_points=nyk_points,
                opp_points=opp_points,
                margin_before=rows[0].margin_before,
                margin_after=rows[-1].margin_after,
                start=rows[0],
                end=rows[-1],
            )
        )
    return output


def _clutch(plays: list[Play]) -> tuple[list[Play], int, list[Play]]:
    clutch: list[Play] = []
    for play in plays:
        in_window = (play.period == 4 and clock_seconds(play.clock) <= CLUTCH_SECONDS) or (
            play.period > 4
        )
        if not in_window:
            continue
        if abs(play.margin_before) <= CLUTCH_MARGIN or abs(play.margin_after) <= CLUTCH_MARGIN:
            clutch.append(play)
    changes, change_plays, _, _ = _lead_counts(clutch)
    return clutch, changes, change_plays


def build_flow(game: Game, events: list[GameEvent], periods: list[int]) -> GameFlow | None:
    """Build one game's flow. Period filters restrict every state-based definition."""
    plays = _plays_for_game(game, events, periods)
    if not plays:
        return None
    nyk_home = game.home_team_id == "NYK"
    opponent = game.away_team_id if nyk_home else game.home_team_id
    final_nyk = game.home_score if nyk_home else game.away_score
    final_opp = game.away_score if nyk_home else game.home_score
    winner = "NYK" if final_nyk > final_opp else "OPP" if final_opp > final_nyk else None
    runs = _runs(plays, include_opening=bool(periods))
    largest_nyk = max(plays, key=lambda play: (play.margin_after, -play.sequence))
    largest_opp = min(plays, key=lambda play: (play.margin_after, play.sequence))
    lead_changes, change_plays, ties, tie_plays = _lead_counts(plays)
    go_ahead = _go_ahead(plays, winner)
    best_run_nyk = max(
        (run for run in runs if run.team_id == "NYK"),
        key=lambda run: (run.points, -run.start.sequence),
        default=None,
    )
    best_run_opp = max(
        (run for run in runs if run.team_id != "NYK"),
        key=lambda run: (run.points, -run.start.sequence),
        default=None,
    )
    clutch, clutch_changes, clutch_change_plays = _clutch(plays)
    return GameFlow(
        game=game,
        opponent=opponent,
        winner=winner,
        plays=plays,
        runs=runs,
        final_nyk=final_nyk,
        final_opp=final_opp,
        largest_lead_nyk=max(0, largest_nyk.margin_after),
        largest_lead_nyk_play=largest_nyk if largest_nyk.margin_after > 0 else None,
        largest_lead_opp=max(0, -largest_opp.margin_after),
        largest_lead_opp_play=largest_opp if largest_opp.margin_after < 0 else None,
        lead_changes=lead_changes,
        change_plays=change_plays,
        ties=ties,
        tie_plays=tie_plays,
        best_run_nyk=best_run_nyk,
        best_run_opp=best_run_opp,
        go_ahead=go_ahead,
        go_ahead_run=_run_containing(runs, go_ahead),
        clutch_plays=clutch,
        clutch_lead_changes=clutch_changes,
        clutch_change_plays=clutch_change_plays,
        comeback=_comeback(plays, runs, winner),
        lost_lead=_lost_lead(plays, winner, go_ahead),
        period_nets=_period_nets(plays),
    )


def phase(game: Game) -> str:
    return {
        "regular": "Regular season",
        "play_in": "Play-in",
        "playoffs": "Playoffs",
    }.get(game.season_type, game.season_type)


def prefix(game: Game, opponent: str) -> str:
    return f"{phase(game)} {game.game_date} vs {opponent}"


def time_text(play: Play) -> str:
    return f"Q{play.period} {play.clock}"


def score_text(play: Play) -> str:
    return f"{play.nyk_after}-{play.opp_after}"


def score_before_text(play: Play) -> str:
    return f"{play.nyk_before}-{play.opp_before}"


def run_text(run: Run) -> str:
    return (
        f"{time_text(run.start)} to {time_text(run.end)}, score "
        f"{score_before_text(run.start)} to {score_text(run.end)}"
    )
