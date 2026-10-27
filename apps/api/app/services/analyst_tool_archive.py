"""search_archive handler: retrieved examples, never a season denominator."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.evaluation.trace_capture import record_search
from app.services.archive_retrieval import fuse_archive_evidence, search_archive_vectors
from app.services.archive_units import accepts_unit, build_archive_units
from app.services.evidence_contracts import Evidence, ToolResult

if TYPE_CHECKING:
    from app.models.game import Game
    from app.services.analyst_tools import AnalystTools
    from app.services.evidence_contracts import ToolCall
    from app.services.query_resolution import ResolvedQuery


async def run(
    tools: AnalystTools,
    call: ToolCall,
    scope: ResolvedQuery | None,
    games: list[Game],
    *,
    unit_records: list[dict[str, Any]] | None = None,
    local_only: bool = False,
    purpose: str = "analyst_search",
) -> ToolResult:
    assert scope is not None
    if unit_records is None:
        unit_records = (
            await build_archive_units(tools.db, games, tools.release.version) if games else []
        )
    game_ids = {g.id for g in games}
    filters: dict[str, Any] = scope.planner_filters()
    filters["game_ids"] = [g.id for g in games]
    filters["unanchored_game_reference"] = scope.clarification_reason == "missing_conversation_game"
    lexical = (
        await tools.search_archive_lexical(
            tools.db,
            query=call.question,
            collections=["games", "box_scores", "reports", "possessions"],
            filters=filters,
            data_version=tools.release.version,
            limit=20,
            unit_records=unit_records,
        )
        if games
        else []
    )
    dense, failure = [], False
    if games and not local_only and get_settings().rag_qdrant_enabled:
        try:
            dense = await asyncio.to_thread(
                search_archive_vectors,
                queries=[call.question],
                collections=["games", "box_scores", "reports", "possessions"],
                filters=filters,
                data_version=tools.release.version,
                limit=20,
                candidate_limit=20,
            )
        except Exception:
            failure = True
    found = fuse_archive_evidence(lexical, dense, limit=20, filters=filters)
    evidence = [
        Evidence(
            evidence_id=f"{tools.release.version}:{e.evidence_id}",
            release_id=tools.release.version,
            text=e.text,
            game_id=e.metadata.get("game_id"),
            source_name=e.metadata.get("source_name"),
            source_url=e.metadata.get("source_url"),
            metadata={
                key: value
                for key, value in e.metadata.items()
                if key
                not in {
                    "retrieval_sources",
                    "fusion_components",
                    "component_ranks",
                    "exact_match_fields",
                    "_index_embedding",
                    "chunk_id",
                }
            },
        )
        for e in found
        if e.metadata.get("data_version") == tools.release.version
        and (
            e.metadata.get("game_id") in game_ids
            if not e.metadata.get("unit_type")
            else accepts_unit(
                e.metadata,
                unit_records=unit_records,
                selected_game_ids=game_ids,
                player_ids=scope.player_ids,
                periods=scope.periods,
                version=tools.release.version,
            )
            and e.text == e.metadata.get("text")
        )
    ]
    returned_ids = {e.evidence_id for e in evidence}
    record_search(
        {
            "purpose": purpose,
            "status": "ok",
            "release": tools.release.version,
            "question": tools.question if local_only else call.question,
            "query": call.question,
            "filters": filters,
            "lexical_evidence_ids": [f"{tools.release.version}:{e.evidence_id}" for e in lexical],
            "dense_evidence_ids": [f"{tools.release.version}:{e.evidence_id}" for e in dense],
            "candidate_evidence_ids": [e.evidence_id for e in evidence],
            "returned_evidence_ids": [e.evidence_id for e in evidence],
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "ranking": [
                {
                    "evidence_id": f"{tools.release.version}:{e.evidence_id}",
                    "score": e.score,
                    "retrieval_sources": e.metadata.get("retrieval_sources", []),
                    "fusion_components": e.metadata.get("fusion_components", []),
                    "component_ranks": e.metadata.get("component_ranks", {}),
                    "exact_match_fields": e.metadata.get("exact_match_fields", []),
                    "index_embedding": e.metadata.get("_index_embedding"),
                }
                for e in found
                if f"{tools.release.version}:{e.evidence_id}" in returned_ids
            ],
            "dense_failed": failure,
        }
    )
    return ToolResult(
        status=("incomplete_coverage" if failure else "ok")
        if evidence
        else ("dependency_failure" if failure else "no_matching_results"),
        message="Retrieved examples only, never a season denominator. "
        + ("Vector retrieval unavailable." if failure else ""),
        evidence=evidence,
        scope={"release": tools.release.version, **filters},
    )
