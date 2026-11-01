"""Lexical PostgreSQL statements and row-to-evidence mapping for the archive.

Each collection owns one statement and one metadata shape, so adding a collection
never touches the others. Ordering, limits and the release scope are applied by
the caller in :mod:`app.services.archive_retrieval`.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.models.box_score import PlayerGameStat, TeamGameStat
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.player import Player
from app.models.report import Report
from app.services.archive_clock import GameMoment
from app.services.archive_documents import (
    game_document,
    player_box_document,
    report_document,
    team_box_document,
)
from app.services.archive_evidence import ArchiveEvidence
from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 2}


def clean_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, [], {}, "")}


def game_filter_clauses(filters: dict[str, Any]) -> list[Any]:
    clauses: list[Any] = []
    if filters.get("dates"):
        clauses.append(Game.game_date.in_([date.fromisoformat(item) for item in filters["dates"]]))
    if filters.get("game_ids"):
        clauses.append(Game.id.in_(filters["game_ids"]))
    if filters.get("season_types"):
        clauses.append(Game.season_type.in_(filters["season_types"]))
    team_ids = set(filters.get("team_ids") or [])
    if team_ids:
        clauses.append(or_(Game.home_team_id.in_(team_ids), Game.away_team_id.in_(team_ids)))
    return clauses


def lexical_match(db: AsyncSession, text_expression: Any, query: str) -> tuple[Any, Any]:
    """Return a backend-appropriate match predicate and rank expression."""
    if db.bind and db.bind.dialect.name == "postgresql":
        vector = func.to_tsvector("simple", func.coalesce(text_expression, ""))
        tsquery = func.websearch_to_tsquery("simple", query)
        return vector.op("@@")(tsquery), func.ts_rank_cd(vector, tsquery)
    lowered = query.lower()
    tokens = sorted(_tokens(lowered))
    if not tokens:
        return literal(True), literal(0.0)
    predicates = [func.lower(text_expression).contains(token) for token in tokens]
    rank = sum(
        (case((func.lower(text_expression).contains(token), 1), else_=0) for token in tokens),
        literal(0),
    )
    return or_(*predicates), rank


async def game_evidence(
    db: AsyncSession,
    *,
    query: str,
    game_clauses: list[Any],
    release_id: int | None,
    limit: int,
    data_version: str,
) -> list[ArchiveEvidence]:
    text = (
        Game.away_team_id
        + " "
        + cast(Game.away_score, String)
        + " at "
        + Game.home_team_id
        + " "
        + cast(Game.home_score, String)
        + " "
        + func.coalesce(Game.game_label, "")
    )
    match, rank = lexical_match(db, text, query)
    stmt = select(Game, text.label("text"), rank.label("rank")).where(match, *game_clauses)
    if release_id is not None:
        stmt = stmt.where(Game.release_id == release_id)
    evidence: list[ArchiveEvidence] = []
    for game, value, score in (await db.execute(stmt.order_by(rank.desc()).limit(limit))).all():
        metadata = {
            "game_id": game.id,
            "date": str(game.game_date),
            "team_ids": [game.home_team_id, game.away_team_id],
            "season_type": game.season_type,
            "data_version": data_version,
            "source_row_id": game.id,
            "retrieval_sources": ["lexical"],
        }
        evidence.append(
            game_document(game, data_version).evidence(
                score=float(score or 0),
                source="lexical",
                evidence_id=f"lexical:games:{game.id}",
                text=str(value),
                extra=metadata,
            )
        )
    return evidence


async def report_evidence(
    db: AsyncSession,
    *,
    query: str,
    game_clauses: list[Any],
    release_id: int | None,
    limit: int,
    data_version: str,
) -> list[ArchiveEvidence]:
    text = Report.title + " " + Report.summary + " " + Report.turning_point
    match, rank = lexical_match(db, text, query)
    stmt = (
        select(Report, Game, text.label("text"), rank.label("rank"))
        .join(Game, Game.id == Report.game_id)
        .where(Report.reviewed.is_(True), match, *game_clauses)
    )
    if release_id is not None:
        stmt = stmt.where(Report.release_id == release_id, Game.release_id == release_id)
    evidence: list[ArchiveEvidence] = []
    for report, game, value, score in (
        await db.execute(stmt.order_by(rank.desc()).limit(limit))
    ).all():
        metadata = {
            "game_id": game.id,
            "report_id": report.id,
            "date": str(game.game_date),
            "team_ids": [game.home_team_id, game.away_team_id],
            "season_type": game.season_type,
            "data_version": data_version,
            "retrieval_sources": ["lexical"],
        }
        evidence.append(
            report_document(report, game, data_version).evidence(
                score=float(score or 0),
                source="lexical",
                evidence_id=f"lexical:reports:{report.id}",
                text=str(value),
                extra=metadata,
            )
        )
    return evidence


async def team_stat_evidence(
    db: AsyncSession,
    *,
    query: str,
    game_clauses: list[Any],
    release_id: int | None,
    limit: int,
    data_version: str,
) -> list[ArchiveEvidence]:
    text = (
        TeamGameStat.team_id
        + " "
        + cast(TeamGameStat.points, String)
        + " points "
        + cast(TeamGameStat.rebounds, String)
        + " rebounds "
        + cast(TeamGameStat.assists, String)
        + " assists "
        + cast(TeamGameStat.turnovers, String)
        + " turnovers"
    )
    match, rank = lexical_match(db, text, query)
    stmt = (
        select(
            TeamGameStat,
            Game,
            text.label("text"),
            rank.label("rank"),
        )
        .join(Game, Game.id == TeamGameStat.game_id)
        .where(match, *game_clauses)
    )
    if release_id is not None:
        stmt = stmt.where(
            TeamGameStat.release_id == release_id,
            Game.release_id == release_id,
        )
    evidence: list[ArchiveEvidence] = []
    for stat, game, value, score in (
        await db.execute(stmt.order_by(rank.desc()).limit(limit))
    ).all():
        metadata = {
            "game_id": game.id,
            "source_row_id": f"team:{stat.id}",
            "date": str(game.game_date),
            "team_ids": [stat.team_id],
            "season_type": game.season_type,
            "data_version": data_version,
            "retrieval_sources": ["lexical"],
        }
        evidence.append(
            team_box_document(stat, game, data_version).evidence(
                score=float(score or 0),
                source="lexical",
                evidence_id=f"lexical:box_scores:team:{stat.id}",
                text=str(value),
                extra=metadata,
            )
        )
    return evidence


async def player_stat_evidence(
    db: AsyncSession,
    *,
    query: str,
    game_clauses: list[Any],
    release_id: int | None,
    limit: int,
    data_version: str,
    player_ids: list[int] | None,
) -> list[ArchiveEvidence]:
    text = (
        Player.full_name
        + " "
        + cast(PlayerGameStat.points, String)
        + " points "
        + cast(PlayerGameStat.rebounds, String)
        + " rebounds "
        + cast(PlayerGameStat.assists, String)
        + " assists"
    )
    match, rank = lexical_match(db, text, query)
    stmt = (
        select(PlayerGameStat, Player, Game, text.label("text"), rank.label("rank"))
        .join(Player, Player.id == PlayerGameStat.player_id)
        .join(Game, Game.id == PlayerGameStat.game_id)
        .where(match, *game_clauses)
    )
    if player_ids:
        stmt = stmt.where(PlayerGameStat.player_id.in_(player_ids))
    if release_id is not None:
        stmt = stmt.where(
            PlayerGameStat.release_id == release_id,
            Game.release_id == release_id,
        )
    evidence: list[ArchiveEvidence] = []
    for stat, player, game, value, score in (
        await db.execute(stmt.order_by(rank.desc()).limit(limit))
    ).all():
        metadata = {
            "game_id": game.id,
            "source_row_id": stat.id,
            "date": str(game.game_date),
            "team_ids": [stat.team_id],
            "player_ids": [stat.player_id],
            "player_names": [player.full_name],
            "season_type": game.season_type,
            "data_version": data_version,
            "retrieval_sources": ["lexical"],
        }
        evidence.append(
            player_box_document(stat, game, data_version).evidence(
                score=float(score or 0),
                source="lexical",
                evidence_id=f"lexical:box_scores:{stat.id}",
                text=str(value),
                extra=metadata,
            )
        )
    return evidence


async def possession_evidence(
    db: AsyncSession,
    *,
    query: str,
    game_clauses: list[Any],
    release_id: int | None,
    limit: int,
    data_version: str,
    periods: list[int] | None,
    player_ids: list[int] | None,
    moment: GameMoment | None,
) -> list[ArchiveEvidence]:
    from app.core.config import get_settings
    from app.services.archive_documents import possession_document
    from app.services.possession_chunks import build_possession_chunks
    from app.services.rag_ranking import lexical_rank_chunks
    from sqlalchemy.orm import selectinload

    statement = select(Game).where(*game_clauses)
    if release_id is not None:
        statement = statement.where(Game.release_id == release_id)
    games = list((await db.execute(statement.order_by(Game.game_date, Game.id))).scalars().all())
    if not games:
        return []
    events = list(
        (
            await db.execute(
                select(GameEvent)
                .options(selectinload(GameEvent.player))
                .where(GameEvent.game_id.in_([game.id for game in games]))
                .order_by(
                    GameEvent.game_id,
                    GameEvent.period,
                    GameEvent.sequence,
                    GameEvent.id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_game: dict[int, list[GameEvent]] = {}
    for event in events:
        by_game.setdefault(event.game_id, []).append(event)

    settings = get_settings()
    chunks = []
    wanted_players = set(player_ids or ())
    wanted_periods = set(periods or ())
    for game in games:
        for chunk in build_possession_chunks(
            game,
            by_game.get(game.id, []),
            contextual_event_windows=settings.rag_contextual_event_windows_enabled,
        ):
            metadata = chunk.metadata
            if wanted_players and not (wanted_players & set(metadata.get("player_ids") or ())):
                continue
            start = int(metadata["start_period"])
            end = int(metadata["end_period"])
            if wanted_periods and not any(start <= period <= end for period in wanted_periods):
                continue
            if moment is not None and not any(moment.matches(row) for row in chunk.rows):
                continue
            chunks.append(chunk)

    ranked, _ = lexical_rank_chunks(query, chunks)
    return [
        possession_document(chunk, data_version).evidence(
            score=score,
            source="lexical",
        )
        for chunk, score in ranked[:limit]
    ]
