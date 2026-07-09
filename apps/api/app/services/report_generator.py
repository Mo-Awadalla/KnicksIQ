"""Postgame report generator.

Orchestrates: fetch game data → assemble context → call LLM →
validate citations → persist Report row with tool trace.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.bad_stretch import BadStretch
from app.models.game import Game
from app.models.game_event import GameEvent
from app.models.report import Report
from app.models.scoring_run import ScoringRun
from app.services.report_llm import LLMAdapter, get_llm_adapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _fetch_game(db: AsyncSession, game_id: int) -> Game | None:
    return await db.get(Game, game_id)


async def _fetch_runs(db: AsyncSession, game_id: int) -> list[dict[str, Any]]:
    stmt = (
        select(ScoringRun)
        .where(ScoringRun.game_id == game_id)
        .order_by(ScoringRun.period, ScoringRun.start_sequence)
    )
    runs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "team_id": r.team_id,
            "period": r.period,
            "start_clock": r.start_clock,
            "end_clock": r.end_clock,
            "points_for": r.points_for,
            "points_against": r.points_against,
            "score_delta": r.score_delta,
            "event_count": r.event_count,
        }
        for r in runs
    ]


async def _fetch_bad_stretches(db: AsyncSession, game_id: int) -> list[dict[str, Any]]:
    stmt = (
        select(BadStretch)
        .where(BadStretch.game_id == game_id)
        .order_by(BadStretch.period, BadStretch.start_clock)
    )
    rows = (await db.execute(stmt)).scalars().all()
    out = []
    for s in rows:
        out.append(
            {
                "period": s.period,
                "start_clock": s.start_clock,
                "end_clock": s.end_clock,
                "score_delta": s.score_delta,
                "summary": s.summary,
                "likely_causes": json.loads(s.likely_causes) if s.likely_causes else [],
                "knicks_turnovers": s.knicks_turnovers,
                "knicks_missed_shots": s.knicks_missed_shots,
            }
        )
    return out


async def _fetch_event_snippets(db: AsyncSession, game_id: int, limit: int = 6) -> list[str]:
    stmt = (
        select(GameEvent)
        .where(GameEvent.game_id == game_id)
        .where(GameEvent.event_type.in_(("made_shot", "turnover", "missed_shot")))
        .order_by(GameEvent.period, GameEvent.sequence)
        .limit(limit)
    )
    events = (await db.execute(stmt)).scalars().all()
    return [e.description for e in events if e.description]


def _build_context(
    game: Game, runs: list[dict], stretches: list[dict], snippets: list[str]
) -> dict[str, Any]:
    return {
        "game": {
            "id": game.id,
            "home_team_id": game.home_team_id,
            "away_team_id": game.away_team_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "status": game.status,
            "season": game.season,
            "game_date": str(game.game_date),
        },
        "scoring_runs": runs,
        "bad_stretches": stretches,
        "event_snippets": snippets,
    }


def _build_system_prompt() -> str:
    return (
        "You are a Knicks postgame analyst. Produce a JSON report with the "
        "fields: title, summary, turning_point, best_stretch, worst_stretch, "
        "player_notes (list), suggested_adjustments (list). Ground every claim "
        "in the supplied scoring runs and bad stretches."
    )


def _validate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Light validation: required fields present, types correct."""
    required = [
        "title",
        "summary",
        "turning_point",
        "best_stretch",
        "worst_stretch",
        "player_notes",
        "suggested_adjustments",
    ]
    for key in required:
        if key not in report:
            raise ValueError(f"Report missing required field: {key}")
    if not isinstance(report["player_notes"], list):
        raise ValueError("player_notes must be a list")
    if not isinstance(report["suggested_adjustments"], list):
        raise ValueError("suggested_adjustments must be a list")
    return report


async def generate_postgame_report(
    *,
    game_id: int,
    llm: LLMAdapter | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Generate a postgame report and persist it. Returns the saved report row.

    The function records a tool-call trace (`tool_trace_json`) so the
    caller can audit which data sources were consulted.
    """
    llm = llm or get_llm_adapter()
    tool_trace: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as db:
        # Tool: fetch_game
        t0 = time.perf_counter()
        game = await _fetch_game(db, game_id)
        tool_trace.append(
            {
                "tool": "fetch_game",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result": "ok" if game else "missing",
            }
        )
        if not game:
            raise ValueError(f"Game {game_id} not found")

        t0 = time.perf_counter()
        runs = await _fetch_runs(db, game_id)
        tool_trace.append(
            {
                "tool": "fetch_scoring_runs",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": len(runs),
            }
        )

        t0 = time.perf_counter()
        stretches = await _fetch_bad_stretches(db, game_id)
        tool_trace.append(
            {
                "tool": "fetch_bad_stretches",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": len(stretches),
            }
        )

        t0 = time.perf_counter()
        snippets = await _fetch_event_snippets(db, game_id)
        tool_trace.append(
            {
                "tool": "fetch_event_snippets",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": len(snippets),
            }
        )

        context = _build_context(game, runs, stretches, snippets)

        # LLM call.
        t0 = time.perf_counter()
        llm_response = await llm.generate(
            system=_build_system_prompt(),
            user=json.dumps(context, default=str),
        )
        llm_latency = int((time.perf_counter() - t0) * 1000)
        tool_trace.append(
            {
                "tool": "llm_generate",
                "latency_ms": llm_latency,
                "model": llm.__class__.__name__,
            }
        )

        report = _validate_report(json.loads(llm_response))

        # Persist.
        sources = [
            {"type": "scoring_run", "game_id": game_id, "runs_count": len(runs)},
            {"type": "bad_stretch", "game_id": game_id, "stretches_count": len(stretches)},
            {"type": "play_by_play", "game_id": game_id, "snippets_count": len(snippets)},
        ]
        report_row = Report(
            game_id=game_id,
            report_type="postgame",
            title=report["title"],
            summary=report["summary"],
            turning_point=report["turning_point"],
            best_stretch=report["best_stretch"],
            worst_stretch=report["worst_stretch"],
            player_notes=json.dumps(report["player_notes"]),
            suggested_adjustments=json.dumps(report["suggested_adjustments"]),
            sources_json=json.dumps(sources),
            tool_trace_json=json.dumps(tool_trace),
        )
        db.add(report_row)
        await db.commit()
        await db.refresh(report_row)

        return {
            "id": report_row.id,
            "game_id": report_row.game_id,
            "title": report_row.title,
            "summary": report_row.summary,
            "turning_point": report_row.turning_point,
            "best_stretch": report_row.best_stretch,
            "worst_stretch": report_row.worst_stretch,
            "player_notes": json.loads(report_row.player_notes),
            "suggested_adjustments": json.loads(report_row.suggested_adjustments),
            "sources": json.loads(report_row.sources_json),
            "tool_calls": json.loads(report_row.tool_trace_json),
            "created_at": report_row.created_at.isoformat(),
        }


def new_report_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
