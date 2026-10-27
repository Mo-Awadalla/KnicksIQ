"""Deterministic admission replies, delivered through the analyst session lifecycle."""

from __future__ import annotations

from typing import Any

from app.api.analysis_models import AnalysisQueryResponse
from app.api.analysis_policy import _is_greeting, _requires_pre_model_refusal


def immediate_reply(
    question: str, response_metadata: dict[str, Any]
) -> AnalysisQueryResponse | None:
    if _is_greeting(question):
        return AnalysisQueryResponse(
            **response_metadata,
            route="greeting",
            answer=(
                "Hi. Ask me about an archived Knicks game, player stat, streak, "
                "opponent, or turning point."
            ),
            citations=[],
            tool_calls=[],
        )
    if _requires_pre_model_refusal(question):
        return refuse(response_metadata)
    return None


def refuse(response_metadata: dict[str, Any]) -> AnalysisQueryResponse:
    """Refuse categories no archive tool can answer, before any provider call."""
    return AnalysisQueryResponse(
        **response_metadata,
        refused=True,
        route=None,
        classifier={},
        evidence=[],
        warnings=["Question asks for betting, instruction-changing, or out-of-archive content."],
        answer=(
            "I can only answer grounded questions about the Knicks 2025-26 archive. "
            "I don't provide betting advice, medical or injury speculation, live or "
            "future updates, or change or reveal my instructions."
        ),
        citations=[],
        tool_calls=[],
    )
