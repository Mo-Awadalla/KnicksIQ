"""Archive selection, hybrid retrieval, and background shadow evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analysis_policy as runtime
from app.api.analysis_generation import _generate_grounded_answer
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.services.archive_retrieval import (
    ArchiveEvidence,
    fuse_archive_evidence,
    search_archive_lexical,
    search_archive_vectors,
)
from app.services.query_resolution import ResolvedQuery
from app.services.releases import restrict_to_active_release
from app.services.retrieval_planner import (
    RetrievalPlan,
    RetrievalPlanFilters,
    maybe_plan_retrieval,
)
from app.services.team_scope import scope_games, scores

logger = logging.getLogger(__name__)


async def _matching_games(db: AsyncSession, question: str, season: str) -> list[Game]:
    stmt = (
        select(Game)
        .where(Game.season == season)
        .where((Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"))
        .order_by(Game.game_date.desc())
    )
    stmt = restrict_to_active_release(stmt)
    games = (await db.execute(stmt)).scalars().all()
    selected = scope_games(question, list(games))
    q = question.lower()
    if "closest" in q and selected:
        minimum = min(abs(scores(game)[0] - scores(game)[1]) for game in selected)
        selected = [game for game in selected if abs(scores(game)[0] - scores(game)[1]) == minimum]
    elif "best defensive game" in q and selected:
        minimum = min(scores(game)[1] for game in selected)
        selected = [game for game in selected if scores(game)[1] == minimum]
    if re.search(r"\b(?:the|boston|toronto|atlanta|chicago|charlotte) loss\b", q):
        selected = [game for game in selected if scores(game)[0] < scores(game)[1]]
    return selected


async def _active_data_version(db: AsyncSession) -> str:
    version = (
        await db.execute(select(DatasetRelease.version).where(DatasetRelease.status == "active"))
    ).scalar_one_or_none()
    return version or (
        "test-seed" if getattr(runtime.get_settings(), "test_mode", False) else "unreleased"
    )


async def _execute_archive_retrieval(
    plan: RetrievalPlan,
    *,
    db: AsyncSession | None = None,
    data_version: str,
    settings: Any,
) -> tuple[list[ArchiveEvidence], dict[str, Any], bool]:
    started = time.perf_counter()
    base_call = {
        "tool": "archive_vector_search",
        "mode": "hybrid",
        "collection_count": len(plan.collections),
    }
    lexical: list[ArchiveEvidence] = []
    dense: list[ArchiveEvidence] = []
    errors: list[str] = []
    true_hybrid = getattr(settings, "rag_true_hybrid_enabled", False)
    if db is not None and true_hybrid:
        try:
            lexical = await search_archive_lexical(
                db,
                query=" ".join(plan.queries),
                collections=list(plan.collections),
                filters=plan.filters.model_dump(mode="json"),
                data_version=data_version,
                limit=getattr(settings, "rag_lexical_candidate_limit", 30),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "archive_lexical_search_failed",
                extra={"error_type": type(exc).__name__},
            )
            errors.append("lexical")
    if getattr(settings, "rag_qdrant_enabled", False):
        try:
            dense = await asyncio.to_thread(
                search_archive_vectors,
                queries=plan.queries,
                collections=list(plan.collections),
                filters=plan.filters.model_dump(mode="json"),
                data_version=data_version,
                limit=getattr(settings, "rag_dense_candidate_limit", 30),
                candidate_limit=getattr(settings, "rag_dense_candidate_limit", 30),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "archive_vector_search_failed",
                extra={"error_type": type(exc).__name__},
            )
            errors.append("dense")
    else:
        errors.append("dense")
    if not true_hybrid:
        return (
            dense[: getattr(settings, "rag_retrieval_limit", 5)],
            {
                **base_call,
                "mode": "dense",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "result_count": len(dense),
                "lexical_candidate_count": 0,
                "dense_candidate_count": len(dense),
                "errors": errors,
            },
            "dense" in errors,
        )
    evidence = fuse_archive_evidence(
        lexical,
        dense,
        limit=getattr(settings, "rag_final_evidence_limit", 5),
        max_per_game=(
            (
                None
                if len(plan.filters.game_ids) == 1
                else getattr(settings, "rag_multi_game_max_evidence_per_game", 2)
            )
            if getattr(settings, "rag_result_diversity_enabled", False)
            else None
        ),
        filters=plan.filters.model_dump(mode="json"),
        weighted=getattr(settings, "rag_weighted_fusion_enabled", False),
    )
    return (
        evidence,
        {
            **base_call,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "result_count": len(evidence),
            "lexical_candidate_count": len(lexical),
            "dense_candidate_count": len(dense),
            "errors": errors,
        },
        len(errors) == 2,
    )


def _sample_shadow(request_id: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    digest = hashlib.sha256(request_id.encode()).digest()
    bucket = int.from_bytes(digest[:4], "big") / (2**32 - 1)
    return bucket < rate


async def _run_shadow_candidate(
    *,
    request_id: str,
    question: str,
    season: str,
    data_version: str,
    fallback_plan: RetrievalPlan,
    evidence: dict[str, str],
) -> None:
    """Best-effort shadow evaluation; never retain prompt or evidence content."""
    started = time.perf_counter()
    settings = runtime.get_settings()
    try:
        plan = await maybe_plan_retrieval(question, fallback=fallback_plan)
        vectors, _call, vector_degraded = await _execute_archive_retrieval(
            plan,
            data_version=data_version,
            settings=settings,
        )
        if vector_degraded:
            logger.info(
                "analysis_shadow_candidate",
                extra={
                    "request_id": request_id,
                    "outcome": "vector_unavailable",
                    "intent": plan.intent,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "data_version": data_version,
                },
            )
            return
        candidate = await _generate_grounded_answer(
            question=question,
            season=season,
            evidence={
                **evidence,
                **{item.evidence_id: item.text for item in vectors if item.text},
            },
        )
        logger.info(
            "analysis_shadow_candidate",
            extra={
                "request_id": request_id,
                "outcome": "validated" if candidate else "rejected",
                "intent": plan.intent,
                "retrieval_count": len(vectors),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "data_version": data_version,
                "model": getattr(settings, "ai_chat_model", "disabled"),
                "prompt_version": getattr(settings, "analysis_prompt_version", "v1"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "analysis_shadow_failed",
            extra={
                "request_id": request_id,
                "error_type": type(exc).__name__,
            },
        )


def _schedule_shadow(
    background_tasks: BackgroundTasks,
    *,
    settings: Any,
    request_id: str,
    question: str,
    season: str,
    data_version: str,
    fallback_plan: RetrievalPlan,
    evidence: dict[str, str],
) -> None:
    if not _sample_shadow(
        request_id,
        float(getattr(settings, "analysis_shadow_sample_rate", 0.1)),
    ):
        return
    background_tasks.add_task(
        _run_shadow_candidate,
        request_id=request_id,
        question=question,
        season=season,
        data_version=data_version,
        fallback_plan=fallback_plan,
        evidence=evidence,
    )


def _apply_resolved_filters(
    plan: RetrievalPlan,
    resolved: ResolvedQuery | None,
) -> RetrievalPlan:
    if resolved is None:
        return plan
    return plan.model_copy(
        update={
            "filters": RetrievalPlanFilters.model_validate(resolved.planner_filters()),
        }
    )
