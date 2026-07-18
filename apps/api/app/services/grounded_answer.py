"""Structured, internally validated LLM answers."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

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
    claim_type: Literal["narrative", "player_stat", "causal", "observational"] = "narrative"
    subject_id: int | str | None = None
    metric: str | None = None
    value: float | int | None = None
    game_ids: list[int] = Field(default_factory=list, max_length=82)
    filters: dict[str, Any] = Field(default_factory=dict)


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
    structured_evidence: dict[str, dict[str, Any]] | None = None,
    evidence_metadata: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Validate sentence coverage plus typed statistical and causal relationships."""
    structured_evidence = structured_evidence or {}
    evidence_metadata = evidence_metadata or {}

    def numbers(text: str) -> set[Decimal]:
        values: set[Decimal] = set()
        for raw in _NUMBER_RE.findall(text):
            try:
                values.add(Decimal(raw))
            except InvalidOperation:
                continue
        return values

    def parsed_structure(evidence_id: str) -> dict[str, Any]:
        if evidence_id in structured_evidence:
            return structured_evidence[evidence_id]
        try:
            value = json.loads(evidence[evidence_id])
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def contains_value(value: Any, expected: Any) -> bool:
        if isinstance(value, dict):
            return any(contains_value(child, expected) for child in value.values())
        if isinstance(value, list):
            return any(contains_value(child, expected) for child in value)
        if isinstance(expected, (int, float)) and isinstance(value, (int, float)):
            return Decimal(str(value)) == Decimal(str(expected))
        return str(value).lower() == str(expected).lower()

    def dictionary_nodes(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [
                value,
                *[node for child in value.values() for node in dictionary_nodes(child)],
            ]
        if isinstance(value, list):
            return [node for child in value for node in dictionary_nodes(child)]
        return []

    def relationship_matches(node: dict[str, Any], claim: GroundedClaim) -> bool:
        subject_matches = any(
            str(node.get(key)).lower() == str(claim.subject_id).lower()
            for key in ("subject_id", "player_id", "nba_person_id")
        )
        if not subject_matches:
            return False
        explicit_pair = str(node.get("metric")).lower() == str(
            claim.metric
        ).lower() and contains_value(node.get("value"), claim.value)
        direct_metric = claim.metric in node and contains_value(
            node.get(claim.metric),
            claim.value,
        )
        raw_values = node.get("raw_values")
        nested_metric = isinstance(raw_values, dict) and contains_value(
            raw_values.get(claim.metric),
            claim.value,
        )
        return explicit_pair or direct_metric or nested_metric

    def typed_stat_supported(claim: GroundedClaim) -> bool:
        if (
            claim.subject_id is None
            or claim.metric is None
            or claim.value is None
            or not claim.game_ids
        ):
            return False
        for evidence_id in claim.evidence_ids:
            structure = parsed_structure(evidence_id)
            if not structure:
                continue
            relationship_node = next(
                (node for node in dictionary_nodes(structure) if relationship_matches(node, claim)),
                None,
            )
            if relationship_node is None:
                continue
            if not all(contains_value(structure, game_id) for game_id in claim.game_ids):
                continue
            if not all(contains_value(structure, value) for value in claim.filters.values()):
                continue
            return True
        return False

    causal_terms = re.compile(
        r"\b(?:because|caused|led to|resulted in|reason|why|responsible for)\b",
        re.IGNORECASE,
    )

    for claim in candidate.claims:
        if any(evidence_id not in evidence for evidence_id in claim.evidence_ids):
            return False
        has_causal_language = bool(causal_terms.search(claim.text))
        if has_causal_language and claim.claim_type != "causal":
            return False
        if claim.claim_type == "causal":
            if not has_causal_language:
                return False
            if not any(
                evidence_metadata.get(evidence_id, {}).get("reviewed_report")
                or evidence_metadata.get(evidence_id, {}).get("connected_sequence")
                for evidence_id in claim.evidence_ids
            ):
                return False
        if claim.claim_type == "player_stat" and not typed_stat_supported(claim):
            return False

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", claim.text)
            if sentence.strip()
        ]
        for sentence in sentences:
            sentence_numbers = numbers(sentence)
            entities = {
                token
                for token in _ENTITY_RE.findall(sentence)
                if token not in _NON_ENTITY_SENTENCE_WORDS
            }
            if not any(
                sentence_numbers.issubset(numbers(evidence[evidence_id]))
                and all(entity.lower() in evidence[evidence_id].lower() for entity in entities)
                for evidence_id in claim.evidence_ids
            ):
                return False
    return True
