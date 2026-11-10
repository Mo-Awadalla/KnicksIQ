"""Grounded model generation and validation against archive evidence."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.api import analysis_policy as runtime
from app.api.analysis_models import AnalysisContextMessage
from app.services.grounded_answer import GroundedAnswer, validate_grounded_answer
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
