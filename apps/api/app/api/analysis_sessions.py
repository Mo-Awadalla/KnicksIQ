"""Evidence analyst turns and verified conversation session commits."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analysis_policy as runtime
from app.api.analysis_models import AnalysisQueryRequest, AnalysisQueryResponse
from app.api.analysis_retrieval import _sample_shadow
from app.models.dataset_release import DatasetRelease

if TYPE_CHECKING:
    from app.services.analyst_sessions import SessionTurn

logger = logging.getLogger(__name__)


async def _finish_turn(
    turn: SessionTurn | None, response: AnalysisQueryResponse, state: dict[str, Any]
) -> AnalysisQueryResponse:
    if turn is None:
        return response
    response.session_token = turn.token
    response.session_expires_at = datetime.now(UTC) + timedelta(seconds=86_400)
    response.revision = turn.revision + 1
    response.state_committed = True
    outcome = await turn.commit(response.model_dump(mode="json"), state)
    if outcome.response is not None:
        return AnalysisQueryResponse.model_validate(outcome.response)
    if not outcome.committed:
        response.session_token = None
        response.session_expires_at = None
        response.revision = None
        response.state_committed = False
        response.degraded = True
        response.warnings.append(
            "Conversation state could not be committed. Retry the same turn."
        )
    return response


async def _query_evidence_analyst(
    req: AnalysisQueryRequest,
    request: Request,
    db: AsyncSession,
    *,
    immediate_response: AnalysisQueryResponse | None = None,
) -> AnalysisQueryResponse:
    from app.services.analyst_loop import AnalystLoop
    from app.services.analyst_sessions import SessionConflict, SessionTurn, SessionUnavailable
    from app.services.analyst_tools import AnalystTools

    started = time.monotonic()
    release = (
        await db.execute(
            select(DatasetRelease).where(
                DatasetRelease.status == "active",
                DatasetRelease.validation_passed.is_(True),
            )
        )
    ).scalar_one_or_none()
    if release is None and immediate_response is None:
        return AnalysisQueryResponse(
            answer="No verified archive release is available.", citations=[], degraded=True
        )
    if not req.turn_id:
        # Legacy clients get a factual response; they cannot supply authoritative state.
        turn = None
    else:
        try:
            turn = await SessionTurn.begin(
                req.session_token,
                req.turn_id,
                req.expected_revision,
                {
                    "question": req.question,
                    "season": req.season,
                    "context": [m.model_dump() for m in req.context],
                },
            )
        except SessionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={"reason": exc.reason},
            ) from exc
        except SessionUnavailable:
            turn = None
    if turn and turn.replay is not None:
        return AnalysisQueryResponse.model_validate(turn.replay)
    try:
        if immediate_response is not None:
            # Policy and greeting turns participate in revision/replay handling without
            # changing the archive topic or spending a model call.
            return await _finish_turn(turn, immediate_response, turn.state if turn else {})
        assert release is not None
        tools = AnalystTools(db, release, req.question, req.season, turn.state if turn else {})
        prepare_started = time.monotonic()
        async with asyncio.timeout(
            max(
                0.001,
                runtime.get_settings().analyst_deadline_seconds - (time.monotonic() - started),
            )
        ):
            await tools.prepare()
        prepare_ms = round((time.monotonic() - prepare_started) * 1000)
        loop = AnalystLoop(tools, [m.model_dump() for m in req.context], started=started)
        loop.trace.append(
            {
                "stage": "prepare",
                "tool": "session_and_release",
                "latency_ms": round((prepare_started - started) * 1000),
            }
        )
        loop.trace.append({"stage": "prepare", "tool": "prepare_total", "latency_ms": prepare_ms})
        loop.trace.extend(tools.timings)
        loop.request_id = getattr(request.state, "request_id", "")
        settings = runtime.get_settings()
        answer_mode = settings.analysis_answer_mode
        shadow_sampled = answer_mode == "shadow" and _sample_shadow(
            loop.request_id, settings.analysis_shadow_sample_rate
        )
        result = await loop.run(
            allow_model=bool(turn) and (answer_mode == "llm_primary" or shadow_sampled)
        )
        state = result.pop("state")
        if answer_mode == "shadow":
            logger.info(
                "analyst_shadow_verification",
                extra={
                    "sampled": shadow_sampled,
                    "validated": result["llm_validated"],
                    "model_calls": loop.calls,
                    "tool_rounds": loop.rounds,
                    "data_version": release.version,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "model": runtime.get_settings().ai_chat_model,
                },
            )
        # Shadow exercises the same reserved, validated path but delivers only backend facts.
        if answer_mode == "shadow" and result["llm_validated"]:
            result = loop.render_fallback("Shadow verification; deterministic delivery.")
            state = result.pop("state")
        response = AnalysisQueryResponse(
            **result, request_id=getattr(request.state, "request_id", "")
        )
        if turn is None:
            response.warnings.append(
                "Stateless factual fallback: conversation storage unavailable."
            )
        return await _finish_turn(turn, response, state)
    except TimeoutError:
        return AnalysisQueryResponse(
            answer="The archive could not be verified within this turn's deadline.",
            citations=[],
            degraded=True,
            data_version=release.version if release else "unreleased",
        )
    finally:
        if turn:
            await turn.abort()
