"""Prove one citation reference against the recorded mapping and its evidence registry.

A receipt resolves through the mapping's own identity — its runtime receipt, or the
release/collection/game/source row id it parses to — and never through the text a
response happens to display. A calculation resolves further: its digest, its sources,
its recorded numerator and denominator and finally an independent recomputation of the
formula from the cited snapshots, which is the only thing that can credit it.

A calculation's content — its registry record, its release, its sources and the
snapshots those sources verify to — is a property of the reference, so it is computed
once per reference. Everything a claim asserts about that content (digest, denominator,
sample, arithmetic, recipe) is re-proved for every claim, so a second claim can never
inherit the first claim's proof.

Resolution is a function of the mapping, so it stays outside the mapping's data and
loaders; the mapping exposes it as ``resolve_citation`` and ``resolve_document``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.evaluation.arithmetic import ClaimView, prove, tolerance
from app.evaluation.mapping_identity import (
    CitationResolution,
    SourceRow,
    calculation,
    calculation_digest,
    parse_evidence_reference,
    unresolved,
)
from app.evaluation.observations import canonical_digest
from app.evaluation.observations_records import EvidenceRecord

if TYPE_CHECKING:
    from app.evaluation.mapping import RuntimeMapping

CALCULATION_PREFIX = "calculation:"


@dataclass(frozen=True)
class CalculationContent:
    """The claim-independent half of one calculation reference.

    ``release_mismatch``, ``expansion_missing`` and ``expansion_mismatch`` are the
    reference's own defects. ``sources_unverified`` and an incomplete ``snapshots``
    tuple mean the expansion cannot be proved, which blocks credit instead of failing.
    """

    record: EvidenceRecord
    sources: tuple[str, ...]
    rows: tuple[SourceRow | None, ...]
    snapshots: tuple[dict[str, Any], ...]
    collections: tuple[str, ...]
    release_mismatch: bool = False
    expansion_missing: bool = False
    expansion_mismatch: bool = False
    sources_unverified: bool = False


def calculation_content(
    mapping: RuntimeMapping, reference: str, registry: dict[str, EvidenceRecord]
) -> CalculationContent | None:
    """The reference's own content, or None when it is not a calculation the registry carries."""
    if not reference.startswith(CALCULATION_PREFIX):
        return None
    record = registry.get(reference)
    if record is None:
        return None
    sources = tuple(record.source_evidence_ids)
    rows = tuple(mapping.row_by_receipt.get(source) for source in sources)
    snapshots: list[dict[str, Any]] = []
    collections: list[str] = []
    expansion_mismatch = False
    for row, source in zip(rows, sources, strict=False):
        evidence = registry.get(source)
        if row is None or evidence is None:
            continue
        if evidence.row_sha256 is not None and evidence.row_sha256 != row.row_sha256:
            expansion_mismatch = True
            break
        if evidence.source_row is not None:
            if canonical_digest(evidence.source_row) != row.row_sha256:
                expansion_mismatch = True
                break
            snapshots.append(evidence.source_row)
            collections.append(row.collection)
    return CalculationContent(
        record=record,
        sources=sources,
        rows=rows,
        snapshots=tuple(snapshots),
        collections=tuple(collections),
        release_mismatch=record.release_id != mapping.version,
        expansion_missing=not sources,
        expansion_mismatch=expansion_mismatch,
        sources_unverified=any(row is None for row in rows),
    )


def resolve_citation(
    mapping: RuntimeMapping,
    reference: str,
    claim: dict[str, Any] | None,
    registry: dict[str, EvidenceRecord] | None = None,
    content: CalculationContent | None = None,
) -> CitationResolution:
    """Resolve one reference from a response's citation list."""
    if not reference:
        return unresolved(reference, "citation_empty_reference")
    if reference.startswith(CALCULATION_PREFIX):
        return _resolve_calculation(mapping, reference, claim or {}, registry or {}, content)
    return _resolve_receipt(mapping, reference)


def resolve_document(mapping: RuntimeMapping, possession_id: str) -> CitationResolution:
    """Resolve one possession document by the release-scoped id it was stored under."""
    reference = f"{mapping.version}:{possession_id}"
    document = mapping.documents.get(reference)
    if document is None:
        return unresolved(reference, "citation_document_not_in_mapping")
    canonical_game = mapping.canonical_for_game(document.game_id)
    if canonical_game is None:
        return unresolved(reference, "citation_unmapped_game")
    return CitationResolution(
        reference, "document", (canonical_game,), (reference,), "document_payload_sha256"
    )


def _resolve_receipt(mapping: RuntimeMapping, reference: str) -> CitationResolution:
    row = mapping.row_by_receipt.get(reference)
    if row is not None:
        return CitationResolution(reference, "receipt", (row.canonical_id,), (reference,))
    parsed = parse_evidence_reference(reference)
    if parsed is None:
        return unresolved(reference, "citation_unmapped_receipt")
    release, collection, game_reference, source_id = parsed
    if release != mapping.version:
        return unresolved(reference, "citation_foreign_release")
    if collection == "games":
        canonical = mapping.canonical_for_game(game_reference)
        if canonical:
            return CitationResolution(reference, "receipt", (canonical,), (reference,))
        return unresolved(reference, "citation_unmapped_game")
    expected_collection = {
        "box_scores": "player_game_stats",
        "team_box": "team_game_stats",
        "period": "period_scores",
    }.get(collection)
    if expected_collection is None:
        return unresolved(reference, "citation_unmapped_collection")
    source_row = mapping.row_by_database_id.get(source_id)
    if source_row is None:
        return unresolved(reference, "citation_unmapped_receipt")
    if source_row.collection != expected_collection:
        return unresolved(reference, "citation_collection_mismatch")
    if mapping.canonical_for_game(source_row.game_id) != mapping.canonical_for_game(game_reference):
        return unresolved(reference, "citation_game_mismatch")
    return CitationResolution(reference, "receipt", (source_row.canonical_id,), (reference,))


def _resolve_calculation(
    mapping: RuntimeMapping,
    reference: str,
    claim: dict[str, Any],
    registry: dict[str, EvidenceRecord],
    content: CalculationContent | None = None,
) -> CitationResolution:
    body = reference[len(CALCULATION_PREFIX) :]
    if content is None:
        content = calculation_content(mapping, reference, registry)
        if content is None:
            return unresolved(reference, "calculation_evidence_missing")
    record = content.record
    subject = claim.get("subject_id")
    metric = claim.get("metric_id")
    value = claim.get("value")
    if not subject or not metric or value is None:
        return unresolved(reference, "citation_calculation_claim_incomplete")
    problems: list[str] = []
    unverified: list[str] = []
    if content.release_mismatch:
        problems.append("calculation_release_mismatch")
    sources = list(content.sources)
    if content.expansion_missing:
        problems.append("calculation_expansion_missing")
    elif calculation_digest(mapping.version, subject, metric, sources, value) != body:
        problems.append("calculation_receipt_mismatch")
    claim_denominator = claim.get("denominator")
    if claim_denominator is not None and record.denominator != float(claim_denominator):
        problems.append("calculation_denominator_mismatch")
    claim_sample = claim.get("sample_size")
    if claim_sample is not None and record.sample_size != int(claim_sample):
        problems.append("calculation_sample_mismatch")
    slack = tolerance(record.value_decimals)
    if record.numerator is not None and record.denominator and _number(value):
        # The recorded numerator must reproduce the delivered value through its
        # own denominator, never as value * denominator.
        if abs(record.numerator / record.denominator - float(value)) > slack:
            problems.append("calculation_arithmetic_mismatch")
    if record.made is not None and record.attempted and _number(value):
        if abs(100.0 * record.made / record.attempted - float(value)) > slack:
            problems.append("calculation_arithmetic_mismatch")
    rows = list(content.rows)
    if content.sources_unverified:
        unverified.append("calculation_sources_unverified")
    snapshots = list(content.snapshots)
    collections = list(content.collections)
    if content.expansion_mismatch:
        problems.append("calculation_expansion_mismatch")
    recipe = None
    population_cited = False
    if sources and len(snapshots) == len(sources):
        # Recompute from the verified rows: a numerator/value pair that agrees
        # only with itself cannot pass, and an unknown recipe is never credited.
        proof = prove(
            claim_view(mapping, claim, subject, metric, value, record),
            rows=snapshots,
            collections=collections,
            player=player_canonical_id(subject, mapping.player_canonical_ids),
            population=mapping.population,
        )
        recipe = proof.recipe
        population_cited = proof.population_cited
        problems.extend(proof.problems)
        if proof.status == "unverifiable":
            unverified.append(proof.reason or "unsupported_recipe")
    elif sources and "calculation_expansion_mismatch" not in problems:
        unverified.append("calculation_content_unverified")
    problems = list(dict.fromkeys(problems))
    if problems:
        return calculation(
            reference, sources=tuple(sources), problems=tuple(problems), recipe=recipe
        )
    if unverified:
        return calculation(reference, sources=tuple(sources), unverified=tuple(unverified))
    canonical = tuple(dict.fromkeys(row.canonical_id for row in rows if row is not None))
    source_games = {mapping.canonical_for_game(row.game_id) for row in rows if row is not None}
    claim_games = {mapping.canonical_for_game(game) for game in claim.get("game_ids") or []}
    if not population_cited and claim_games and source_games != claim_games:
        return calculation(reference, canonical, tuple(sources), ("calculation_scope_mismatch",))
    return calculation(reference, canonical, tuple(sources), recipe=recipe)


def claim_view(
    mapping: RuntimeMapping,
    claim: dict[str, Any],
    subject: str,
    metric: str,
    value: Any,
    record: EvidenceRecord,
) -> ClaimView:
    """The claim's own attribution, beside the receipt record's measured ingredients."""
    eligibility = claim.get("eligibility")
    window = claim.get("window")
    return ClaimView(
        metric=str(metric),
        value=value,
        subject=str(subject),
        game_ids=tuple(int(game) for game in claim.get("game_ids") or [] if _is_int(game)),
        window=window if isinstance(window, dict) else None,
        eligibility=dict(eligibility) if isinstance(eligibility, dict) else {},
        baseline_claim_ids=tuple(str(item) for item in claim.get("baseline_claim_ids") or []),
        sample_size=record.sample_size,
        denominator=record.denominator,
        decimals=record.value_decimals,
        numerator=record.numerator,
        made=record.made,
        attempted=record.attempted,
        player_name=player_display_name(subject, mapping.player_names),
    )


def player_canonical_id(subject: str, player_canonical_ids: dict[int, str]) -> str | None:
    """The mapped canonical player id for a ``player:<runtime id>`` subject."""
    runtime_id = _runtime_player(subject)
    return None if runtime_id is None else player_canonical_ids.get(runtime_id)


def player_display_name(subject: str, player_names: dict[int, str]) -> str | None:
    """The mapped name of a ``player:<runtime id>`` subject, when the mapping has it."""
    runtime_id = _runtime_player(subject)
    return None if runtime_id is None else player_names.get(runtime_id)


def _runtime_player(subject: str) -> int | None:
    """The runtime player id a ``player:<id>`` subject names, or None when it is not one."""
    if not subject.startswith("player:"):
        return None
    try:
        return int(subject.split(":", 1)[1])
    except ValueError:
        return None


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
