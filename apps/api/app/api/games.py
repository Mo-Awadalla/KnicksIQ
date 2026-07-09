"""Game-related endpoints."""

from __future__ import annotations

import json
from typing import Annotated

from basketball_core.detectors.bad_stretch import BadStretchConfig, detect_bad_stretches
from basketball_core.detectors.impactful_run import ImpactfulRunConfig, detect_impactful_runs
from basketball_core.models.event import GameEvent as CoreGameEvent
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.jobs import JobAcceptedResponse
from app.api.security import require_admin_api_key
from app.core.db import get_db
from app.models.bad_stretch import BadStretch
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.scoring_run import ScoringRun
from app.schemas.game import (
    BadStretchRead,
    GameDetail,
    GameEventRead,
    GameSummary,
    ScoringRunRead,
)

router = APIRouter(prefix="/games", tags=["games"])


def _to_summary(game: Game) -> GameSummary:
    return GameSummary(
        id=game.id,
        nba_game_id=game.nba_game_id,
        season=game.season,
        game_date=game.game_date,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        home_score=game.home_score,
        away_score=game.away_score,
        status=game.status,
        season_type=game.season_type,
        data_status=game.data_status,
        source_name=game.source_name,
        source_url=game.source_url,
        source_game_id=game.source_game_id,
        game_label=game.game_label,
        series_name=game.series_name,
        series_game_number=game.series_game_number,
        margin=game.home_score - game.away_score,
        winner_team_id=(
            game.home_team_id if game.home_score > game.away_score else game.away_team_id
        ),
    )


def _orm_event_to_core(event: GameEvent) -> CoreGameEvent:
    return CoreGameEvent(
        id=event.id,
        game_id=event.game_id,
        sequence=event.sequence,
        period=event.period,
        clock=event.clock,
        team_id=event.team_id,
        player_id=event.player_id,
        event_type=event.event_type,
        description=event.description,
        home_score=event.home_score,
        away_score=event.away_score,
        score_margin=event.score_margin,
        shot_type=event.shot_type,
        shot_result=event.shot_result,
        shot_distance_ft=event.shot_distance_ft,
    )


async def _load_game_or_404(db: AsyncSession, game_id: int) -> Game:
    game = await db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    return game


def _ensure_events_ready(game: Game) -> None:
    if game.data_status == "summary_only":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Play-by-play data is not available for this game",
        )


@router.get("", response_model=list[GameSummary])
async def list_games(
    db: Annotated[AsyncSession, Depends(get_db)],
    season: str | None = Query(None, description="Filter by season, e.g. '2024-25'"),
    team_id: str | None = Query(None, description="Filter by team abbreviation"),
    status_filter: str | None = Query(None, alias="status"),
    season_type: str | None = Query(None, description="regular, play_in, or playoffs"),
    data_status: str | None = Query(None, description="summary_only, events_ready, analysis_ready"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[GameSummary]:
    stmt = select(Game)
    if season:
        stmt = stmt.where(Game.season == season)
    if team_id:
        stmt = stmt.where((Game.home_team_id == team_id) | (Game.away_team_id == team_id))
    if status_filter:
        stmt = stmt.where(Game.status == status_filter)
    if season_type:
        stmt = stmt.where(Game.season_type == season_type)
    if data_status:
        stmt = stmt.where(Game.data_status == data_status)
    stmt = stmt.order_by(Game.game_date.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    games = result.scalars().all()
    return [_to_summary(g) for g in games]


@router.get("/{game_id}", response_model=GameDetail)
async def get_game(
    game_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameDetail:
    stmt = (
        select(Game)
        .options(selectinload(Game.home_team), selectinload(Game.away_team))
        .where(Game.id == game_id)
    )
    result = await db.execute(stmt)
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    summary = _to_summary(game)
    return GameDetail(
        **summary.model_dump(),
        home_team=game.home_team,
        away_team=game.away_team,
    )


@router.get("/{game_id}/play-by-play", response_model=list[GameEventRead])
async def get_play_by_play(
    game_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    period: int | None = Query(None, ge=1, le=14),
) -> list[GameEventRead]:
    game = await _load_game_or_404(db, game_id)
    _ensure_events_ready(game)
    stmt = (
        select(GameEvent)
        .options(selectinload(GameEvent.player))
        .where(GameEvent.game_id == game_id)
        .order_by(GameEvent.period, GameEvent.sequence)
    )
    if period is not None:
        stmt = stmt.where(GameEvent.period == period)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return [GameEventRead.model_validate(e) for e in events]


@router.get("/{game_id}/runs", response_model=list[ScoringRunRead])
async def get_runs(
    game_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    team_id: str | None = Query(None, description="Filter by team abbreviation"),
) -> list[ScoringRunRead]:
    game = await _load_game_or_404(db, game_id)
    _ensure_events_ready(game)
    stmt = (
        select(ScoringRun)
        .where(ScoringRun.game_id == game_id)
        .order_by(ScoringRun.period, ScoringRun.start_sequence)
    )
    if team_id:
        stmt = stmt.where(ScoringRun.team_id == team_id)
    result = await db.execute(stmt)
    runs = result.scalars().all()
    if runs:
        return [ScoringRunRead.model_validate(r) for r in runs]

    event_rows = (
        await db.execute(
            select(GameEvent)
            .where(GameEvent.game_id == game_id)
            .order_by(GameEvent.period, GameEvent.sequence)
        )
    ).scalars().all()
    computed = detect_impactful_runs(
        [_orm_event_to_core(e) for e in event_rows],
        ImpactfulRunConfig(
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
            season_type=game.season_type,
        ),
    )
    if team_id:
        computed = [r for r in computed if r.team_id == team_id]
    return [
        ScoringRunRead(
            id=0,
            game_id=r.game_id,
            team_id=r.team_id,
            period=r.period,
            start_clock=r.start_clock,
            end_clock=r.end_clock,
            points_for=r.points_for,
            points_against=r.points_against,
            score_delta=r.score_delta,
            event_count=r.event_count,
            summary=r.summary,
        )
        for r in computed
    ]


@router.get("/{game_id}/bad-stretches", response_model=list[BadStretchRead])
async def get_bad_stretches(
    game_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[BadStretchRead]:
    game = await _load_game_or_404(db, game_id)
    _ensure_events_ready(game)
    stmt = (
        select(BadStretch)
        .where(BadStretch.game_id == game_id)
        .order_by(BadStretch.period, BadStretch.start_clock)
    )
    result = await db.execute(stmt)
    stretches = result.scalars().all()
    out: list[BadStretchRead] = []
    if not stretches:
        event_rows = (
            await db.execute(
                select(GameEvent)
                .where(GameEvent.game_id == game_id)
                .order_by(GameEvent.period, GameEvent.sequence)
            )
        ).scalars().all()
        computed = detect_bad_stretches(
            [_orm_event_to_core(e) for e in event_rows],
            BadStretchConfig(
                home_team_id=game.home_team_id,
                away_team_id=game.away_team_id,
                season_type=game.season_type,
            ),
        )
        return [
            BadStretchRead(
                id=0,
                game_id=s.game_id,
                period=s.period,
                start_clock=s.start_clock,
                end_clock=s.end_clock,
                score_delta=s.score_delta,
                summary=s.summary,
                likely_causes=s.likely_causes,
                knicks_turnovers=s.knicks_turnovers,
                knicks_missed_shots=s.knicks_missed_shots,
                opponent_fast_breaks=s.opponent_fast_breaks,
            )
            for s in computed
        ]

    for s in stretches:
        causes: list[str] = []
        if s.likely_causes:
            try:
                causes = json.loads(s.likely_causes)
            except (TypeError, ValueError):
                causes = []
        out.append(
            BadStretchRead(
                id=s.id,
                game_id=s.game_id,
                period=s.period,
                start_clock=s.start_clock,
                end_clock=s.end_clock,
                score_delta=s.score_delta,
                summary=s.summary,
                likely_causes=causes,
                knicks_turnovers=s.knicks_turnovers,
                knicks_missed_shots=s.knicks_missed_shots,
                opponent_fast_breaks=s.opponent_fast_breaks,
            )
        )
    return out


@router.post(
    "/{game_id}/detect-runs",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin_api_key)],
)
async def trigger_detect_runs(game_id: int) -> JobAcceptedResponse:
    """Enqueue a job to (re)compute scoring runs and bad stretches for a game.

    Once the worker finishes, the data is queryable via:
      - GET /games/{id}/runs
      - GET /games/{id}/bad-stretches
    """
    from worker_app.job_queue import enqueue_detect_runs

    job_id = enqueue_detect_runs(game_db_id=game_id)
    # Reuse the API's job row creation helper.
    from app.api.jobs import _create_job_row

    await _create_job_row(job_id, "detect_runs", {"game_id": game_id})
    return JobAcceptedResponse(job_id=job_id, status="queued")
