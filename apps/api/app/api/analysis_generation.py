"""Grounded model generation and validation against archive evidence."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.api import analysis_policy as runtime
from app.api.analysis_models import AnalysisContextMessage
from app.api.analysis_presenters import _analysis_context
from app.models.game import Game
from app.services.grounded_answer import GroundedAnswer, validate_grounded_answer
from app.services.query_classifier import QueryClassifierResult
from app.services.rag import SearchResult
from app.services.report_llm import get_llm_adapter
from app.services.runtime_store import (
    reserve_ai_budget,
)

logger = logging.getLogger(__name__)


def _llm_enabled() -> bool:
    settings = runtime.get_settings()
    if getattr(settings, "test_mode", False):
        return False
    if settings.ai_provider.lower() in {"mock", "none", "disabled"} or not settings.ai_api_key:
        return False
    allowed_models = getattr(settings, "openrouter_allowed_models", [])
    return not allowed_models or (settings.ai_chat_model in allowed_models)


async def _generate_llm_answer(
    *,
    question: str,
    season: str,
    games: list[Game],
    docs: list[SearchResult],
    evidence: list[dict[str, Any]] | None = None,
    classifier: QueryClassifierResult | None = None,
    chat_context: list[AnalysisContextMessage] | None = None,
    computed_facts: dict[str, Any] | None = None,
) -> str | None:
    if not _llm_enabled():
        return None
    if not await reserve_ai_budget():
        return None

    system = (
        "You are KnicksIQ, a grounded Knicks analyst. Answer only from the provided "
        "available Knicks game, document, and computed-fact context. Treat computed facts "
        "as authoritative. Do not use live, current, injury, trade, "
        "standings, or outside knowledge. If the context is insufficient, say so. "
        "If the classifier is counterfactual, provide a historical baseline and a "
        "clearly labeled hypothetical adjustment, not a full simulation. "
        "Do not use backend terms like RAG, vector search, embeddings, chunks, Qdrant, "
        "lexical retrieval, seeded data, or cached. Answer directly in one or two "
        "sentences by default; explain more when the user asks for depth. "
        "Mention concrete dates, opponents, scores, "
        "runs, stretches, or play-by-play details when present."
    )
    user = json.dumps(
        _analysis_context(
            question=question,
            season=season,
            games=games,
            docs=docs,
            evidence=evidence,
            classifier=classifier,
            chat_context=chat_context,
            computed_facts=computed_facts,
        )
    )
    try:
        answer = await get_llm_adapter(response_format_json=False).generate(
            system=system, user=user
        )
        canonical_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", user))
        answer_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", answer))
        if not answer_numbers.issubset(canonical_numbers):
            return None
        ignored_phrases = {"short answer", "key evidence"}
        named_entities = {
            match.group(0).lower()
            for match in re.finditer(r"\b[A-Z][a-z'-]+ [A-Z][a-z'-]+\b", answer)
        } - ignored_phrases
        if any(entity not in user.lower() for entity in named_entities):
            return None
        return answer
    except Exception:  # noqa: B110
        return None


async def _generate_grounded_answer(
    *,
    question: str,
    season: str,
    evidence: dict[str, str],
    chat_context: list[AnalysisContextMessage] | None = None,
    structured_evidence: dict[str, dict[str, Any]] | None = None,
    evidence_metadata: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    if not _llm_enabled() or not evidence:
        return None
    if not await reserve_ai_budget():
        return None
    system = (
        "You are KnicksIQ, a grounded Knicks analyst. Return compact JSON containing "
        "an array named claims. Every claim must contain text and one or more "
        "evidence_ids. Write only evidence-linked claims supported by the provided "
        "archive evidence. Treat computed facts as authoritative. Never use outside, "
        "live, current, injury, trade, or future knowledge. Answer briefly by default "
        "and explain more when requested. "
        "Do not mention backend systems, retrieval, validation, or evidence IDs."
    )
    if getattr(runtime.get_settings(), "rag_typed_grounding_enabled", False):
        system += (
            " For every statistical sentence use claim_type=player_stat and include "
            "subject_id, metric, value, game_ids, and filters. Use claim_type=causal "
            "for causal language; causal claims require a reviewed report or explicitly "
            "connected event sequence. Otherwise use observational wording."
        )
    max_evidence_chars = max(
        1024,
        int(getattr(runtime.get_settings(), "rag_generation_max_input_tokens", 4000)) * 4 - 2000,
    )
    compact_evidence: dict[str, str] = {}
    used_chars = 0
    for evidence_id, text in evidence.items():
        remaining = max_evidence_chars - used_chars
        if remaining <= 0:
            break
        compact = text[: min(1200, remaining)]
        compact_evidence[evidence_id] = compact
        used_chars += len(compact)
    payload = {
        "question": question,
        "season": season,
        "context": [
            {"role": item.role, "content": item.content}
            for item in (chat_context or [])[-10:]
            if item.role in {"user", "assistant"}
        ],
        "evidence": compact_evidence,
    }
    try:
        raw = await get_llm_adapter(response_format_json=True).generate(
            system=system,
            user=json.dumps(payload, separators=(",", ":")),
        )
        candidate = GroundedAnswer.model_validate_json(raw)
        if not validate_grounded_answer(
            candidate,
            evidence=evidence,
            structured_evidence=structured_evidence,
            evidence_metadata=evidence_metadata,
        ):
            logger.warning("grounded_answer_rejected", extra={"reason": "claim_validation"})
            return None
        return candidate.answer
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "grounded_answer_failed",
            extra={"error_type": type(exc).__name__},
        )
        return None
