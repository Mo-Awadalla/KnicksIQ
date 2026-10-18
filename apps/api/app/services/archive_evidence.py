"""Archive evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArchiveEvidence:
    evidence_id: str
    collection: str
    text: str
    score: float
    metadata: dict[str, Any]


def _canonical_key(collection: str, metadata: dict[str, Any], fallback: str) -> str:
    game_id = metadata.get("game_id", "archive")
    if collection == "games":
        source_id = game_id
    elif collection == "box_scores":
        source_id = (
            metadata.get("source_row_id")
            or tuple(metadata.get("player_ids") or [])
            or tuple(metadata.get("team_ids") or [])
            or fallback
        )
    elif collection == "reports":
        source_id = metadata.get("report_id") or metadata.get("chunk_id") or fallback
    else:
        source_id = (
            metadata.get("sequence_id")
            or metadata.get("chunk_id")
            or metadata.get("source_row_id")
            or fallback
        )
    return f"{collection}:{game_id}:{source_id}"
