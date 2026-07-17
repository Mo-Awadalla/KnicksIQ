"""Read-only table RAG over available game rows."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.services.releases import restrict_to_active_release
from app.services.table_rag_templates import polars_summary, template_intent
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

TABLE_RAG_TIMEOUT_SECONDS = 1.5
_BLOCKED_NAMES = {
    "__import__",
    "eval",
    "exec",
    "open",
    "os",
    "pathlib",
    "shutil",
    "subprocess",
    "sys",
}
_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.keyword,
)
_ALLOWED_TABLE_FUNCTIONS = {
    "average_points_against",
    "average_points_for",
    "count_games",
    "largest_win_margin",
    "losses",
    "sum_points_against",
    "sum_points_for",
    "wins",
}
_DATA_STATUS_RANK = {"summary_only": 0, "events_ready": 1, "analysis_ready": 2}


@dataclass(frozen=True)
class TableRagResult:
    answer: str
    evidence: list[dict[str, Any]]
    warnings: list[str]


class TableRagSandboxError(ValueError):
    """Raised when a table expression is not safe to execute."""


class ReadOnlyTable:
    """Immutable game rows exposed to TableRAG math helpers."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = tuple(MappingProxyType(dict(row)) for row in rows)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


def _knicks_scores(game: Game) -> tuple[int, int, str]:
    opponent = game.home_team_id if game.away_team_id == "NYK" else game.away_team_id
    knicks_score = game.away_score if game.away_team_id == "NYK" else game.home_score
    opponent_score = game.home_score if game.away_team_id == "NYK" else game.away_score
    return knicks_score, opponent_score, opponent


def _game_evidence(game: Game) -> dict[str, Any]:
    knicks_score, opponent_score, opponent = _knicks_scores(game)
    return {
        "type": "game",
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": opponent,
        "score": {"NYK": knicks_score, opponent: opponent_score},
        "season_type": game.season_type,
        "data_status": game.data_status,
        "source_name": game.source_name,
        "source_url": game.source_url,
    }


def _table_row(game: Game) -> dict[str, Any]:
    knicks_score, opponent_score, opponent = _knicks_scores(game)
    return {
        "game_id": game.id,
        "date": str(game.game_date),
        "opponent": opponent,
        "knicks_score": knicks_score,
        "opponent_score": opponent_score,
        "knicks_win": knicks_score > opponent_score,
        "season_type": game.season_type,
        "data_status": game.data_status,
    }


def validate_table_expression(expression: str) -> ast.Expression:
    """Validate a tiny aggregate-expression AST before execution."""
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise TableRagSandboxError("Invalid table expression syntax.") from exc

    for node in ast.walk(parsed):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise TableRagSandboxError(f"Unsupported table expression node: {type(node).__name__}.")
        if isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES:
                raise TableRagSandboxError(f"Blocked table expression name: {node.id}.")
            if node.id not in _ALLOWED_TABLE_FUNCTIONS:
                raise TableRagSandboxError(f"Unknown table expression name: {node.id}.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise TableRagSandboxError("Only direct aggregate helper calls are allowed.")
            if node.func.id not in _ALLOWED_TABLE_FUNCTIONS:
                raise TableRagSandboxError(f"Unsupported aggregate helper: {node.func.id}.")
            if node.args or node.keywords:
                raise TableRagSandboxError("Aggregate helpers do not accept arguments.")
    return parsed


def evaluate_table_expression(expression: str, games: list[Game]) -> int | float:
    """Evaluate allowlisted aggregate math over immutable cached rows."""
    parsed = validate_table_expression(expression)
    table = ReadOnlyTable([_table_row(game) for game in games])

    def count_games() -> int:
        return len(table)

    def wins() -> int:
        return sum(1 for row in table if row["knicks_win"])

    def losses() -> int:
        return len(table) - wins()

    def largest_win_margin() -> int:
        margins = [
            int(row["knicks_score"]) - int(row["opponent_score"])
            for row in table
            if row["knicks_win"]
        ]
        return max(margins) if margins else 0

    def sum_points_for() -> int:
        return sum(int(row["knicks_score"]) for row in table)

    def sum_points_against() -> int:
        return sum(int(row["opponent_score"]) for row in table)

    def average_points_for() -> float:
        return sum_points_for() / len(table) if table else 0.0

    def average_points_against() -> float:
        return sum_points_against() / len(table) if table else 0.0

    safe_locals = {
        "average_points_against": average_points_against,
        "average_points_for": average_points_for,
        "count_games": count_games,
        "largest_win_margin": largest_win_margin,
        "losses": losses,
        "sum_points_against": sum_points_against,
        "sum_points_for": sum_points_for,
        "wins": wins,
    }
    return eval(  # noqa: S307
        compile(parsed, "<table_rag_expression>", "eval"),
        {"__builtins__": {}},
        safe_locals,
    )


async def _season_games(db: AsyncSession, season: str) -> list[Game]:
    stmt = restrict_to_active_release(
        select(Game)
        .where(Game.season == season)
        .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
        .order_by(Game.game_date)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return _dedupe_games(list(rows))


def _dedupe_games(games: list[Any]) -> list[Any]:
    """Collapse duplicate cached rows for the same final game.

    Some local/dev caches can contain a seed summary row and a later source row
    for the same date, teams, and final score. TableRAG should count that once
    and prefer the row with richer event data.
    """
    selected: dict[tuple, Game] = {}
    for game in games:
        key = (
            game.game_date,
            game.home_team_id,
            game.away_team_id,
            game.home_score,
            game.away_score,
        )
        existing = selected.get(key)
        if existing is None:
            selected[key] = game
            continue
        current_rank = _DATA_STATUS_RANK.get(game.data_status, 0)
        existing_rank = _DATA_STATUS_RANK.get(existing.data_status, 0)
        if (current_rank, game.id) > (existing_rank, existing.id):
            selected[key] = game
    return sorted(selected.values(), key=lambda game: (game.game_date, game.id))


def _answer_from_games(question: str, season: str, games: list[Game]) -> TableRagResult:
    q = question.lower()
    warnings: list[str] = []
    if not games:
        return TableRagResult(
            answer=f"No available Knicks games were found for {season}.",
            evidence=[],
            warnings=[f"No available Knicks games for season {season}."],
        )

    summary_only = sum(1 for game in games if game.data_status == "summary_only")
    if summary_only:
        warnings.append(
            f"{summary_only} available game(s) are summary-only; aggregate score "
            "math is available, "
            "but event-level detail is incomplete."
        )

    evidence = [_game_evidence(game) for game in games]
    summary = polars_summary([_table_row(game) for game in games])
    wins = int(summary["wins"]) if summary else int(evaluate_table_expression("wins()", games))
    losses = (
        int(summary["losses"]) if summary else int(evaluate_table_expression("losses()", games))
    )
    points_for = (
        int(summary["points_for"])
        if summary
        else int(evaluate_table_expression("sum_points_for()", games))
    )
    points_against = (
        int(summary["points_against"])
        if summary
        else int(evaluate_table_expression("sum_points_against()", games))
    )
    intent = template_intent(question)
    unsupported_player_leader = any(
        term in q for term in ("who led", "who had", "player led", "player had", "leader")
    ) and any(
        term in q
        for term in (
            "assist",
            "block",
            "rebound",
            "scoring",
            "steal",
            "point",
            "turnover",
        )
    )
    if not unsupported_player_leader and "most" in q:
        unsupported_player_leader = any(
            term in q
            for term in (
                "assists",
                "blocks",
                "rebounds",
                "steals",
                "turnovers",
            )
        )
    unsupported_comeback = "comeback" in q

    if unsupported_player_leader:
        warnings.append(
            "The available season data does not include complete player box-score leader tables."
        )
        return TableRagResult(
            answer=(
                "I do not have enough available Knicks game data to name a player leader "
                "for that category."
            ),
            evidence=evidence,
            warnings=warnings,
        )

    if unsupported_comeback:
        warnings.append(
            "The available season data does not include complete lead-by-lead comeback rankings."
        )
        return TableRagResult(
            answer=("I do not have enough available Knicks game data to rank the best comeback."),
            evidence=evidence,
            warnings=warnings,
        )

    if intent is None:
        warnings.append(
            "This table view supports season record, scoring averages/totals, streaks, "
            "and largest win/loss margins. It does not have enough structured data for "
            "that specific ranking or breakdown."
        )
        return TableRagResult(
            answer=(
                "I do not have enough available Knicks game data to answer that "
                "specific table question."
            ),
            evidence=evidence,
            warnings=warnings,
        )

    if intent == "longest_losing_streak":
        longest_streak: list[Game] = []
        current_streak: list[Game] = []
        for game in games:
            knicks_score, opponent_score, _ = _knicks_scores(game)
            if knicks_score < opponent_score:
                current_streak.append(game)
                if len(current_streak) > len(longest_streak):
                    longest_streak = list(current_streak)
            else:
                current_streak = []
        if not longest_streak:
            answer = f"In the available {season} Knicks games, NYK has no losing streak."
            evidence = []
        else:
            streak_evidence = [_game_evidence(game) for game in longest_streak]
            evidence = [
                *streak_evidence,
                *[
                    _game_evidence(game)
                    for game in games
                    if game.id not in {item.id for item in longest_streak}
                ],
            ]
            start = streak_evidence[0]
            end = streak_evidence[-1]
            date_text = (
                start["date"]
                if start["date"] == end["date"]
                else f"{start['date']} through {end['date']}"
            )
            answer = (
                f"The Knicks' longest {season} losing streak in the available data is "
                f"{len(longest_streak)} game(s), from {date_text}."
            )
    elif intent == "largest_loss_margin":
        knicks_losses = [
            (game, *_knicks_scores(game))
            for game in games
            if _knicks_scores(game)[0] < _knicks_scores(game)[1]
        ]
        if not knicks_losses:
            answer = f"In the available {season} Knicks games, NYK has no losses to rank."
        else:
            game, knicks_score, opponent_score, opponent = max(
                knicks_losses,
                key=lambda item: (item[2] - item[1], item[2], str(item[0].game_date)),
            )
            evidence = [
                _game_evidence(game),
                *[_game_evidence(other_game) for other_game in games if other_game.id != game.id],
            ]
            margin = opponent_score - knicks_score
            answer = (
                f"The biggest {season} Knicks loss in the available data was {game.game_date} "
                f"against {opponent}: NYK lost {knicks_score}-{opponent_score} "
                f"by {margin}."
            )
    elif intent == "largest_win_margin":
        knicks_wins = [
            (game, *_knicks_scores(game))
            for game in games
            if _knicks_scores(game)[0] > _knicks_scores(game)[1]
        ]
        if not knicks_wins:
            answer = f"In the available {season} Knicks games, NYK has no wins to rank."
        else:
            game, knicks_score, opponent_score, opponent = max(
                knicks_wins,
                key=lambda item: (item[1] - item[2], item[1], str(item[0].game_date)),
            )
            evidence = [
                _game_evidence(game),
                *[_game_evidence(other_game) for other_game in games if other_game.id != game.id],
            ]
            margin = int(evaluate_table_expression("largest_win_margin()", games))
            if "why did you pick" in q or "why those" in q or "why that" in q:
                answer = (
                    f"I picked {game.game_date} against {opponent} because this route "
                    f"ranks available Knicks wins by final margin. NYK won "
                    f"{knicks_score}-{opponent_score}, a {margin}-point margin, which is "
                    f"the largest Knicks win margin in the available {season} games."
                )
            else:
                answer = (
                    f"The Knicks' best {season} game by win margin in the available data was "
                    f"{game.game_date} against {opponent}: NYK won "
                    f"{knicks_score}-{opponent_score} by {margin}."
                )
    elif intent == "record":
        answer = f"In the available {season} Knicks games, NYK is {wins}-{losses}."
    elif intent == "points_average":
        avg_for = (
            float(summary["avg_for"])
            if summary
            else float(evaluate_table_expression("average_points_for()", games))
        )
        avg_against = (
            float(summary["avg_against"])
            if summary
            else float(evaluate_table_expression("average_points_against()", games))
        )
        answer = (
            f"Across {len(games)} available {season} Knicks game(s), NYK averaged "
            f"{avg_for:.1f} points "
            f"and allowed {avg_against:.1f}."
        )
    elif intent == "points_total":
        answer = (
            f"Across {len(games)} available {season} Knicks game(s), NYK scored "
            f"{points_for} total points and allowed {points_against}."
        )
    else:
        answer = (
            f"Available season summary for {season}: {len(games)} game(s), "
            f"{wins}-{losses}, {points_for} points for, {points_against} against."
        )
    return TableRagResult(answer=answer, evidence=evidence, warnings=warnings)


async def answer_table_question(
    db: AsyncSession,
    question: str,
    *,
    season: str,
    timeout_seconds: float = TABLE_RAG_TIMEOUT_SECONDS,
) -> TableRagResult:
    """Answer aggregate questions from ORM-loaded rows only.

    The function does not evaluate user code, import runtime modules from user
    input, open files, make network calls, or mutate source basketball tables.
    """
    games = await asyncio.wait_for(_season_games(db, season), timeout=timeout_seconds)
    swing_answer = await asyncio.wait_for(
        _answer_swing_question(db, question, season, games),
        timeout=timeout_seconds,
    )
    if swing_answer is not None:
        return swing_answer
    box_score_answer = await asyncio.wait_for(
        _answer_box_score_question(db, question, season, games),
        timeout=timeout_seconds,
    )
    if box_score_answer is not None:
        return box_score_answer
    return await asyncio.wait_for(
        asyncio.to_thread(_answer_from_games, question, season, games),
        timeout=timeout_seconds,
    )


def _margin_position(value: int) -> str:
    if value > 0:
        return f"{value} points ahead"
    if value < 0:
        return f"{abs(value)} points behind"
    return "tied"


async def _answer_swing_question(
    db: AsyncSession,
    question: str,
    season: str,
    games: list[Game],
) -> TableRagResult | None:
    """Rank games by the observed range of the Knicks' score margin."""
    if "swing" not in question.lower():
        return None

    game_ids = [game.id for game in games]
    evidence = [_game_evidence(game) for game in games]
    if not game_ids:
        return TableRagResult(
            answer=f"No available Knicks games were found for {season}.",
            evidence=[],
            warnings=[f"No available Knicks games for season {season}."],
        )

    rows = (
        await db.execute(
            select(
                GameEvent.game_id,
                func.min(GameEvent.score_margin),
                func.max(GameEvent.score_margin),
            )
            .where(GameEvent.game_id.in_(game_ids))
            .group_by(GameEvent.game_id)
        )
    ).all()
    if not rows:
        return TableRagResult(
            answer=(
                "I do not have enough play-by-play score-margin data to rank "
                f"the wildest {season} Knicks games."
            ),
            evidence=evidence,
            warnings=["No play-by-play score-margin data is available for this ranking."],
        )

    games_by_id = {game.id: game for game in games}
    ranked: list[tuple[int, Game, int, int]] = []
    for game_id, minimum_home_margin, maximum_home_margin in rows:
        game = games_by_id.get(int(game_id))
        if game is None:
            continue
        minimum_home = min(int(minimum_home_margin), 0)
        maximum_home = max(int(maximum_home_margin), 0)
        if game.home_team_id == "NYK":
            minimum_knicks = minimum_home
            maximum_knicks = maximum_home
        else:
            minimum_knicks = -maximum_home
            maximum_knicks = -minimum_home
        ranked.append(
            (
                maximum_knicks - minimum_knicks,
                game,
                minimum_knicks,
                maximum_knicks,
            )
        )

    ranked.sort(
        key=lambda item: (item[0], item[3], str(item[1].game_date), item[1].id),
        reverse=True,
    )
    top = ranked[:5]
    if not top:
        return TableRagResult(
            answer=(
                "I do not have enough play-by-play score-margin data to rank "
                f"the wildest {season} Knicks games."
            ),
            evidence=evidence,
            warnings=["No play-by-play score-margin data is available for this ranking."],
        )

    top_ids = {game.id for _, game, _, _ in top}
    evidence = [
        *[_game_evidence(game) for _, game, _, _ in top],
        *[_game_evidence(game) for game in games if game.id not in top_ids],
    ]
    lines: list[str] = []
    for index, (margin_range, game, minimum_knicks, maximum_knicks) in enumerate(top, start=1):
        knicks_score, opponent_score, opponent = _knicks_scores(game)
        lines.append(
            f"{index}. {game.game_date} vs {opponent}: {margin_range}-point range "
            f"(between {_margin_position(minimum_knicks)} and "
            f"{_margin_position(maximum_knicks)}; final NYK "
            f"{knicks_score}-{opponent_score})."
        )

    event_ready_count = sum(game.data_status != "summary_only" for game in games)
    warnings = []
    if len(ranked) < event_ready_count:
        warnings.append(
            f"Swing ranking covers {len(ranked)} of {event_ready_count} "
            "event-ready games with score-margin data."
        )
    return TableRagResult(
        answer=(
            f"The wildest {season} Knicks games by observed score-margin range were:\n"
            + "\n".join(lines)
            + "\nThis measures the distance between the Knicks' largest deficit "
            "and largest lead in each game's available play-by-play."
        ),
        evidence=evidence,
        warnings=warnings,
    )


_STAT_TERMS = {
    "points": "points",
    "scoring": "points",
    "rebounds": "rebounds",
    "rebound": "rebounds",
    "assists": "assists",
    "assist": "assists",
    "turnovers": "turnovers",
    "turnover": "turnovers",
    "steals": "steals",
    "steal": "steals",
    "blocks": "blocks",
    "block": "blocks",
}


def _requested_stat(question: str) -> str | None:
    q = question.lower()
    return next((column for term, column in _STAT_TERMS.items() if term in q), None)


async def _answer_box_score_question(
    db: AsyncSession,
    question: str,
    season: str,
    games: list[Game],
) -> TableRagResult | None:
    """Authoritative SQL for facts that require complete box-score tables."""
    q = question.lower()
    stat = _requested_stat(question)
    game_ids = [game.id for game in games]
    if not game_ids:
        return None
    evidence = [_game_evidence(game) for game in games]

    if (
        stat
        and "beat the knicks" not in q
        and any(term in q for term in ("who led", "leader", "most", "which player"))
    ):
        stat_column = getattr(PlayerGameStat, stat)
        row = (
            await db.execute(
                select(Player.full_name, func.sum(stat_column).label("total"))
                .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                .where(
                    PlayerGameStat.game_id.in_(game_ids),
                    PlayerGameStat.team_id == "NYK",
                )
                .group_by(Player.id, Player.full_name)
                .order_by(func.sum(stat_column).desc(), Player.full_name)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return TableRagResult(
                answer=f"No complete player {stat} facts are available for {season}.",
                evidence=evidence,
                warnings=["Complete player box scores are unavailable."],
            )
        return TableRagResult(
            answer=(
                f"{row.full_name} led the Knicks with {int(row.total)} total {stat} in {season}."
            ),
            evidence=evidence,
            warnings=[],
        )

    if "quarter" in q or any(f"q{period}" in q for period in range(1, 5)):
        requested_period = next(
            (
                period
                for period in range(1, 5)
                if f"q{period}" in q
                or f"{period}st quarter" in q
                or f"{period}nd quarter" in q
                or f"{period}rd quarter" in q
                or f"{period}th quarter" in q
            ),
            None,
        )
        stmt = select(PeriodScore.period, func.sum(PeriodScore.points)).where(
            PeriodScore.game_id.in_(game_ids), PeriodScore.team_id == "NYK"
        )
        if requested_period:
            stmt = stmt.where(PeriodScore.period == requested_period)
        rows = (
            await db.execute(stmt.group_by(PeriodScore.period).order_by(PeriodScore.period))
        ).all()
        if not rows:
            return None
        totals = ", ".join(f"Q{period}: {int(points)}" for period, points in rows)
        return TableRagResult(
            answer=f"Knicks quarter scoring across available {season} games — {totals}.",
            evidence=evidence,
            warnings=[],
        )

    if "bench" in q:
        total = (
            await db.execute(
                select(func.sum(PlayerGameStat.points)).where(
                    PlayerGameStat.game_id.in_(game_ids),
                    PlayerGameStat.team_id == "NYK",
                    PlayerGameStat.starter.is_(False),
                )
            )
        ).scalar_one()
        if total is None:
            return None
        return TableRagResult(
            answer=(
                f"The Knicks bench scored {int(total)} total points across "
                f"available {season} games."
            ),
            evidence=evidence,
            warnings=[],
        )

    if any(term in q for term in ("shooting split", "from three", "three-point", "free throw")):
        made_attempted = (
            await db.execute(
                select(
                    func.sum(TeamGameStat.field_goals_made),
                    func.sum(TeamGameStat.field_goals_attempted),
                    func.sum(TeamGameStat.three_pointers_made),
                    func.sum(TeamGameStat.three_pointers_attempted),
                    func.sum(TeamGameStat.free_throws_made),
                    func.sum(TeamGameStat.free_throws_attempted),
                ).where(TeamGameStat.game_id.in_(game_ids), TeamGameStat.team_id == "NYK")
            )
        ).one()
        if made_attempted[1] is None:
            return None

        def pct(made: int, attempted: int) -> float:
            return 100 * made / attempted if attempted else 0.0

        fg_m, fg_a, three_m, three_a, ft_m, ft_a = map(int, made_attempted)
        return TableRagResult(
            answer=(
                f"Across available {season} games, NYK shot {fg_m}/{fg_a} "
                f"({pct(fg_m, fg_a):.1f}%) overall, {three_m}/{three_a} "
                f"({pct(three_m, three_a):.1f}%) from three, and {ft_m}/{ft_a} "
                f"({pct(ft_m, ft_a):.1f}%) at the line."
            ),
            evidence=evidence,
            warnings=[],
        )

    if stat and any(term in q for term in ("average", "total", "how many", "per game")):
        stat_column = getattr(TeamGameStat, stat)
        total = (
            await db.execute(
                select(func.sum(stat_column)).where(
                    TeamGameStat.game_id.in_(game_ids), TeamGameStat.team_id == "NYK"
                )
            )
        ).scalar_one()
        if total is None:
            return None
        total_value = int(total)
        if "average" in q or "per game" in q:
            answer = (
                f"The Knicks averaged {total_value / len(games):.1f} {stat} per game "
                f"in available {season} games."
            )
        else:
            answer = f"The Knicks recorded {total_value} total {stat} in available {season} games."
        return TableRagResult(answer=answer, evidence=evidence, warnings=[])
    return None
