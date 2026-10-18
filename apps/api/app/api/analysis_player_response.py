"""Typed player analytics responses and optional grounded synthesis."""

from __future__ import annotations

import time
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analysis_generation import _generate_grounded_answer
from app.api.analysis_models import AnalysisCitation, AnalysisQueryRequest, AnalysisQueryResponse
from app.api.analysis_retrieval import (
    _apply_resolved_filters,
    _execute_archive_retrieval,
    _schedule_shadow,
)
from app.schemas.analytics import AnalyticsPayload
from app.services.player_analytics import answer_player_question
from app.services.query_resolution import ResolvedQuery
from app.services.retrieval_planner import (
    RetrievalPlan,
    RetrievalPlanFilters,
    maybe_plan_retrieval,
)


async def answer_player_query(
    req: AnalysisQueryRequest,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    settings: Any,
    question: str,
    context_question: str,
    structured_conversation_enabled: bool,
    resolved_query: ResolvedQuery | None,
    response_metadata: dict[str, Any],
) -> AnalysisQueryResponse | None:
    analytics_t0 = time.perf_counter()
    player_answer = await answer_player_question(
        db,
        question=question,
        season=req.season,
        context=(
            [] if structured_conversation_enabled else [item.model_dump() for item in req.context]
        ),
        resolved_player_ids=resolved_query.player_ids if resolved_query else None,
        resolved_game_ids=resolved_query.game_ids if resolved_query else None,
    )
    if player_answer is not None:
        analytics_payload = AnalyticsPayload.model_validate(player_answer.analytics)
        player_tool_calls: list[dict[str, Any]] = [
            {
                "tool": "player_analytics",
                "latency_ms": int((time.perf_counter() - analytics_t0) * 1000),
                "result_count": len(analytics_payload.results),
            }
        ]
        player_answer_text = player_answer.answer
        player_degraded = response_metadata["degraded"]
        player_mode = getattr(settings, "analysis_answer_mode", "deterministic")
        player_fallback_plan = RetrievalPlan(
            supported=True,
            intent="player_intelligence",
            queries=[context_question],
            collections=["games", "box_scores", "reports"],
            filters=RetrievalPlanFilters.model_validate(
                resolved_query.planner_filters() if resolved_query else {}
            ),
            fact_tools=["player_analytics"],
        )
        if player_mode == "llm_primary" and not getattr(
            settings,
            "rag_conditional_generation_enabled",
            False,
        ):
            plan_t0 = time.perf_counter()
            player_plan = await maybe_plan_retrieval(
                context_question,
                fallback=player_fallback_plan,
            )
            player_plan = _apply_resolved_filters(player_plan, resolved_query)
            player_tool_calls.append(
                {
                    "tool": "retrieval_plan",
                    "estimated_cost_usd": 0.002,
                    "latency_ms": int((time.perf_counter() - plan_t0) * 1000),
                    "result_count": len(player_plan.queries),
                    "intent": player_plan.intent,
                    "collection_count": len(player_plan.collections),
                }
            )
            player_vectors, vector_call, vector_degraded = await _execute_archive_retrieval(
                player_plan,
                db=db,
                data_version=response_metadata["data_version"],
                settings=settings,
            )
            player_tool_calls.append(vector_call)
            player_degraded = player_degraded or vector_degraded
            grounded_player_answer = (
                None
                if player_degraded
                else await _generate_grounded_answer(
                    question=question,
                    season=req.season,
                    chat_context=req.context,
                    evidence={
                        "fact:player": analytics_payload.model_dump_json(),
                        **{item.evidence_id: item.text for item in player_vectors if item.text},
                    },
                    structured_evidence={
                        "fact:player": {
                            "claims": [
                                {
                                    **result.model_dump(mode="json"),
                                    "player_id": (
                                        resolved_query.player_ids[0]
                                        if resolved_query and len(resolved_query.player_ids) == 1
                                        else None
                                    ),
                                    "game_ids": result.source_game_ids,
                                }
                                for result in analytics_payload.results
                            ],
                        }
                    },
                    evidence_metadata={
                        item.evidence_id: {
                            "reviewed_report": item.collection == "reports",
                            "connected_sequence": (
                                item.collection == "possessions"
                                and bool(item.metadata.get("sequence_id"))
                            ),
                        }
                        for item in player_vectors
                    },
                )
            )
            if grounded_player_answer:
                player_answer_text = grounded_player_answer
                player_tool_calls.append(
                    {
                        "tool": "llm_generate",
                        "estimated_cost_usd": 0.01,
                        "model": settings.ai_chat_model,
                        "latency_ms": 0,
                    }
                )
            else:
                player_degraded = True
        elif player_mode == "shadow":
            _schedule_shadow(
                background_tasks,
                settings=settings,
                request_id=response_metadata["request_id"],
                question=context_question,
                season=req.season,
                data_version=response_metadata["data_version"],
                fallback_plan=player_fallback_plan,
                evidence={"fact:player": analytics_payload.model_dump_json()},
            )
        response = AnalysisQueryResponse(
            **{**response_metadata, "degraded": player_degraded},
            answer=player_answer_text,
            route="table_rag",
            classifier={"kind": "player_intelligence", "is_aggregative": True},
            evidence=[],
            warnings=player_answer.warnings,
            citations=[AnalysisCitation.model_validate(item) for item in player_answer.citations],
            tool_calls=player_tool_calls,
            analytics=analytics_payload,
        )
        return response
