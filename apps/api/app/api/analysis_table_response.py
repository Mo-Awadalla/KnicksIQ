"""Aggregate game facts, citations, and grounded table answers."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analysis_generation import _generate_grounded_answer
from app.api.analysis_models import AnalysisCitation, AnalysisQueryRequest, AnalysisQueryResponse
from app.api.analysis_presenters import _format_answer, _table_evidence_note
from app.api.analysis_retrieval import _schedule_shadow
from app.services.archive_retrieval import (
    ArchiveEvidence,
)
from app.services.query_classifier import QueryClassifierResult
from app.services.retrieval_planner import (
    deterministic_retrieval_plan,
)
from app.services.table_rag import answer_table_question


async def answer_table_query(
    req: AnalysisQueryRequest,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    settings: Any,
    question: str,
    effective_question: str,
    response_metadata: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    classifier: QueryClassifierResult,
    classifier_payload: dict[str, Any],
    route: str,
    answer_mode: str,
    archive_vector_evidence: list[ArchiveEvidence],
) -> AnalysisQueryResponse:
    t0 = time.perf_counter()
    table_result = await answer_table_question(db, effective_question, season=req.season)
    tool_calls.append(
        {
            "tool": "table_rag",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(table_result.evidence),
        }
    )
    citations = [
        AnalysisCitation(
            claim=table_result.answer,
            type="game",
            title=f"{item['date']} NYK vs {item['opponent']}",
            game_id=item["game_id"],
            source_name=item.get("source_name"),
            source_url=item.get("source_url"),
            metadata={
                "season_type": item["season_type"],
                "data_status": item["data_status"],
                "score": item["score"],
            },
        )
        for item in table_result.evidence[:5]
    ]
    table_grounding_evidence = {
        "fact:table": " ".join([table_result.answer, *table_result.warnings]).strip(),
        **{item.evidence_id: item.text for item in archive_vector_evidence if item.text},
        **{
            f"game:{item['game_id']}": json.dumps(item, sort_keys=True)
            for item in table_result.evidence[:5]
        },
    }
    generated_answer = None
    if (
        getattr(settings, "analysis_answer_mode", "deterministic") == "llm_primary"
        and not response_metadata["degraded"]
        and not getattr(settings, "rag_conditional_generation_enabled", False)
    ):
        llm_t0 = time.perf_counter()
        generated_answer = await _generate_grounded_answer(
            question=question,
            season=req.season,
            chat_context=req.context,
            evidence=table_grounding_evidence,
            evidence_metadata={
                item.evidence_id: {
                    "reviewed_report": item.collection == "reports",
                    "connected_sequence": item.collection == "possessions",
                }
                for item in archive_vector_evidence
            },
        )
        if generated_answer:
            tool_calls.append(
                {
                    "tool": "llm_generate",
                    "estimated_cost_usd": 0.01,
                    "model": settings.ai_chat_model,
                    "latency_ms": int((time.perf_counter() - llm_t0) * 1000),
                }
            )
    elif answer_mode == "shadow":
        _schedule_shadow(
            background_tasks,
            settings=settings,
            request_id=response_metadata["request_id"],
            question=effective_question,
            season=req.season,
            data_version=response_metadata["data_version"],
            fallback_plan=deterministic_retrieval_plan(
                effective_question,
                intent=classifier.kind,
                is_aggregative=True,
            ),
            evidence=table_grounding_evidence,
        )
    table_metadata = {
        **response_metadata,
        "degraded": response_metadata["degraded"]
        or (
            getattr(settings, "analysis_answer_mode", "deterministic") == "llm_primary"
            and generated_answer is None
        ),
    }
    response = AnalysisQueryResponse(
        **table_metadata,
        answer=generated_answer
        or _format_answer(
            direct_answer=table_result.answer,
            evidence_note=_table_evidence_note(table_result.evidence),
            limitation_note=" ".join(table_result.warnings) if table_result.warnings else None,
        ),
        route=route,
        classifier=classifier_payload,
        evidence=table_result.evidence,
        warnings=table_result.warnings,
        citations=citations,
        tool_calls=tool_calls,
    )
    return response
