"""Table rag swings."""

from __future__ import annotations

from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.table_rag_types import TableRagResult, _game_evidence, _knicks_scores
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


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
