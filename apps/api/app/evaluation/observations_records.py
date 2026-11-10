"""Typed records read out of one recorded response: its receipts and its traces.

The evidence registry is the backend-generated list of receipts and calculation
expansions a turn was built from. The retrieval trace is what the ranking stages
selected. Both are read here as data, entry by entry, so a malformed entry becomes an
explicit problem instead of an inference — nothing in this module treats a stored row
as proof of a persistent commit, and nothing here decides what a record means for a
case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_HEX = re.compile(r"^[0-9a-f]{64}$")


class ObservationError(ValueError):
    """A response record cannot be interpreted without guessing."""


@dataclass(frozen=True)
class EvidenceRecord:
    """One backend-issued receipt from the response's own evidence registry."""

    evidence_id: str
    release_id: str
    text: str
    game_id: int | None
    source_row_id: int | str | None
    sequence_id: int | None
    source_evidence_ids: tuple[str, ...]
    row_sha256: str | None
    payload_sha256: str | None
    calculation_version: str | None
    sample_size: int | None
    denominator: float | None
    numerator: float | None
    value_decimals: int | None
    made: float | None
    attempted: float | None
    source_row: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    event_window: dict[str, Any] | None = None
    event_rows: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceRecord:
        evidence_id = str(value.get("evidence_id") or "")
        if not evidence_id:
            raise ObservationError("evidence registry entry has no evidence_id")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ObservationError("evidence registry metadata is not an object")
        source_ids = metadata.get("source_evidence_ids") or []
        if not isinstance(source_ids, list):
            raise ObservationError("source_evidence_ids is not a list")
        source_row = value.get("source_row")
        if source_row is not None and not isinstance(source_row, dict):
            raise ObservationError("evidence source_row is not an object")
        payload = value.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise ObservationError("evidence payload is not an object")
        decimals = _optional_number(metadata.get("value_decimals"))
        ingredients = metadata.get("ingredients") or {}
        if not isinstance(ingredients, dict):
            raise ObservationError("evidence ingredients is not an object")
        return cls(
            evidence_id=evidence_id,
            release_id=str(value.get("release_id") or ""),
            text=str(value.get("text") or ""),
            game_id=value.get("game_id"),
            source_row_id=value.get("source_row_id"),
            sequence_id=value.get("sequence_id"),
            source_evidence_ids=tuple(str(item) for item in source_ids),
            # The candidate emits the digest beside its snapshot, outside the
            # model-facing metadata; older recordings kept it inside metadata.
            row_sha256=_optional_digest(value.get("row_sha256") or metadata.get("row_sha256")),
            payload_sha256=_optional_digest(
                value.get("payload_sha256") or metadata.get("payload_sha256")
            ),
            calculation_version=(
                str(metadata["calculation_version"])
                if metadata.get("calculation_version")
                else None
            ),
            sample_size=(
                int(metadata["sample_size"]) if metadata.get("sample_size") is not None else None
            ),
            denominator=_optional_number(metadata.get("denominator")),
            numerator=_optional_number(metadata.get("numerator")),
            value_decimals=None if decimals is None else int(decimals),
            made=_optional_number(ingredients.get("made")),
            attempted=_optional_number(ingredients.get("attempted")),
            source_row=source_row,
            payload=payload,
            event_window=(
                metadata.get("event_window")
                if isinstance(metadata.get("event_window"), dict)
                else None
            ),
            event_rows=tuple(row for row in metadata.get("rows", []) if isinstance(row, dict))
            if isinstance(metadata.get("rows"), list)
            else (),
        )


def _optional_digest(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if _HEX.match(text) else None


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def evidence_registry(
    response: dict[str, Any],
) -> tuple[dict[str, EvidenceRecord], tuple[str, ...]]:
    """Read the response's own evidence registry; malformed entries are explicit problems."""
    raw = response.get("evidence")
    if raw in (None, []):
        return {}, ()
    if not isinstance(raw, list):
        return {}, ("malformed_evidence_registry",)
    records: dict[str, EvidenceRecord] = {}
    problems: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            problems.append("malformed_evidence_registry")
            continue
        try:
            record = EvidenceRecord.from_dict(item)
        except (ObservationError, TypeError, ValueError) as exc:
            problems.append(f"malformed_evidence_registry:{type(exc).__name__}")
            continue
        records.setdefault(record.evidence_id, record)
    return records, tuple(problems)


@dataclass(frozen=True)
class RankedEntry:
    evidence_id: str
    collection: str
    game_id: int | None
    player_ids: tuple[int, ...]
    team_ids: tuple[str, ...]
    source_row_id: int | str | None
    sequence_id: str | None
    score: float
    rank: int
    document_id: str | None = None
    point_id: str | None = None
    payload_sha256: str | None = None

    @classmethod
    def from_trace(cls, value: dict[str, Any]) -> RankedEntry:
        sequence_id = value.get("sequence_id")
        if sequence_id is not None and not isinstance(sequence_id, str):
            raise ObservationError("ranked sequence_id must be an opaque string")
        return cls(
            evidence_id=str(value["evidence_id"]),
            collection=str(value["collection"]),
            game_id=value.get("game_id"),
            player_ids=tuple(int(item) for item in value.get("player_ids") or []),
            team_ids=tuple(str(item) for item in value.get("team_ids") or []),
            source_row_id=value.get("source_row_id"),
            sequence_id=sequence_id,
            score=float(value.get("score") or 0.0),
            rank=int(value["rank"]),
            document_id=value.get("document_id"),
            point_id=value.get("point_id"),
            payload_sha256=value.get("payload_sha256"),
        )


@dataclass(frozen=True)
class TraceEntry:
    request_id: str
    data_version: str
    errors: tuple[str, ...]
    lexical: tuple[RankedEntry, ...]
    dense: tuple[RankedEntry, ...]
    candidates: tuple[RankedEntry, ...]
    selected: tuple[RankedEntry, ...]
    candidate_limit: int | None
    candidate_limit_applied: bool
    latency_ms: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TraceEntry:
        if not value.get("request_id"):
            raise ObservationError("trace has no request id")
        if not value.get("data_version"):
            raise ObservationError("trace has no data version")
        return cls(
            request_id=str(value["request_id"]),
            data_version=str(value["data_version"]),
            errors=tuple(str(item) for item in value.get("errors") or []),
            lexical=_ranked(value.get("lexical")),
            dense=_ranked(value.get("dense")),
            candidates=_ranked(value.get("candidates")),
            selected=_ranked(value.get("selected")),
            candidate_limit=value.get("candidate_limit"),
            candidate_limit_applied=bool(value.get("candidate_limit_applied")),
            latency_ms=int(value.get("latency_ms") or 0),
        )

    def rank_problems(self) -> list[str]:
        """Ranks must be 1..n inside each list, with no duplicate ids."""
        problems: list[str] = []
        for name in ("lexical", "dense", "candidates", "selected"):
            items = getattr(self, name)
            ranks = [item.rank for item in items]
            if ranks != list(range(1, len(items) + 1)):
                problems.append(f"trace_rank_invalid:{name}")
            ids = [item.evidence_id for item in items]
            if len(set(ids)) != len(ids):
                problems.append(f"trace_duplicate_evidence:{name}")
        return problems


def _ranked(value: Any) -> tuple[RankedEntry, ...]:
    """One trace stage as its entries, or the error its shape cannot be read past."""
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise ObservationError("trace stage is not a list")
    return tuple(RankedEntry.from_trace(item) for item in value)
