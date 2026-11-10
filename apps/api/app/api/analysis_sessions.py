"""Evidence analyst turns and verified conversation session commits."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analysis_policy as runtime
from app.api.analysis_models import AnalysisQueryRequest, AnalysisQueryResponse
from app.api.analysis_retrieval import _sample_shadow
from app.api.analysis_shadow import _schedule_shadow_verification
from app.models.dataset_release import DatasetRelease
from app.services.fact_discovery import is_discovery
from app.services.query_classifier import classify_query


async def _query_evidence_analyst(
    req: AnalysisQueryRequest,
    request: Request,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    data_version: str,
) -> AnalysisQueryResponse:
    """Own the whole turn deadline without discarding known release authority."""
    try:
        async with asyncio.timeout(runtime.get_settings().analyst_deadline_seconds):
            return await _execute_evidence_turn(req, request, db, background_tasks)
    except TimeoutError:
        return AnalysisQueryResponse(
            answer="The archive could not be verified within this turn's deadline.",
            citations=[],
            degraded=True,
            data_version=data_version,
            session_status="retryable",
        )


async def _execute_evidence_turn(
    req: AnalysisQueryRequest,
    request: Request,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
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
    if release is None:
        return AnalysisQueryResponse(
            answer="No verified archive release is available.",
            citations=[],
            degraded=True,
            session_status="unavailable",
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
            detail: dict[str, object] = {"code": exc.reason}
            if exc.current_revision is not None:
                detail["current_revision"] = exc.current_revision
            raise HTTPException(status_code=409, detail=detail) from exc
        except SessionUnavailable:
            turn = None
    if turn and turn.replay is not None:
        return AnalysisQueryResponse.model_validate(turn.replay)
    tools = AnalystTools(db, release, req.question, req.season, turn.state if turn else {})
    try:
        if len(req.question.strip()) > runtime.get_settings().public_chat_max_prompt_chars:
            raise HTTPException(status_code=413, detail="Question is too long")
        async with asyncio.timeout(
            max(
                0.001,
                runtime.get_settings().analyst_deadline_seconds - (time.monotonic() - started),
            )
        ):
            await tools.prepare()
        scope = tools.scope
        assert scope is not None
        follow_up = bool(turn and req.session_token) or (
            runtime._looks_like_follow_up(req.question) and bool(req.context)
        )
        missing_data = runtime._unknown_data_question(req.question)
        outside_archive = not (
            runtime._is_supported_question(req.question)
            or is_discovery(req.question)
            or follow_up
            or scope.operation
            or scope.player_ids
            or scope.game_ids
            or scope.date_start
            or scope.date_end
            or scope.periods
            or scope.metric
            or scope.comparison
            or (
                scope.requires_clarification
                and (
                    scope.clarification_reason != "ambiguous_metric"
                    or classify_query(req.question).is_aggregative
                )
            )
        )
        if outside_archive and not missing_data:
            tools.scope = scope.model_copy(
                update={
                    "operation_reason": (
                        "I can only answer grounded questions about available Knicks "
                        "archive games and player statistics."
                    ),
                    "requires_clarification": False,
                }
            )
            tools.state["scope"] = tools.scope.model_dump(mode="json")
        loop = AnalystLoop(tools, [m.model_dump() for m in req.context], started=started)
        loop.request_id = getattr(request.state, "request_id", "")
        settings = runtime.get_settings()
        answer_mode = settings.analysis_answer_mode
        verify_shadow = (
            answer_mode == "shadow"
            and bool(turn)
            and not outside_archive
            and not missing_data
            and _sample_shadow(loop.request_id, settings.analysis_shadow_sample_rate)
        )
        # A shadow trial is verification, never the answer. The client's facts are computed
        # and committed first, so a blocked or failing provider cannot withhold them.
        if missing_data:
            from app.services.evidence_contracts import ProposedAnswer

            limitation = runtime._retrieval_limitation_note(req.question)
            text = "I can only answer from games available in this archive."
            if limitation:
                text += f" {limitation}"
            result = loop.render(ProposedAnswer(text=text), llm=False, degraded=False, delivered=[])
            if limitation:
                result["warnings"] = [limitation]
        else:
            result = await loop.run(
                allow_model=bool(turn) and answer_mode == "llm_primary" and not outside_archive
            )
        state = result.pop("state")
        response = AnalysisQueryResponse(
            **result, request_id=getattr(request.state, "request_id", "")
        )
        committed = False
        if turn:
            response.session_token = turn.token
            response.session_expires_at = datetime.now(UTC) + timedelta(seconds=86_400)
            response.revision = turn.revision + 1
            response.state_committed = True
            response.session_status = "committed"
            committed = await turn.commit(response.model_dump(mode="json"), state)
            if not committed:
                response.session_token = None
                response.session_expires_at = None
                response.revision = None
                response.state_committed = False
                response.session_status = "retryable"
                response.degraded = True
                response.warnings.append(
                    "Conversation state could not be committed. Retry the same turn."
                )
        else:
            response.session_status = "unavailable"
            response.warnings.append(
                "Stateless factual fallback: conversation storage unavailable."
            )
        if verify_shadow and committed:
            _schedule_shadow_verification(
                background_tasks,
                request_id=loop.request_id,
                question=req.question,
                season=req.season,
                data_version=release.version,
                state=state,
                context=[m.model_dump() for m in req.context],
            )
        return response
    except TimeoutError:
        return AnalysisQueryResponse(
            answer="The archive could not be verified within this turn's deadline.",
            citations=[],
            degraded=True,
            data_version=release.version,
            session_status="retryable" if turn else "unavailable",
        )
    finally:
        if turn:
            await turn.abort()
