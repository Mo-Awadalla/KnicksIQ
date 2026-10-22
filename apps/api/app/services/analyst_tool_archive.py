"""search_archive handler: retrieved examples, never a season denominator."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.services.archive_retrieval import (
    fuse_archive_evidence,
    search_archive_lexical,
    search_archive_vectors,
)
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
) -> ToolResult:
    assert scope is not None
    filters = scope.planner_filters()
    filters["game_ids"] = [g.id for g in games]
    lexical = await search_archive_lexical(
        tools.db,
        query=call.question,
        collections=["games", "box_scores", "reports", "possessions"],
        filters=filters,
        data_version=tools.release.version,
        limit=20,
    )
    dense, failure = [], False
    if get_settings().rag_qdrant_enabled:
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
    found = fuse_archive_evidence(lexical, dense, limit=20)
    evidence = [
        Evidence(
            evidence_id=f"{tools.release.version}:{e.evidence_id}",
            release_id=tools.release.version,
            text=e.text,
            game_id=e.metadata.get("game_id"),
            source_name=e.metadata.get("source_name"),
            source_url=e.metadata.get("source_url"),
            metadata=e.metadata,
        )
        for e in found
        if e.metadata.get("data_version") == tools.release.version
        and e.metadata.get("game_id") in {g.id for g in games}
    ]
    return ToolResult(
        status=("incomplete_coverage" if failure else "ok")
        if evidence
        else ("dependency_failure" if failure else "no_matching_results"),
        message="Retrieved examples only, never a season denominator. "
        + ("Vector retrieval unavailable." if failure else ""),
        evidence=evidence,
        scope={"release": tools.release.version, **filters},
    )
