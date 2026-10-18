"""Table rag games."""

from __future__ import annotations

import re
from typing import Any

from app.models.game import Game
from app.services.releases import restrict_to_active_release
from app.services.table_rag_sandbox import evaluate_table_expression
from app.services.table_rag_templates import polars_summary, template_intent
from app.services.table_rag_types import TableRagResult, _game_evidence, _knicks_scores, _table_row
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DATA_STATUS_RANK = {"summary_only": 0, "events_ready": 1, "analysis_ready": 2}


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
    elif intent == "average_margin":
        answer = (
            f"Across {len(games)} available {season} games, the Knicks averaged a "
            f"{(points_for - points_against) / len(games):+.1f}-point margin."
        )
    elif intent == "points_allowed":
        answer = (
            f"Across {len(games)} available {season} games, the Knicks allowed "
            f"{points_against / len(games):.1f} points per game ({points_against} total)."
        )
    elif intent in {"highest_scoring", "lowest_scoring"}:
        pick = max if intent == "highest_scoring" else min
        game = pick(games, key=lambda game: _knicks_scores(game)[0])
        own, other, opponent = _knicks_scores(game)
        label = "highest" if intent == "highest_scoring" else "lowest"
        answer = (
            f"The Knicks' {label}-scoring game was {game.game_date} against {opponent}: "
            f"NYK scored {own} points (opponent {other})."
        )
        evidence = [_game_evidence(game)]
    elif intent == "game_count":
        answer = f"The Knicks played {len(games)} matching games in the available {season} archive."
    elif intent == "score_threshold":
        match = re.search(r"\b(at least|under|over|fewer than|more than)\s+(\d+)", q)
        assert match is not None
        operator, target = match[1], int(match[2])
        against = "opponent" in q or "allow" in q

        def passes(game: Game) -> bool:
            own, other, _ = _knicks_scores(game)
            value = other if against else own
            return (
                value >= target
                if operator == "at least"
                else value < target
                if operator in {"under", "fewer than"}
                else value > target
            )

        matching = [game for game in games if passes(game)]
        subject = "opponents scored" if against else "NYK scored"
        answer = (
            f"In {len(matching)} of {len(games)} available {season} games, "
            f"{subject} {operator} {target} points."
        )
        evidence = [_game_evidence(game) for game in matching]
    elif intent in {"win_count", "loss_count"}:
        count = wins if intent == "win_count" else losses
        verb = "won" if intent == "win_count" else "lost"
        answer = (
            f"In the available {season} Knicks games, NYK {verb} {count} of {len(games)} games."
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
