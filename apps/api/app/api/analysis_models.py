"""HTTP contracts and calendar validation for analyst queries."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings, get_settings
from app.schemas.analytics import AnalyticsPayload
from app.services.archive_evidence import ArchiveEvidence
from app.services.conversation_state import (
    ConversationState,
)
from app.services.query_classifier import QueryClassifierResult


class AnswerQueryContext(TypedDict):
    """Resolved request inputs shared by table and narrative response builders."""

    settings: Settings
    question: str
    effective_question: str
    response_metadata: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    classifier: QueryClassifierResult
    classifier_payload: dict[str, Any]
    route: str
    answer_mode: str
    archive_vector_evidence: list[ArchiveEvidence]


def _validate_calendar_dates(value: str) -> str:
    for candidate in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", value):
        try:
            date.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("Use valid calendar dates in YYYY-MM-DD format") from exc
    return value


class AnalysisContextMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)

    _validate_dates = field_validator("content")(_validate_calendar_dates)


class AnalysisQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1200)
    season: str = "2025-26"
    context: list[AnalysisContextMessage] = Field(default_factory=list, max_length=100)
    conversation_state: ConversationState | None = None
    session_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    turn_id: str | None = Field(
        default=None, min_length=16, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    expected_revision: int = Field(default=0, ge=0)

    _validate_dates = field_validator("question")(_validate_calendar_dates)

    @field_validator("question")
    @classmethod
    def _validate_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value


class AnalysisCitation(BaseModel):
    claim: str
    type: str
    title: str
    game_id: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisQueryResponse(BaseModel):
    answer: str
    follow_up_questions: list[str] = Field(default_factory=list, max_length=2)
    route: str | None = Field(default=None, exclude=get_settings().is_production)
    classifier: dict[str, Any] = Field(default_factory=dict, exclude=get_settings().is_production)
    evidence: list[dict[str, Any]] = Field(
        default_factory=list, exclude=get_settings().is_production
    )
    warnings: list[str] = Field(default_factory=list)
    citations: list[AnalysisCitation]
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list, exclude=get_settings().is_production
    )
    refused: bool = False
    degraded: bool = False
    data_version: str = "unreleased"
    request_id: str = ""
    analytics: AnalyticsPayload | None = None
    resolved_query: dict[str, Any] = Field(
        default_factory=dict,
        exclude=get_settings().is_production,
    )
    conversation_state: ConversationState | None = None
    session_token: str | None = None
    session_expires_at: datetime | None = None
    revision: int | None = None
    state_committed: bool = False
    llm_validated: bool = False
