"""Job: run scoring run + bad stretch detectors on a single game.

Reads `game_events` rows, runs the basketball-core detectors, and
upserts results into the `scoring_runs` and `bad_stretches` tables.
The API exposes these via /games/{id}/runs and /games/{id}/bad-stretches.
"""

from __future__ import annotations

import json
import socket
from typing import Any

from app.models.bad_stretch import BadStretch as BadStretchORM
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.scoring_run import ScoringRun as ScoringRunORM
from basketball_core.detectors.bad_stretch import BadStretchConfig, detect_bad_stretches
from basketball_core.detectors.impactful_run import ImpactfulRunConfig, detect_impactful_runs
from basketball_core.models.event import GameEvent as DomainGameEvent
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from worker_app.core.db import AsyncSessionLocal
from worker_app.jobs import mark_failed, mark_finished, mark_started


def _worker_name() -> str:
    return f"worker@{socket.gethostname()}"


def _to_domain(orm_event: GameEvent) -> DomainGameEvent:
    """Convert an ORM GameEvent to the basketball-core domain model."""
    return DomainGameEvent.model_validate(
        {
            "game_id": orm_event.game_id,
            "sequence": orm_event.sequence,
            "period": orm_event.period,
            "clock": orm_event.clock,
            "team_id": orm_event.team_id,
            "player_id": orm_event.player_id,
            "event_type": orm_event.event_type,
            "description": orm_event.description,
            "home_score": orm_event.home_score,
            "away_score": orm_event.away_score,
            "score_margin": orm_event.score_margin,
            "shot_type": orm_event.shot_type,
            "shot_result": orm_event.shot_result,
            "shot_distance_ft": orm_event.shot_distance_ft,
        }
    )


async def _delete_existing(db: AsyncSession, game_id: int) -> None:
    await db.execute(delete(ScoringRunORM).where(ScoringRunORM.game_id == game_id))
    await db.execute(delete(BadStretchORM).where(BadStretchORM.game_id == game_id))


async def detect_game_features(
    *,
    job_id: str,
    game_db_id: int,
) -> dict[str, Any]:
    """Run both detectors on a single game and persist results."""
    async with AsyncSessionLocal() as db:
        await mark_started(db, job_id, _worker_name())
        try:
            game = await db.get(Game, game_db_id)
            if not game:
                raise ValueError(f"Game {game_db_id} not found")

            # Load events via a fresh query to avoid lazy-load issues.
            from sqlalchemy import select

            stmt = (
                select(GameEvent)
                .where(GameEvent.game_id == game.id)
                .order_by(GameEvent.period, GameEvent.sequence)
            )
            result = await db.execute(stmt)
            orm_events = result.scalars().all()
            events = [_to_domain(e) for e in orm_events]

            if not events:
                # Nothing to detect — clear any stale rows.
                await _delete_existing(db, game.id)
                await db.commit()
                result_data = {
                    "game_id": game.id,
                    "nba_game_id": game.nba_game_id,
                    "events_processed": 0,
                    "runs_detected": 0,
                    "bad_stretches_detected": 0,
                }
                await mark_finished(db, job_id, result_data)
                return result_data

            run_config = ImpactfulRunConfig(
                home_team_id=game.home_team_id,
                away_team_id=game.away_team_id,
                season_type=game.season_type,
            )
            bad_stretch_config = BadStretchConfig(
                home_team_id=game.home_team_id,
                away_team_id=game.away_team_id,
                season_type=game.season_type,
            )
            runs = detect_impactful_runs(events, run_config)
            bad_stretches = detect_bad_stretches(events, bad_stretch_config)

            await _delete_existing(db, game.id)

            for run in runs:
                db.add(
                    ScoringRunORM(
                        game_id=game.id,
                        team_id=run.team_id,
                        period=run.period,
                        start_sequence=run.start_sequence,
                        end_sequence=run.end_sequence,
                        start_clock=run.start_clock,
                        end_clock=run.end_clock,
                        points_for=run.points_for,
                        points_against=run.points_against,
                        score_delta=run.score_delta,
                        event_count=run.event_count,
                        summary=run.summary,
                    )
                )
            for stretch in bad_stretches:
                db.add(
                    BadStretchORM(
                        game_id=game.id,
                        period=stretch.period,
                        start_clock=stretch.start_clock,
                        end_clock=stretch.end_clock,
                        score_delta=stretch.score_delta,
                        summary=stretch.summary,
                        likely_causes=json.dumps(stretch.likely_causes),
                        knicks_turnovers=stretch.knicks_turnovers,
                        knicks_missed_shots=stretch.knicks_missed_shots,
                        opponent_fast_breaks=stretch.opponent_fast_breaks,
                    )
                )

            await db.commit()

            result_data = {
                "game_id": game.id,
                "nba_game_id": game.nba_game_id,
                "events_processed": len(events),
                "runs_detected": len(runs),
                "bad_stretches_detected": len(bad_stretches),
            }
            await mark_finished(db, job_id, result_data)
            return result_data
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            await mark_failed(db, job_id, str(exc))
            raise
