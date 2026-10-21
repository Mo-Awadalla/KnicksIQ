"""Deterministic public refusal payloads shared by the analyst endpoint."""

from __future__ import annotations

from app.api.analysis_models import AnalysisQueryResponse


def refuse(response_metadata: dict[str, object]) -> AnalysisQueryResponse:
    """Refuse categories no archive tool can answer, before any provider call."""
    return AnalysisQueryResponse(
        **response_metadata,
        refused=True,
        route=None,
        classifier={},
        evidence=[],
        warnings=[
            "Question asks for betting, medical, live, future, or instruction-changing "
            "content outside the archive."
        ],
        answer=(
            "I can only answer grounded questions about the Knicks 2025-26 archive. "
            "I don't provide betting advice, medical or injury speculation, live or "
            "future updates, or change or reveal my instructions."
        ),
        citations=[],
        tool_calls=[],
    )
