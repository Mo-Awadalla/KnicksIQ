"""Resolve runtime receipts and canonical ids through the recorded local mapping.

An absent reference fails closed; the mapping proves local source identity only.

The mapping itself is data and identity lookups. Proving one cited reference is a
separate concern, so ``resolve_citation`` and ``resolve_document`` delegate to
``mapping_citation``, which owns the receipt, document and calculation verdicts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from app.evaluation import mapping_citation
from app.evaluation.arithmetic import Population, PopulationRow
from app.evaluation.mapping_identity import (
    CitationResolution,
    DocumentIdentity,
    MappingError,
    SourceRow,
)
from app.evaluation.observations import canonical_digest
from app.evaluation.observations_records import EvidenceRecord


@dataclass(frozen=True)
class RuntimeMapping:
    version: str
    release_id: int
    scope: str
    rows: dict[str, SourceRow]
    player_names: dict[int, str]
    player_canonical_ids: dict[int, str]
    file_sha256: str
    row_by_database_id: dict[int, SourceRow] = field(default_factory=dict)
    row_by_receipt: dict[str, SourceRow] = field(default_factory=dict)
    game_by_runtime_id: dict[int, str] = field(default_factory=dict)
    box_by_game_player: dict[tuple[int, int], str] = field(default_factory=dict)
    team_by_game_team: dict[tuple[int, str], str] = field(default_factory=dict)
    documents: dict[str, DocumentIdentity] = field(default_factory=dict)
    population: Population = field(default_factory=Population)

    def unmapped_references(self, references: tuple[str, ...] | list[str]) -> list[str]:
        return [reference for reference in references if reference not in self.rows]

    def canonical_for_game(self, runtime_game_id: int | None) -> str | None:
        if runtime_game_id is None:
            return None
        return self.game_by_runtime_id.get(int(runtime_game_id))

    def player_name(self, runtime_player_id: int | None) -> str | None:
        if runtime_player_id is None:
            return None
        return self.player_names.get(int(runtime_player_id))

    def runtime_for_canonical_game(self, canonical_id: Any) -> int | None:
        row = self.rows.get(f"game:{canonical_id}")
        return row.game_id if row is not None else None

    def runtime_for_canonical_player(self, canonical_player_id: Any) -> int | None:
        key = str(canonical_player_id)
        return next((r for r, c in self.player_canonical_ids.items() if c == key), None)

    def resolve_document(self, possession_id: str) -> CitationResolution:
        """Resolve one possession document, or record why the mapping cannot place it."""
        return mapping_citation.resolve_document(self, possession_id)

    def resolve_citation(
        self,
        reference: str,
        claim: dict[str, Any] | None,
        *,
        registry: dict[str, EvidenceRecord] | None = None,
        content: mapping_citation.CalculationContent | None = None,
    ) -> CitationResolution:
        """Resolve one citation reference, or record why it earns nothing."""
        return mapping_citation.resolve_citation(self, reference, claim, registry, content)

    def calculation_content(
        self, reference: str, registry: dict[str, EvidenceRecord]
    ) -> mapping_citation.CalculationContent | None:
        """The claim-independent content of one calculation reference, cached by callers."""
        return mapping_citation.calculation_content(self, reference, registry)


def load_documents(path: Path, mapping: RuntimeMapping) -> RuntimeMapping:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("version") or "") != mapping.version:
        raise MappingError(
            f"{path} documents release {payload.get('version')!r} but the mapping is "
            f"{mapping.version!r}"
        )
    documents: dict[str, DocumentIdentity] = {}
    for value in (payload.get("documents") or {}).values():
        identity = DocumentIdentity(
            runtime_evidence_id=str(value["runtime_evidence_id"]),
            collection=str(value["collection"]),
            game_id=int(value["game_id"]),
            point_id=str(value["point_id"]),
            payload_sha256=str(value["payload_sha256"]),
        )
        documents[identity.runtime_evidence_id] = identity
    return replace(mapping, documents=documents)


def load_mapping(path: Path) -> RuntimeMapping:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    version = str(payload.get("version") or "")
    if not version:
        raise MappingError(f"{path} has no release version")
    rows: dict[str, SourceRow] = {}
    for canonical_id, value in (payload.get("rows") or {}).items():
        try:
            row = SourceRow(
                canonical_id=str(canonical_id),
                collection=str(value["collection"]),
                row_sha256=str(value["row_sha256"]),
                database_row_id=int(value["database_row_id"]),
                game_id=int(value["game_id"]),
                release_id=int(value["release_id"]),
                runtime_receipt=value.get("runtime_receipt"),
                player_id=None if value.get("player_id") is None else int(value["player_id"]),
                source_row=value.get("source_row"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MappingError(f"row {canonical_id} is malformed: {exc}") from exc
        if row.source_row is not None and not isinstance(row.source_row, dict):
            raise MappingError(f"row {canonical_id} source_row is not an object")
        if row.source_row is not None and canonical_digest(row.source_row) != row.row_sha256:
            # A projected row that does not reproduce its own recorded digest is not a
            # verified snapshot, so it can never be used as a population oracle.
            raise MappingError(f"row {canonical_id} source_row does not match its digest")
        rows[str(canonical_id)] = row
    player_names: dict[int, str] = {}
    player_canonical_ids: dict[int, str] = {}
    for canonical_player_id, value in (payload.get("players") or {}).items():
        runtime_id = int(value["id"])
        player_names[runtime_id] = str(value["name"])
        player_canonical_ids[runtime_id] = str(canonical_player_id)
    by_database_id: dict[int, SourceRow] = {}
    by_receipt: dict[str, SourceRow] = {}
    by_game: dict[int, str] = {}
    box_by_game_player: dict[tuple[int, int], str] = {}
    team_by_game_team: dict[tuple[int, str], str] = {}
    for row in rows.values():
        by_database_id[row.database_row_id] = row
        if row.runtime_receipt:
            by_receipt[row.runtime_receipt] = row
        if row.collection == "games":
            by_game[row.game_id] = row.canonical_id
        elif row.collection == "player_game_stats" and row.player_id is not None:
            box_by_game_player[(row.game_id, row.player_id)] = row.canonical_id
        elif row.collection == "team_game_stats":
            segments = row.canonical_id.split(":")
            if len(segments) == 3:
                team_by_game_team[(row.game_id, segments[2])] = row.canonical_id
    return RuntimeMapping(
        version=version,
        release_id=int(payload.get("release_id") or 0),
        scope=str(payload.get("scope") or ""),
        rows=rows,
        player_names=player_names,
        player_canonical_ids=player_canonical_ids,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        row_by_database_id=by_database_id,
        row_by_receipt=by_receipt,
        game_by_runtime_id=by_game,
        box_by_game_player=box_by_game_player,
        team_by_game_team=team_by_game_team,
        population=_population(rows),
    )


def _population(rows: dict[str, SourceRow]) -> Population:
    """The verified projections indexed for whole-population recomputation.

    Rows without a projection cannot contribute: a recipe that needs the release
    population blocks rather than counting only the rows an answer chose to cite.
    """
    games: dict[int, PopulationRow] = {}
    game_by_nba: dict[str, int] = {}
    box: list[PopulationRow] = []
    team: list[PopulationRow] = []
    periods: list[PopulationRow] = []
    for row in rows.values():
        if row.source_row is None:
            continue
        entry = PopulationRow(
            canonical_id=row.canonical_id,
            collection=row.collection,
            game_id=row.game_id,
            player_id=row.player_id,
            row=row.source_row,
        )
        if row.collection == "games":
            games[row.game_id] = entry
            nba_game_id = row.source_row.get("nba_game_id")
            if nba_game_id is not None:
                game_by_nba[str(nba_game_id)] = row.game_id
        elif row.collection == "player_game_stats":
            box.append(entry)
        elif row.collection == "team_game_stats":
            team.append(entry)
        elif row.collection == "period_scores":
            periods.append(entry)
    return Population(
        games=games,
        game_by_nba=game_by_nba,
        box=tuple(box),
        team=tuple(team),
        periods=tuple(periods),
    )
