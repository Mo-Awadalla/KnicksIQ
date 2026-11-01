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


async def _query_evidence_analyst(
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
        async with asyncio.timeout(
            max(
                0.001,
                runtime.get_settings().analyst_deadline_seconds - (time.monotonic() - started),
            )
        ):
            await tools.prepare()
        loop = AnalystLoop(tools, [m.model_dump() for m in req.context], started=started)
        loop.request_id = getattr(request.state, "request_id", "")
        settings = runtime.get_settings()
        answer_mode = settings.analysis_answer_mode
        verify_shadow = (
            answer_mode == "shadow"
            and bool(turn)
            and _sample_shadow(loop.request_id, settings.analysis_shadow_sample_rate)
        )
        # A shadow trial is verification, never the answer. The client's facts are computed
        # and committed first, so a blocked or failing provider cannot withhold them.
        result = await loop.run(allow_model=bool(turn) and answer_mode == "llm_primary")
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
            committed = await turn.commit(response.model_dump(mode="json"), state)
            if not committed:
                response.session_token = None
                response.session_expires_at = None
                response.revision = None
                response.state_committed = False
                response.degraded = True
                response.warnings.append(
                    "Conversation state could not be committed. Retry the same turn."
                )
        else:
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
        )
    finally:
        if turn:
            await turn.abort()
