"""Evidence analyst turns and verified conversation session commits."""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import anyio
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analysis_policy as runtime
from app.api.analysis_models import AnalysisQueryRequest, AnalysisQueryResponse
from app.api.analysis_policy import _requires_evidence_refusal
from app.api.analysis_retrieval import _sample_shadow
from app.models.dataset_release import DatasetRelease
from app.services.canonical_narrative import measure_clarification
from app.services.narrative_scope import narrative_clarification
from app.services.query_parsing import is_live_only_score_request

if TYPE_CHECKING:
    from app.services.analyst_sessions import SessionTurn

logger = logging.getLogger(__name__)

_STATELESS_WARNING = "Stateless factual fallback: conversation storage unavailable."


async def _finish_turn(
    turn: SessionTurn | None, response: AnalysisQueryResponse, state: dict[str, Any]
) -> AnalysisQueryResponse:
    if turn is None:
        if _STATELESS_WARNING not in response.warnings:
            response.warnings.append(_STATELESS_WARNING)
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
        response.warnings.append("Conversation state could not be committed. Retry the same turn.")
    return response


async def _query_evidence_analyst(
    req: AnalysisQueryRequest,
    request: Request,
    db: AsyncSession,
    *,
    reference_context: list[dict[str, str]],
    immediate_response: AnalysisQueryResponse | None = None,
) -> AnalysisQueryResponse:
    from app.evaluation.trace_capture import record_turn
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
                    "context": reference_context,
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
        record_turn({"replayed": True, "model_calls": 0})
        return AnalysisQueryResponse.model_validate(turn.replay)
    try:
        if immediate_response is not None:
            # Policy and greeting turns participate in revision/replay handling without
            # changing the archive topic or spending a model call.
            record_turn(
                {
                    "answer_mode": runtime.get_settings().analysis_answer_mode,
                    "model_calls": 0,
                    "replayed": False,
                }
            )
            return await _finish_turn(turn, immediate_response, turn.state if turn else {})
        assert release is not None
        tools = AnalystTools(
            db,
            release,
            req.question,
            req.season,
            deepcopy(turn.state) if turn else {},
            context=reference_context,
        )
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
        clarification = None
        refusal = _requires_evidence_refusal(req.question)
        if not refusal:
            clarification = measure_clarification(req.question)
            if not clarification and tools.scope and tools.scope.requires_clarification:
                if tools.scope.clarification_reason in {
                    "missing_conversation_game",
                    "ambiguous_game",
                    "unverified_game_condition",
                }:
                    clarification = (
                        await narrative_clarification(
                            db, req.question, season=req.season, prior_questions=[]
                        )
                        or "Which archived game date should I use?"
                    )
                else:
                    clarification = "Which subject or game did you mean? " + "; ".join(
                        tools.scope.clarification_options
                    )
            elif not clarification and not tools.claims and not tools.narrative:
                # Committed, release-revalidated claims already scope an explanation.
                clarification = await narrative_clarification(
                    db,
                    req.question,
                    season=req.season,
                    prior_questions=[],
                    selected_game_ids=tools.scope.game_ids if tools.scope else None,
                )
        discovery = await tools.canonical_discovery() if not refusal else None
        discovery_failed = bool(discovery and discovery.status == "dependency_failure")
        if refusal or clarification:
            result = {
                "answer": clarification
                or (
                    "I don't have live game scores. "
                    "I can answer questions about archived Knicks games."
                    if is_live_only_score_request(req.question)
                    else "I don't have live, current, injury, trade, betting or future coverage. "
                    "I can answer questions about games in the 2025-26 Knicks archive."
                ),
                "follow_up_questions": [],
                "citations": [],
                "warnings": [discovery.message] if discovery_failed and discovery else [],
                "degraded": discovery_failed,
                "route": "clarification" if clarification else None,
                "refused": refusal,
                "data_version": release.version,
                "state": (turn.state.copy() if turn else {}) if refusal else tools.state.copy(),
                "tool_calls": [],
                "llm_validated": False,
            }
        else:
            if discovery_failed and discovery:
                # No model or recovery query may follow a failed database preflight.
                loop.results.append(discovery)
                loop.recovery_ran = True
                result = loop.render_fallback(discovery.message)
            else:
                result = await loop.run(
                    allow_model=bool(turn) and (answer_mode == "llm_primary" or shadow_sampled)
                )
        state = result.pop("state")
        record_turn(
            {
                "request_id": loop.request_id,
                "answer_mode": answer_mode,
                "sampled": shadow_sampled,
                "model_calls": loop.calls,
                "model_validated": result["llm_validated"],
                "replayed": False,
                "release": release.version,
                "committed_evidence_proposal": state,
            }
        )
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
                    "model": settings.ai_chat_model,
                },
            )
        # Shadow exercises the same reserved, validated path but delivers only backend facts.
        if answer_mode == "shadow" and result["llm_validated"]:
            result = loop.render_fallback("Shadow verification; deterministic delivery.")
            state = result.pop("state")
        record_turn({"delivered_mode": result["route"]})
        response = AnalysisQueryResponse(
            **result, request_id=getattr(request.state, "request_id", "")
        )
        response = await _finish_turn(turn, response, state)
        record_turn(
            {
                "state_committed": response.state_committed,
                "revision": response.revision,
                "delivered_state": state,
            }
        )
        return response
    except TimeoutError:
        record_turn({"error": "deadline_exceeded", "state_committed": False})
        return AnalysisQueryResponse(
            answer="The archive could not be verified within this turn's deadline.",
            citations=[],
            degraded=True,
            data_version=release.version if release else "unreleased",
        )
    finally:
        if turn:
            # A cancelled ASGI task still releases only its own conversation lease.
            # Paid accounting and uncertain reservations remain untouched.
            with anyio.move_on_after(1, shield=True):
                await turn.abort()
