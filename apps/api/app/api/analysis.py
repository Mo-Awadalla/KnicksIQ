"""Public analyst query orchestration and HTTP endpoint."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analysis_policy as runtime
from app.api.analysis_models import (
    AnalysisCitation,
    AnalysisContextMessage,
    AnalysisQueryRequest,
    AnalysisQueryResponse,
    AnswerQueryContext,
)
from app.api.analysis_narrative_response import answer_narrative_query
from app.api.analysis_player_response import answer_player_query
from app.api.analysis_policy import (
    _client_id as _client_id,
)
from app.api.analysis_policy import (
    _contextual_question,
    _is_supported_question,
    _looks_like_follow_up,
    _rate_limit,
    _requires_explicit_refusal,
    _retrieval_limitation_note,
    _unknown_data_question,
)
from app.api.analysis_policy import (
    _requests_by_client as _requests_by_client,
)
from app.api.analysis_presenters import _format_answer
from app.api.analysis_refusals import immediate_reply
from app.api.analysis_retrieval import (
    _active_data_version,
    _execute_archive_retrieval,
    _matching_games,
    _schedule_shadow,
)
from app.api.analysis_retrieval import (
    _apply_resolved_filters as _apply_resolved_filters,
)
from app.api.analysis_retrieval import (
    _sample_shadow as _sample_shadow,
)
from app.api.analysis_sessions import _query_evidence_analyst
from app.api.analysis_table_response import answer_table_query
from app.core.db import get_db
from app.services.archive_retrieval import (
    ArchiveEvidence,
)
from app.services.conversation_memory import bounded_history
from app.services.conversation_state import (
    ConversationState,
    resolve_conversation_delta,
    state_from_resolved,
)
from app.services.fact_discovery import discover_fact, is_discovery
from app.services.llm_planner import maybe_plan_query
from app.services.narrative_scope import narrative_clarification
from app.services.query_classifier import classify_query
from app.services.query_resolution import ResolvedQuery, resolve_query
from app.services.retrieval_planner import (
    RetrievalPlan,
    deterministic_retrieval_plan,
    maybe_plan_retrieval,
)
from app.services.runtime_store import (
    answer_cache_key,
    get_cached_answer,
    set_cached_answer,
)
from app.services.team_aliases import team_ids_in_text

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/query", response_model=AnalysisQueryResponse)
async def query_analysis(
    req: AnalysisQueryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AnalysisQueryResponse:
    settings = runtime.get_settings()
    req.context = [
        AnalysisContextMessage.model_validate(item) for item in bounded_history(req.context)
    ]
    redis_degraded = await _rate_limit(request)
    response_metadata = {
        "request_id": getattr(request.state, "request_id", ""),
        "data_version": await _active_data_version(db),
        "degraded": redis_degraded,
    }
    question = req.question.strip()
    if len(question) > settings.public_chat_max_prompt_chars:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Question is too long",
        )
    immediate_response = immediate_reply(question, response_metadata)
    if getattr(settings, "analyst_evidence_loop_enabled", False):
        try:
            async with asyncio.timeout(settings.analyst_deadline_seconds):
                return await _query_evidence_analyst(
                    req, request, db, immediate_response=immediate_response
                )
        except TimeoutError:
            return AnalysisQueryResponse(
                answer="The archive could not be verified within this turn's deadline.",
                citations=[],
                degraded=True,
            )
    if immediate_response is not None:
        return immediate_response
    structured_conversation_enabled = getattr(
        settings,
        "rag_structured_conversation_state_enabled",
        False,
    )
    context_question = (
        question if structured_conversation_enabled else _contextual_question(question, req.context)
    )
    if _requires_explicit_refusal(question):
        return AnalysisQueryResponse(
            **response_metadata,
            refused=True,
            route=None,
            classifier={},
            evidence=[],
            warnings=[
                "Question asks outside the available Knicks season data or live/current coverage."
            ],
            answer=(
                "I don't have live injury, trade, current-game, or future updates. "
                "I can help with the Knicks games in the 2025-26 archive."
            ),
            citations=[],
            tool_calls=[],
        )
    if is_discovery(question):
        discovery = await discover_fact(
            db,
            question=question,
            season=req.season,
            prior=req.conversation_state,
            context=[item.model_dump() for item in req.context],
        )
        return AnalysisQueryResponse(
            **response_metadata,
            answer=discovery.answer,
            route=discovery.route,
            conversation_state=discovery.state,
            citations=[AnalysisCitation.model_validate(item) for item in discovery.citations],
            tool_calls=[{"tool": "discover_fact", "result_count": len(discovery.citations)}],
        )
    resolved_query: ResolvedQuery | None = None
    if getattr(settings, "rag_query_resolution_v2_enabled", False) or (
        structured_conversation_enabled
    ):
        initial_classifier = classify_query(question)
        resolved_query = await resolve_query(
            db,
            question,
            intent=initial_classifier.kind,
            data_version=str(response_metadata["data_version"]),
        )
        conversation_state: ConversationState | None = None
        if structured_conversation_enabled:
            prior_state = req.conversation_state
            if prior_state is None:
                prior_user = next(
                    (
                        item.content
                        for item in reversed(req.context)
                        if item.role == "user" and item.content.strip()
                    ),
                    None,
                )
                if prior_user:
                    prior_resolved = await resolve_query(
                        db,
                        prior_user,
                        intent=classify_query(prior_user).kind,
                        data_version=str(response_metadata["data_version"]),
                    )
                    prior_state = state_from_resolved(prior_resolved)
            resolved_query, conversation_state = resolve_conversation_delta(
                question,
                resolved_query,
                prior_state,
            )
        if resolved_query.requires_clarification:
            choices = "; ".join(resolved_query.clarification_options)
            return AnalysisQueryResponse(
                **response_metadata,
                route="clarification",
                classifier=initial_classifier.as_dict(),
                resolved_query=resolved_query.model_dump(mode="json"),
                conversation_state=conversation_state,
                warnings=[resolved_query.clarification_reason or "ambiguous_reference"],
                answer=(
                    "Short answer\n"
                    "I found more than one valid match. Which one did you mean?"
                    + (f"\n\nOptions\n{choices}" if choices else "")
                ),
                citations=[],
                tool_calls=[
                    {
                        "tool": "query_resolution",
                        "result_count": len(resolved_query.clarification_options),
                    }
                ],
            )
        response_metadata = {
            **response_metadata,
            "resolved_query": resolved_query.model_dump(mode="json"),
            "conversation_state": conversation_state,
        }
    reference_clarification = await narrative_clarification(
        db,
        question,
        season=req.season,
        prior_questions=[item.content for item in req.context if item.role == "user"],
        references_only=True,
        selected_game_ids=(req.conversation_state.game_ids if req.conversation_state else None),
    )
    if reference_clarification:
        return AnalysisQueryResponse(
            **response_metadata,
            answer=_format_answer(direct_answer=reference_clarification),
            route="clarification",
            citations=[],
            warnings=[],
            tool_calls=[],
        )
    player_response = await answer_player_query(
        req,
        db,
        background_tasks,
        settings=settings,
        question=question,
        context_question=context_question,
        structured_conversation_enabled=structured_conversation_enabled,
        resolved_query=resolved_query,
        response_metadata=response_metadata,
    )
    if player_response is not None:
        return player_response
    clarification = await narrative_clarification(
        db,
        question,
        season=req.season,
        prior_questions=[item.content for item in req.context if item.role == "user"],
        selected_game_ids=(req.conversation_state.game_ids if req.conversation_state else None),
    )
    if clarification:
        return AnalysisQueryResponse(
            **response_metadata,
            answer=_format_answer(direct_answer=clarification),
            route="clarification",
            citations=[],
            warnings=[],
            tool_calls=[],
        )
    selected_narrative_game = None
    if "best defensive game" in question.lower():
        defensive_games = await _matching_games(db, question, req.season)
        if len(defensive_games) == 1:
            selected_narrative_game = defensive_games[0]
            question = f"{question} on {selected_narrative_game.game_date}"
    answer_mode = getattr(settings, "analysis_answer_mode", "deterministic")
    preplanned_retrieval_plan: RetrievalPlan | None = None
    preplan_latency_ms = 0
    resolved_supported = bool(
        resolved_query
        and (
            resolved_query.player_ids
            or resolved_query.team_ids
            or resolved_query.game_ids
            or resolved_query.date_start
            or resolved_query.date_end
            or resolved_query.relative_game_count
            or resolved_query.periods
            or resolved_query.metric
            or team_ids_in_text(question)
        )
    )
    current_supported = _is_supported_question(question) or resolved_supported
    contextual_follow_up_supported = _looks_like_follow_up(question) and _is_supported_question(
        context_question
    )
    if (
        not current_supported
        and not contextual_follow_up_supported
        and answer_mode == "llm_primary"
    ):
        scope_classifier = classify_query(context_question)
        unsupported_fallback = deterministic_retrieval_plan(
            context_question,
            intent=scope_classifier.kind,
            is_aggregative=scope_classifier.is_aggregative,
        ).model_copy(update={"supported": False})
        preplan_t0 = time.perf_counter()
        preplanned_retrieval_plan = await maybe_plan_retrieval(
            context_question,
            fallback=unsupported_fallback,
        )
        preplan_latency_ms = int((time.perf_counter() - preplan_t0) * 1000)
        current_supported = preplanned_retrieval_plan.supported
    if not current_supported and not contextual_follow_up_supported:
        response = AnalysisQueryResponse(
            **response_metadata,
            refused=True,
            route=None,
            classifier={},
            evidence=[],
            warnings=[
                "Question asks outside the available Knicks season data or live/current coverage."
            ],
            answer=(
                "Short answer\n"
                "I can only answer grounded questions about available Knicks 2025-26 "
                "regular-season or playoff games. I do not have live, current, "
                "future, injury, trade, or non-Knicks coverage."
            ),
            citations=[],
            tool_calls=[],
        )
        return response
    effective_question = context_question if contextual_follow_up_supported else question

    cache_key = None
    if not req.context or structured_conversation_enabled:
        state_cache_suffix = (
            req.conversation_state.model_dump_json()
            if structured_conversation_enabled and req.conversation_state
            else ""
        )
        cache_key = answer_cache_key(
            f"{question}\nstate:{state_cache_suffix}",
            response_metadata["data_version"],
            getattr(settings, "ai_chat_model", "deterministic"),
            season=req.season,
            answer_mode=getattr(settings, "analysis_answer_mode", "deterministic"),
            prompt_version=getattr(settings, "analysis_prompt_version", "v1"),
            index_version=response_metadata["data_version"],
        )
        cached = await get_cached_answer(cache_key)
        if cached and not cached.get("degraded", False):
            if answer_mode == "shadow":
                cached_classifier = classify_query(question)
                _schedule_shadow(
                    background_tasks,
                    settings=settings,
                    request_id=response_metadata["request_id"],
                    question=question,
                    season=req.season,
                    data_version=response_metadata["data_version"],
                    fallback_plan=deterministic_retrieval_plan(
                        question,
                        intent=cached_classifier.kind,
                        is_aggregative=cached_classifier.is_aggregative,
                    ),
                    evidence={"fact:cached": str(cached.get("answer") or "")},
                )
            cached["request_id"] = response_metadata["request_id"]
            cached["degraded"] = bool(cached.get("degraded")) or response_metadata["degraded"]
            return AnalysisQueryResponse.model_validate(cached)

    tool_calls: list[dict[str, Any]] = []
    classifier = classify_query(effective_question)
    classifier_payload = classifier.as_dict()
    route = "table_rag" if classifier.is_aggregative else "retrieval_rag"
    retrieval_plan: RetrievalPlan | None = None
    archive_vector_evidence: list[ArchiveEvidence] = []
    t0 = time.perf_counter()
    named_opponent_ids = team_ids_in_text(effective_question) - {"NYK"}
    planner = (
        None
        if named_opponent_ids or selected_narrative_game or answer_mode in {"llm_primary", "shadow"}
        else await maybe_plan_query(effective_question, classifier)
    )
    if planner:
        tool_calls.append(
            {
                "tool": "llm_planner",
                "estimated_cost_usd": 0.002,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "result_count": 1,
            }
        )
        route = planner.route
        classifier_payload.update(planner.as_dict())
    if answer_mode == "llm_primary":
        if preplanned_retrieval_plan is not None:
            retrieval_plan = preplanned_retrieval_plan
            plan_latency_ms = preplan_latency_ms
        else:
            plan_t0 = time.perf_counter()
            fallback_plan = deterministic_retrieval_plan(
                effective_question,
                intent=classifier.kind,
                is_aggregative=classifier.is_aggregative,
            )
            retrieval_plan = (
                fallback_plan
                if getattr(settings, "rag_conditional_generation_enabled", False)
                else await maybe_plan_retrieval(
                    effective_question,
                    fallback=fallback_plan,
                )
            )
            plan_latency_ms = int((time.perf_counter() - plan_t0) * 1000)
        retrieval_plan = _apply_resolved_filters(retrieval_plan, resolved_query)
        if selected_narrative_game is not None:
            retrieval_plan = retrieval_plan.model_copy(
                update={
                    "filters": retrieval_plan.filters.model_copy(
                        update={
                            "game_ids": [selected_narrative_game.id],
                            "dates": [str(selected_narrative_game.game_date)],
                        }
                    ),
                }
            )
        plan_call = {
            "tool": (
                "deterministic_retrieval_plan"
                if getattr(settings, "rag_conditional_generation_enabled", False)
                else "retrieval_plan"
            ),
            "latency_ms": plan_latency_ms,
            "result_count": len(retrieval_plan.queries),
            "intent": retrieval_plan.intent,
            "collection_count": len(retrieval_plan.collections),
        }
        if plan_call["tool"] == "retrieval_plan":
            plan_call["estimated_cost_usd"] = 0.002
        tool_calls.append(plan_call)
        archive_vector_evidence, vector_call, vector_degraded = await _execute_archive_retrieval(
            retrieval_plan,
            db=db,
            data_version=response_metadata["data_version"],
            settings=settings,
        )
        tool_calls.append(vector_call)
        response_metadata = {
            **response_metadata,
            "degraded": response_metadata["degraded"] or vector_degraded,
        }
    if _unknown_data_question(question):
        limitation = _retrieval_limitation_note(question)
        response = AnalysisQueryResponse(
            **response_metadata,
            answer=_format_answer(
                direct_answer=(
                    "I can only answer from the games currently in KnicksIQ, and that "
                    "question does not identify an available game."
                ),
                limitation_note=limitation,
            ),
            route=route,
            classifier=classifier_payload,
            evidence=[],
            warnings=[limitation] if limitation else [],
            citations=[],
            tool_calls=tool_calls,
        )
        if cache_key and not response.degraded:
            await set_cached_answer(cache_key, response.model_dump(mode="json"))
        return response

    response_args = AnswerQueryContext(
        settings=settings,
        question=question,
        effective_question=effective_question,
        response_metadata=response_metadata,
        tool_calls=tool_calls,
        classifier=classifier,
        classifier_payload=classifier_payload,
        route=route,
        answer_mode=answer_mode,
        archive_vector_evidence=archive_vector_evidence,
    )
    if route == "table_rag":
        response = await answer_table_query(req, db, background_tasks, **response_args)
    else:
        response = await answer_narrative_query(
            req,
            db,
            background_tasks,
            selected_narrative_game=selected_narrative_game,
            **response_args,
        )
    if cache_key and not response.degraded:
        await set_cached_answer(cache_key, response.model_dump(mode="json"))
    return response
