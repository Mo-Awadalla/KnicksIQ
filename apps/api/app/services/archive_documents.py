"""Document identities shared by indexing and retrieval."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from app.models.box_score import PlayerGameStat, TeamGameStat
from app.models.game import Game
from app.models.report import Report
from app.services.archive_evidence import ArchiveEvidence
from app.services.possession_chunks import PossessionChunk
from app.services.qdrant_client import qdrant_point_id
from app.services.release_bundle import canonical_json

Collection = Literal["games", "box_scores", "reports", "possessions"]


@dataclass(frozen=True)
class ArchiveDocument:
    document_id: str
    collection: Collection
    payload: dict[str, Any]

    def record(self) -> dict[str, Any]:
        return {"id": self.document_id, "payload": self.payload}

    def evidence(
        self,
        *,
        score: float,
        source: Literal["lexical", "dense"],
        evidence_id: str | None = None,
        text: str | None = None,
        extra: dict[str, Any] | None = None,
        point_id: str | None = None,
    ) -> ArchiveEvidence:
        if self.payload.get("chunk_id") != self.document_id:
            raise ValueError("Document payload identity disagrees with its document")
        payload_hash = hashlib.sha256(canonical_json(self.payload)).hexdigest()
        metadata = {
            **self.payload,
            **(extra or {}),
            "document_id": self.document_id,
            "document_collection": self.collection,
            "point_id": point_id or str(qdrant_point_id(self.document_id)),
            "payload_sha256": payload_hash,
            "document_payload": self.payload,
            "retrieval_sources": [source],
        }
        return ArchiveEvidence(
            evidence_id=evidence_id or self.document_id,
            collection=self.collection,
            text=(
                text
                if text is not None
                else str(self.payload.get("text") or self.payload.get("semantic_summary") or "")
            ),
            score=score,
            metadata=metadata,
        )


def _document(
    document_id: str,
    collection: Collection,
    payload: dict[str, Any],
) -> ArchiveDocument:
    return ArchiveDocument(
        document_id=document_id,
        collection=collection,
        payload={**payload, "chunk_id": document_id},
    )


def game_document(game: Game, version: str) -> ArchiveDocument:
    return _document(
        f"game:{game.id}:summary",
        "games",
        {
            "game_id": game.id,
            "data_version": version,
            "date": str(game.game_date),
            "season": game.season,
            "team_ids": [game.home_team_id, game.away_team_id],
            "semantic_summary": (
                f"{game.away_team_id} {game.away_score} at "
                f"{game.home_team_id} {game.home_score} on {game.game_date}"
            ),
        },
    )


def team_box_document(row: TeamGameStat, game: Game, version: str) -> ArchiveDocument:
    return _document(
        f"team-box:{row.game_id}:{row.team_id}",
        "box_scores",
        {
            "game_id": row.game_id,
            "data_version": version,
            "date": str(game.game_date),
            "season": game.season,
            "season_type": game.season_type,
            "team_ids": [row.team_id],
            "semantic_summary": (
                f"{row.team_id} team box: {row.points} points, "
                f"{row.rebounds} rebounds, {row.assists} assists, "
                f"{row.turnovers} turnovers"
            ),
        },
    )


def player_box_document(row: PlayerGameStat, game: Game, version: str) -> ArchiveDocument:
    return _document(
        f"player-box:{row.game_id}:{row.player_id}",
        "box_scores",
        {
            "game_id": row.game_id,
            "data_version": version,
            "date": str(game.game_date),
            "season": game.season,
            "season_type": game.season_type,
            "team_ids": [row.team_id],
            "player_ids": [row.player_id],
            "semantic_summary": (
                f"Player {row.player_id}: {row.points} points, "
                f"{row.rebounds} rebounds, {row.assists} assists, "
                f"{row.turnovers} turnovers"
            ),
        },
    )


def report_document(row: Report, game: Game, version: str) -> ArchiveDocument:
    return _document(
        f"report:{row.id}",
        "reports",
        {
            "game_id": row.game_id,
            "data_version": version,
            "date": str(game.game_date),
            "season": game.season,
            "season_type": game.season_type,
            "team_ids": [game.home_team_id, game.away_team_id],
            "semantic_summary": f"{row.title}. {row.summary}",
        },
    )


def possession_document(chunk: PossessionChunk, version: str | None) -> ArchiveDocument:
    summary = " ".join(line.strip() for line in chunk.text.splitlines() if line.strip())[:360]
    return _document(
        chunk.chunk_id,
        "possessions",
        {
            **chunk.metadata,
            "data_version": version,
            "text": chunk.text,
            "semantic_summary": summary,
            "raw_rows": chunk.rows,
        },
    )
