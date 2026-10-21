"""Deterministic review checks: span coverage and numeric provenance.

The model reviewer judges meaning, subject and scope. Everything that can be checked
mechanically is checked here first, so a stochastic verdict cannot reject a correct number
or accept a number that exists in no backend record.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.analyst_provider import claim_view
from app.services.evidence_contracts import (
    Evidence,
    ProposedAnswer,
    VerifiedClaim,
    claim_value_issues,
)

# Number-like nouns and ordinals are labels, not quantities.
_LABELS = (
    re.compile(r"\b[1234]-point(?:er)?s?\b", re.IGNORECASE),
    re.compile(r"\b[1234](?:st|nd|rd|th)\b", re.IGNORECASE),
    re.compile(r"\bQ[1-4]\b", re.IGNORECASE),
)
# A minus sign only belongs to a number after a non-word character, so date and score
# ranges keep their parts ("2026-03-03", "112-98") and negatives keep their sign.
# Thousands separators are accepted only between digit groups, so "31," is 31.
_NUMBER = re.compile(r"(?<![\w.])(?:-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![\w.])")


@dataclass(frozen=True)
class NumberToken:
    raw: str
    value: Decimal
    decimals: int
    percent: bool

    @property
    def tolerance(self) -> Decimal:
        return Decimal(1).scaleb(-self.decimals) / 2 + Decimal("1e-9")


def number_tokens(text: str) -> list[NumberToken]:
    cleaned = text
    for pattern in _LABELS:
        cleaned = pattern.sub(" ", cleaned)
    tokens: list[NumberToken] = []
    for match in _NUMBER.finditer(cleaned):
        raw = match.group().replace(",", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        decimals = len(raw.partition(".")[2])
        following = cleaned[match.end() : match.end() + 2].lstrip()
        tokens.append(NumberToken(match.group(), value, decimals, following.startswith("%")))
    return tokens


def _add_numbers(values: set[Decimal], item: Any) -> None:
    if isinstance(item, bool):
        return
    if isinstance(item, (int, float)):
        values.add(Decimal(str(item)))
    elif isinstance(item, str):
        values.update(token.value for token in number_tokens(item))
    elif isinstance(item, Mapping):
        for value in item.values():
            _add_numbers(values, value)
    elif isinstance(item, Iterable) and not isinstance(item, (bytes, bytearray)):
        for value in item:
            _add_numbers(values, value)


_CLAIM_NUMBER_FIELDS = {
    "value",
    "unit",
    "statement",
    "population",
    "window",
    "sample_size",
    "denominator",
    "season",
    "season_type",
}


def _claim_numbers(claim: VerifiedClaim) -> set[Decimal]:
    values: set[Decimal] = set()
    view = claim_view(claim)
    _add_numbers(values, {key: value for key, value in view.items() if key in _CLAIM_NUMBER_FIELDS})
    _add_numbers(values, claim.filters)
    return values


def _evidence_numbers(item: Evidence) -> set[Decimal]:
    values: set[Decimal] = set()
    _add_numbers(values, item.text)
    # Hashes and identifiers contain digit runs that are not facts. Never whitelist them.
    metadata = {
        key: value
        for key, value in item.metadata.items()
        if not key.endswith(("_id", "_ids")) and key != "release_id"
    }
    _add_numbers(values, metadata)
    return values


def trusted_numbers(
    claims: Mapping[str, VerifiedClaim],
    evidence: Mapping[str, Evidence],
    capabilities: Mapping[str, Any] | None = None,
) -> set[Decimal]:
    values: set[Decimal] = set()
    for claim in claims.values():
        values.update(_claim_numbers(claim))
    for item in evidence.values():
        values.update(_evidence_numbers(item))
    if capabilities:
        # The manifest scope can contain game identifiers the writer never sees. Only bounds
        # and window counts are legitimate numbers the writer may restate.
        scope = capabilities.get("scope") or {}
        if isinstance(scope, Mapping):
            for key in ("date_start", "date_end", "relative_game_count", "periods"):
                _add_numbers(values, scope.get(key))
        for key in ("games", "box_score_rows", "seasons", "release_id", "team_metrics", "metrics"):
            _add_numbers(values, capabilities.get(key))
    return values


def _explained(token: NumberToken, exact: set[Decimal], claim_values: Iterable[Decimal]) -> bool:
    if token.value in exact:
        return True
    for value in claim_values:
        if abs(token.value - value) <= token.tolerance:
            return True
        # A percent sign over a ratio is a unit conversion of the same backend value.
        if token.percent and abs(token.value - value * 100) <= token.tolerance * 100:
            return True
    return False


# Decline, refusal and coverage phrasing may restate a threshold from the user's question
# ("games with 120+ points") without asserting it as a backend fact.
_COVERAGE = re.compile(
    r"\b(?:can(?:'|’)t|cannot|can not|do(?:es)?n(?:'|’)t|do not|does not|not able|unable|"
    r"no [\w ]*data|only|coverage|retrieved)\b",
    re.IGNORECASE,
)
# A month name marks a date window whose day numbers come from the question ("January 1
# through January 31"), not from a backend statistic.
_DATE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|october|november|"
    r"december)\b",
    re.IGNORECASE,
)
_CONVERSATIONAL = re.compile(
    r"\b(?:please|do you mean|which (?:player|team|game)|tell me|clarify|name the|"
    r"who do you mean|let me know)\b",
    re.IGNORECASE,
)


def numeric_issues(
    answer: ProposedAnswer,
    spans: list[str],
    claims: Mapping[str, VerifiedClaim],
    evidence: Mapping[str, Evidence],
    capabilities: Mapping[str, Any] | None = None,
    question: str = "",
) -> list[str]:
    exact = trusted_numbers(claims, evidence, capabilities)
    claim_values = [
        Decimal(str(claim.value))
        for claim in claims.values()
        if isinstance(claim.value, (int, float)) and not isinstance(claim.value, bool)
    ]
    question_numbers = {token.value for token in number_tokens(question)}
    issues: list[str] = []
    for index, span in enumerate(spans, start=1):
        criterion = bool(
            _COVERAGE.search(span)
            or _DATE.search(span)
            or _CONVERSATIONAL.search(span)
            or "?" in span
        )
        for token in number_tokens(span):
            if _explained(token, exact, claim_values):
                continue
            if criterion and token.value in question_numbers:
                continue
            issues.append(
                f"span {index} uses {token.raw}, which is not a supplied claim value, "
                "receipt or capability"
            )
    return issues


def review_issues(
    answer: ProposedAnswer,
    spans: list[str],
    claims: Mapping[str, VerifiedClaim],
    evidence: Mapping[str, Evidence],
    capabilities: Mapping[str, Any] | None = None,
    question: str = "",
) -> list[str]:
    issues = claim_value_issues(answer, dict(claims))
    if "".join(spans) != answer.text:
        issues.append("review spans do not reproduce the full answer")
    return issues + numeric_issues(answer, spans, claims, evidence, capabilities, question)
