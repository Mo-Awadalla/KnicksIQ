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

from app.services.analyst_payload import claim_view
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
    # Offsets in the text passed to number_tokens; label blanks keep offsets stable.
    start: int = 0
    end: int = 0

    @property
    def tolerance(self) -> Decimal:
        return Decimal(1).scaleb(-self.decimals) / 2 + Decimal("1e-9")


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group())


def number_tokens(text: str) -> list[NumberToken]:
    cleaned = text
    for pattern in _LABELS:
        cleaned = pattern.sub(_blank, cleaned)
    tokens: list[NumberToken] = []
    for match in _NUMBER.finditer(cleaned):
        raw = match.group().replace(",", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            continue
        decimals = len(raw.partition(".")[2])
        following = cleaned[match.end() : match.end() + 2].lstrip()
        tokens.append(
            NumberToken(
                match.group(),
                value,
                decimals,
                following.startswith("%"),
                match.start(),
                match.end(),
            )
        )
    return tokens


# Unit words the gate understands. A token written next to one of these is matched
# against sources carrying the same unit, so a coincidental trusted value of another
# metric cannot explain it.
_UNIT_WORDS = {
    "point": "points",
    "points": "points",
    "game": "games",
    "games": "games",
    "win": "wins",
    "wins": "wins",
    "loss": "losses",
    "losses": "losses",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "assist": "assists",
    "assists": "assists",
}
_UNIT_BRIDGES = (
    "active",
    "archived",
    "home",
    "playoff",
    "playoffs",
    "regular",
    r"regular\-season",
    "road",
    "season",
    "total",
)
_UNIT_AFTER = re.compile(
    r"^\s*(?:-\s*)?(?:(?:" + "|".join(_UNIT_BRIDGES) + r")\s+)?([A-Za-z]+)",
    re.IGNORECASE,
)
_UNIT_BEFORE = re.compile(r"\b([A-Za-z]+)\s*[:=]\s*$", re.IGNORECASE)
_PER = re.compile(r"\bper\s+$", re.IGNORECASE)


def token_unit(text: str, token: NumberToken) -> str | None:
    """The unit word the token is written next to, if any.

    Only immediate phrasing counts: one bridge adjective ("archived games"),
    a hyphen ("54-point"), or a unit label before a colon ("wins: 69"). Wider
    windows pick up the unit of a neighbouring number. The tail of a hyphenated
    compound ("2025-26", "112-98") is part of that number, not a quantity the
    following word labels.
    """
    if token.start and text[token.start - 1] == "-":
        return None
    after = _UNIT_AFTER.match(text[token.end :])
    if after:
        unit = _UNIT_WORDS.get(after.group(1).lower())
        if unit:
            return unit
    before = _UNIT_BEFORE.search(text[: token.start])
    if before:
        unit = _UNIT_WORDS.get(before.group(1).lower())
        if unit and not _PER.search(text[: before.start(1)]):
            return unit
    return None


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


@dataclass(frozen=True)
class _Source:
    value: Decimal
    unit: str | None = None
    percent: bool = False


_PERCENT_UNIT = re.compile(r"\b(?:pct|percent|percentage)\b", re.IGNORECASE)
_WORDS = re.compile(r"[a-z]+")


def _unit_family(unit: str | None) -> str | None:
    if not unit:
        return None
    words = _WORDS.findall(unit.lower())
    if not words:
        return None
    head = words[0]
    if head in _UNIT_WORDS:
        return _UNIT_WORDS[head]
    if head in {"margin", "net", "score"}:
        return "points"
    if head in {"appearance", "appearances"}:
        return "games"
    if "margin" in words or "net" in words or "score" in words:
        return "points"
    if "game" in words or "games" in words:
        return "games"
    return None


def _compatible(unit: str, source_unit: str | None) -> bool:
    family = _unit_family(source_unit)
    if family is None:
        return False
    if family == unit:
        return True
    # A win or a loss is one game, and "lost 32 games" is a losses value.
    return unit == "games" and family in {"wins", "losses"}


def _key_unit(key: str) -> str | None:
    words = _WORDS.findall(key.lower())
    for word in words:
        family = _UNIT_WORDS.get(word)
        if family:
            return family
    if "margin" in words or "net" in words or "score" in words:
        return "points"
    return None


def _value_sources(value: Any, sources: list[_Source], unit: str | None = None) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        sources.append(_Source(Decimal(str(value)), unit))
    elif isinstance(value, str):
        for token in number_tokens(value):
            sources.append(_Source(token.value, token_unit(value, token) or unit, token.percent))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _value_sources(item, sources, unit or _key_unit(str(key)))
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _value_sources(item, sources, unit)


def _claim_sources(claim: VerifiedClaim, sources: list[_Source]) -> None:
    view = claim_view(claim)
    for key, value in view.items():
        if key not in _CLAIM_NUMBER_FIELDS:
            continue
        if key == "value" and isinstance(value, (int, float)) and not isinstance(value, bool):
            number = Decimal(str(value))
            sources.append(_Source(number, claim.unit))
            # A ratio claim is the same backend value as its percentage; a percent unit
            # already carries percentage display units.
            if 0 < abs(number) < 1:
                sources.append(_Source(number * 100, claim.unit, True))
            if claim.unit and _PERCENT_UNIT.search(claim.unit):
                sources.append(_Source(number, claim.unit, True))
        elif key == "value" and isinstance(value, str):
            # A composite value such as a final score is stated in the claim's unit.
            _value_sources(value, sources, claim.unit)
        else:
            _value_sources(value, sources)
    sample = view.get("sample_size")
    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        # A claim's sample is a count of games (team) or appearances (player).
        sources.append(_Source(Decimal(str(sample)), "games"))
    _value_sources(claim.filters, sources)


def _metadata_sources(item: Evidence, sources: list[_Source]) -> None:
    # Hashes and identifiers contain digit runs that are not facts.
    metadata = {
        key: value
        for key, value in item.metadata.items()
        if not key.endswith(("_id", "_ids")) and key != "release_id"
    }
    _value_sources(metadata, sources)


def _number_sources(
    claims: Mapping[str, VerifiedClaim],
    evidence: Mapping[str, Evidence],
    capabilities: Mapping[str, Any] | None = None,
) -> list[_Source]:
    sources: list[_Source] = []
    for claim in claims.values():
        _claim_sources(claim, sources)
    for item in evidence.values():
        _value_sources(item.text, sources)
        _metadata_sources(item, sources)
    if capabilities:
        scope = capabilities.get("scope") or {}
        if isinstance(scope, Mapping):
            for key in ("date_start", "date_end", "periods"):
                _value_sources(scope.get(key), sources)
            _value_sources(scope.get("relative_game_count"), sources, "games")
        for key in ("seasons", "release_id", "team_metrics", "metrics"):
            _value_sources(capabilities.get(key), sources)
        for key in ("games", "box_score_rows"):
            _value_sources(capabilities.get(key), sources, "games")
    return sources


def _explained(token: NumberToken, unit: str | None, sources: Iterable[_Source]) -> bool:
    for source in sources:
        if source.percent != token.percent:
            continue
        if abs(token.value - source.value) > token.tolerance:
            continue
        # A percent is a unit conversion of a source value, or a value the source writes
        # with a percent sign; a bare count of another unit is not a percentage.
        if token.percent or unit is None or _compatible(unit, source.unit):
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
    sources = _number_sources(claims, evidence, capabilities)
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
            if _explained(token, token_unit(span, token), sources):
                continue
            if criterion and token.value in question_numbers:
                continue
            issues.append(
                f"span {index} uses {token.raw}, which is not a supplied claim value, "
                "receipt or capability"
            )
    return issues


# A sentence-ending period may follow; a decimal or a date part may not.
_RECORD = re.compile(r"(?<![\w.-])(\d{1,3})-(\d{1,3})(?![\w-]|\.\d)")


# A number pair is a W-L record only when the sentence says so: "went 4-1", "a 4-1 record".
# Shooting lines ("shot 1-4 from three"), scores, runs and stretches use the same shape.
_RECORD_BEFORE = re.compile(
    r"\b(?:went|go|going|finished|finish|stood|record(?: of| was| is| at)?)\s+$", re.IGNORECASE
)
_RECORD_AFTER = re.compile(r"^\s*(?:record|mark)\b", re.IGNORECASE)
_NOT_RECORD_AFTER = re.compile(
    r"^\s*(?:from|shooting|on (?:field|three|free)|run|stretch|lead|deficit)\b", re.IGNORECASE
)


def _is_record_context(before: str, after: str) -> bool:
    if _NOT_RECORD_AFTER.search(after):
        return False
    return bool(_RECORD_BEFORE.search(before) or _RECORD_AFTER.search(after))


def record_order_issues(spans: list[str], claims: Mapping[str, VerifiedClaim]) -> list[str]:
    """A W-L record written in reverse. Both numbers are trusted values, so the value check
    passes; only the pairing of a wins claim with a losses claim over the same games shows
    which number comes first."""
    by_games: dict[tuple, dict[str, Decimal]] = {}
    for claim in claims.values():
        if claim.metric_id in {"wins", "losses"} and isinstance(claim.value, (int, float)):
            key = (claim.subject_id, tuple(sorted(claim.game_ids or [])))
            by_games.setdefault(key, {})[claim.metric_id] = Decimal(str(claim.value))
    pairs = {(p["wins"], p["losses"]) for p in by_games.values() if {"wins", "losses"} <= set(p)}
    issues: list[str] = []
    for index, span in enumerate(spans, start=1):
        for match in _RECORD.finditer(span):
            if not _is_record_context(span[: match.start()], span[match.end() :]):
                continue
            shown = (Decimal(match.group(1)), Decimal(match.group(2)))
            if shown not in pairs and shown[::-1] in pairs and shown[0] != shown[1]:
                issues.append(
                    f"span {index} states the record {match.group()} with wins and losses reversed"
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
    return (
        issues
        + numeric_issues(answer, spans, claims, evidence, capabilities, question)
        + record_order_issues(spans, claims)
    )
