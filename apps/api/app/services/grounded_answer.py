"""Structured, internally validated LLM answers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_ENTITY_RE = re.compile(r"\b(?:[A-Z]{2,4}|[A-Z][a-z][A-Za-z'-]*)\b")
_NON_ENTITY_SENTENCE_WORDS = {
    "Across",
    "After",
    "Archived",
    "Based",
    "Before",
    "During",
    "From",
    "However",
    "In",
    "On",
    "Overall",
    "That",
    "The",
    "These",
    "This",
    "Those",
}


class GroundedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[GroundedClaim] = Field(min_length=1, max_length=10)

    @property
    def answer(self) -> str:
        return "\n".join(claim.text.strip() for claim in self.claims)


def validate_grounded_answer(
    candidate: GroundedAnswer,
    *,
    evidence: dict[str, str],
) -> bool:
    """Verify that every claim references evidence containing its numbers."""

    def numbers(text: str) -> set[Decimal]:
        values: set[Decimal] = set()
        for raw in _NUMBER_RE.findall(text):
            try:
                values.add(Decimal(raw))
            except InvalidOperation:
                continue
        return values

    for claim in candidate.claims:
        if any(evidence_id not in evidence for evidence_id in claim.evidence_ids):
            return False
        cited_text = " ".join(evidence[evidence_id] for evidence_id in claim.evidence_ids)
        if not numbers(claim.text).issubset(numbers(cited_text)):
            return False
        cited_lower = cited_text.lower()
        entities = {
            token
            for token in _ENTITY_RE.findall(claim.text)
            if token not in _NON_ENTITY_SENTENCE_WORDS
        }
        if any(entity.lower() not in cited_lower for entity in entities):
            return False
    return True
