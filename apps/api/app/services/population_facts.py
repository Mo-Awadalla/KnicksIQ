"""Pure reductions over release-scoped team scores and canonical player rows."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.models.box_score import PlayerGameStat
from app.models.game import Game
from app.models.player import Player
from basketball_core.analytics import (
    STAT_REGISTRY,
    StatThreshold,
    aggregate_rows,
    parse_stat_threshold,
)

_COUNT_REQUEST = re.compile(r"\b(?:how many|count|number of)\b", re.I)
_GAME_FREQUENCY = re.compile(r"\b(?:games?|times?|occasions?)\b", re.I)
_OPPONENT_SCORE = re.compile(r"\b(?:opponents?|allow(?:ed)?|hold)\b", re.I)
_EXTREME = re.compile(r"\b(?:most|highest|maximum|max)\b", re.I)
_SINGLE_GAME = re.compile(r"\b(?:single|one|a)[\s-]+game\b", re.I)


@dataclass(frozen=True)
class ScoreThresholdCount:
    threshold: StatThreshold
    value: int
    sample_size: int
    matching_game_ids: tuple[int, ...]
    opponent_score: bool

    @property
    def predicate(self) -> dict[str, str | float]:
        return {
            "subject_id": "opponent" if self.opponent_score else "team:NYK",
            "metric_id": "points",
            "operator": self.threshold.symbol,
            "cutoff": self.threshold.value,
        }


@dataclass(frozen=True)
class PlayerGameLeader:
    stat: PlayerGameStat
    player: Player
    game: Game
    value: int | float


@dataclass(frozen=True)
class PlayerLeaderFact:
    metric: str
    label: str
    value: int | float
    leaders: tuple[str, ...]
    tied_rows: tuple[PlayerGameLeader, ...]
    evidence_rows: tuple[tuple[PlayerGameStat, Player], ...]
    sample_size: int
    single_game_high: bool


def score_threshold_count(question: str, games: Sequence[Game]) -> ScoreThresholdCount | None:
    """Count archived game scores using the shared stat-threshold semantics."""
    if not _COUNT_REQUEST.search(question) or not _GAME_FREQUENCY.search(question):
        return None
    opponent_score = bool(_OPPONENT_SCORE.search(question))
    threshold = parse_stat_threshold(question)
    if threshold is None and opponent_score:
        # The shared parser infers points from a scoring verb; opponent defense
        # phrases imply the same score metric without naming it explicitly.
        threshold = parse_stat_threshold(f"score {question}")
    if threshold is None or threshold.stat != "points":
        return None
    matching_game_ids = tuple(
        game.id
        for game in games
        if threshold.meets(
            {
                "points": (game.home_score if game.home_team_id == "NYK" else game.away_score)
                if not opponent_score
                else (game.away_score if game.home_team_id == "NYK" else game.home_score)
            }
        )
    )
    return ScoreThresholdCount(
        threshold=threshold,
        value=len(matching_game_ids),
        sample_size=len(games),
        matching_game_ids=matching_game_ids,
        opponent_score=opponent_score,
    )


def is_single_game_high_request(question: str) -> bool:
    return bool(_EXTREME.search(question) and _SINGLE_GAME.search(question))


def is_player_leader_request(question: str) -> bool:
    lowered = question.lower()
    return bool(
        re.search(r"\b(?:who\s+led|leaders?|which player)\b", lowered)
        or (re.search(r"\bwho\b", lowered) and _EXTREME.search(lowered))
        or (_EXTREME.search(lowered) and re.search(r"\b(?:knick|player)\b", lowered))
    )


def player_leader_fact(
    rows: Sequence[tuple[PlayerGameStat, Player]],
    games: Sequence[Game],
    metric: str,
    question: str,
    *,
    supported_metrics: Sequence[str],
) -> PlayerLeaderFact | None:
    """Reduce canonical Knicks box-score rows to season leaders or per-game highs."""
    if metric not in supported_metrics:
        return None
    definition = STAT_REGISTRY.get(metric)
    if definition is None:
        definition = next(
            (item for item in STAT_REGISTRY.values() if item.columns == (metric,)), None
        )
    if (
        definition is None
        or definition.kind not in {"count", "minutes"}
        or len(definition.columns) != 1
    ):
        return None

    game_map = {game.id: game for game in games}
    scoped_rows = [
        (stat, player, game_map[stat.game_id]) for stat, player in rows if stat.game_id in game_map
    ]
    scoped_rows.sort(key=lambda item: (item[2].game_date, item[1].full_name, item[2].id))

    if not scoped_rows or {stat.game_id for stat, _, _ in scoped_rows} != set(game_map):
        return None

    single_game_high = is_single_game_high_request(question)
    column = definition.columns[0]
    if single_game_high:
        candidates = []
        for stat, player, game in scoped_rows:
            if float(stat.minutes or 0) <= 0:
                continue
            value = aggregate_rows([stat], [definition.key])[definition.key]
            if value is not None:
                candidates.append(PlayerGameLeader(stat, player, game, value))
        if not candidates:
            return None
        maximum = max(entry.value for entry in candidates)
        tied_rows = tuple(
            sorted(
                (entry for entry in candidates if entry.value == maximum),
                key=lambda entry: (entry.game.game_date, entry.player.full_name, entry.game.id),
            )
        )
        return PlayerLeaderFact(
            metric=metric,
            label=definition.label.lower(),
            value=maximum,
            leaders=tuple(sorted({entry.player.full_name for entry in tied_rows})),
            tied_rows=tied_rows,
            evidence_rows=tuple((entry.stat, entry.player) for entry in candidates),
            sample_size=len(candidates),
            single_game_high=True,
        )

    totals: dict[int, float] = {}
    names: dict[int, str] = {}
    for stat, player, _ in scoped_rows:
        totals[player.id] = totals.get(player.id, 0.0) + float(getattr(stat, column) or 0)
        names[player.id] = player.full_name
    maximum = max(totals.values())
    leaders = tuple(
        sorted(names[player_id] for player_id, value in totals.items() if value == maximum)
    )
    return PlayerLeaderFact(
        metric=metric,
        label=definition.label.lower(),
        value=maximum,
        leaders=leaders,
        tied_rows=(),
        evidence_rows=tuple((stat, player) for stat, player, _ in scoped_rows),
        sample_size=len(games),
        single_game_high=False,
    )
