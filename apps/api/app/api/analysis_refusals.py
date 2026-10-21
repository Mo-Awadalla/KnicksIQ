"""Deterministic public refusal payloads shared by the analyst endpoint."""

from __future__ import annotations

from typing import Any

from app.api.analysis_models import AnalysisQueryResponse


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
