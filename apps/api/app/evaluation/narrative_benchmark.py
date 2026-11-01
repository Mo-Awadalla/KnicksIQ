"""Pinned inputs and document identities for narrative retrieval."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.release_bundle import canonical_json

PROTOCOL = "route-aware-evaluation-v2"
LABEL_SCHEMA = "narrative-retrieval-label-proposal-v1"
PROFILE_SCHEMA = "narrative-retrieval-profile-v1"
APPROVAL_SCHEMA = "narrative-retrieval-approval-v1"

COLLECTIONS = {
    "games": "knicks_games",
    "box_scores": "knicks_box_scores",
    "reports": "knicks_reports",
    "possessions": "knicks_possessions",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")

PROFILE_SETTINGS = (
    "rag_embedding_model",
    "rag_embedding_max_seq_length",
    "rag_qdrant_vector_size",
    "rag_qdrant_enabled",
    "rag_qdrant_cloud_inference",
    "rag_hybrid_enabled",
    "rag_contextual_event_windows_enabled",
    "rag_rrf_k",
    "rag_lexical_weight",
    "rag_dense_weight",
    "rag_exact_match_boost",
    "rag_collection_weights",
    "rag_fused_candidate_limit",
    "rag_multi_game_max_evidence_per_game",
    "rag_qdrant_games_collection",
    "rag_qdrant_box_scores_collection",
    "rag_qdrant_reports_collection",
    "rag_qdrant_possessions_collection",
)

IMPLEMENTATION_FILES = (
    "evaluation/narrative_benchmark.py",
    "evaluation/narrative_collection.py",
    "evaluation/narrative_scoring.py",
    "services/analyst_tools.py",
    "services/archive_clock.py",
    "services/archive_documents.py",
    "services/archive_evidence.py",
    "services/archive_lexical_sql.py",
    "services/archive_retrieval.py",
    "services/embeddings.py",
    "services/possession_chunks.py",
    "services/qdrant_client.py",
    "services/rag_ranking.py",
    "services/retrieval_fusion.py",
)


class NarrativeError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def implementation_sha256() -> str:
    app_root = Path(__file__).resolve().parents[1]
    return digest(
        {
            name: hashlib.sha256((app_root / name).read_bytes()).hexdigest()
            for name in IMPLEMENTATION_FILES
        }
    )


def _read(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise NarrativeError(f"{path.name} must contain an object")
    return value, hashlib.sha256(raw).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NarrativeError(f"{field} must be a nonempty string")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NarrativeError(f"{field} must be a nonnegative integer")
    return value


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if not HEX64.fullmatch(text):
        raise NarrativeError(f"{field} must be a lowercase SHA-256")
    return text


@dataclass(frozen=True)
class Document:
    canonical_id: str
    document_id: str
    collection: str
    physical_collection: str
    point_id: str
    payload_sha256: str
    game_id: int
    nba_game_id: str


@dataclass(frozen=True)
class NarrativeCase:
    id: str
    question: str
    season: str
    nba_game_id: str
    game_id: int
    game_date: str
    opponent_id: str
    period: int
    clock: str
    relevant_ids: frozenset[str]

    def request(self, request_id: str) -> dict[str, Any]:
        return {
            "case_id": self.id,
            "request_id": request_id,
            "tool": "search_archive",
            "question": self.question,
            "season": self.season,
            "filters": {
                "dates": [self.game_date],
                "team_ids": ["NYK", self.opponent_id],
                "player_ids": [],
                "game_ids": [self.game_id],
                "periods": [self.period],
                "season_types": [],
            },
        }


@dataclass(frozen=True)
class NarrativeBenchmark:
    version: str
    cases: tuple[NarrativeCase, ...]
    documents: dict[str, Document]
    identity: dict[str, Any]
    profile: dict[str, Any]
    approval_problems: tuple[str, ...]

    @property
    def identity_sha256(self) -> str:
        return digest(self.identity)

    @property
    def approved(self) -> bool:
        return not self.approval_problems

    def resolve(self, entry: dict[str, Any], game_id: int) -> Document:
        document_id = _text(entry.get("document_id"), "trace.document_id")
        document = self.documents.get(document_id)
        if document is None:
            raise NarrativeError("document_not_in_corpus")
        collection = str(entry.get("collection") or "")
        accepted = {
            document.collection,
            document.physical_collection,
            next(
                (name for name, alias in COLLECTIONS.items() if alias == document.collection),
                "",
            ),
        }
        if collection not in accepted:
            raise NarrativeError("document_collection_mismatch")
        if entry.get("game_id") != game_id or document.game_id != game_id:
            raise NarrativeError("document_game_mismatch")
        if entry.get("point_id") != document.point_id:
            raise NarrativeError("document_point_mismatch")
        if entry.get("payload_sha256") != document.payload_sha256:
            raise NarrativeError("document_payload_mismatch")
        return document


def load_benchmark(
    labels_path: Path,
    corpus_path: Path,
    mapping_path: Path,
    profile_path: Path,
    *,
    primary_identity_sha256: str,
    approval_path: Path | None = None,
) -> NarrativeBenchmark:
    _hash(primary_identity_sha256, "primary_identity_sha256")
    labels, labels_hash = _read(labels_path)
    corpus, corpus_hash = _read(corpus_path)
    mapping, mapping_hash = _read(mapping_path)
    profile, profile_hash = _read(profile_path)

    if labels.get("schema") != LABEL_SCHEMA:
        raise NarrativeError("narrative_label_schema_invalid")
    if profile.get("schema") != PROFILE_SCHEMA:
        raise NarrativeError("narrative_profile_schema_invalid")
    version = _text(labels.get("version"), "labels.version")
    if corpus.get("version") != version or mapping.get("version") != version:
        raise NarrativeError("narrative_release_mismatch")
    if labels.get("original_question_count") != 120:
        raise NarrativeError("primary_case_count_changed")
    if labels.get("original_semantic_case_count") != 50:
        raise NarrativeError("original_semantic_count_changed")
    if labels.get("labelled_before_any_ranked_query") is not True:
        raise NarrativeError("source_first_labels_not_recorded")

    settings = profile.get("settings")
    if not isinstance(settings, dict) or set(settings) != set(PROFILE_SETTINGS):
        raise NarrativeError("narrative_profile_settings_incomplete")
    if (
        settings["rag_qdrant_enabled"] is not True
        or settings["rag_hybrid_enabled"] is not True
        or settings["rag_qdrant_cloud_inference"] is not False
    ):
        raise NarrativeError("real_local_hybrid_profile_required")
    if profile.get("tool_limit") != 20:
        raise NarrativeError("narrative_tool_limit_changed")
    embedding = profile.get("query_embedding")
    if (
        not isinstance(embedding, dict)
        or embedding != profile.get("index_embedding")
        or not embedding.get("revision")
        or embedding.get("dimension") != settings["rag_qdrant_vector_size"]
        or embedding.get("model") != settings["rag_embedding_model"]
        or embedding.get("max_sequence_length") != settings["rag_embedding_max_seq_length"]
    ):
        raise NarrativeError("index_query_embedding_profile_mismatch")

    raw_documents = corpus.get("documents")
    if not isinstance(raw_documents, dict) or not raw_documents:
        raise NarrativeError("narrative_corpus_missing")
    documents: dict[str, Document] = {}
    canonical_ids: set[str] = set()
    point_keys: set[tuple[str, str]] = set()
    for document_id, row in raw_documents.items():
        if not isinstance(row, dict):
            raise NarrativeError("malformed_document_identity")
        document = Document(
            canonical_id=_text(row.get("canonical_document_id"), "canonical_document_id"),
            document_id=_text(document_id, "document_id"),
            collection=_text(row.get("collection"), "collection"),
            physical_collection=_text(row.get("physical_collection"), "physical_collection"),
            point_id=_text(row.get("point_id"), "point_id"),
            payload_sha256=_hash(row.get("payload_sha256"), "payload_sha256"),
            game_id=_integer(row.get("game_id"), "game_id"),
            nba_game_id=_text(row.get("nba_game_id"), "nba_game_id"),
        )
        point_key = (document.collection, document.point_id)
        if document.canonical_id in canonical_ids or point_key in point_keys:
            raise NarrativeError("duplicate_document_identity")
        canonical_ids.add(document.canonical_id)
        point_keys.add(point_key)
        documents[document_id] = document

    raw_cases = labels.get("cases")
    if (
        not isinstance(raw_cases, list)
        or len(raw_cases) != labels.get("benchmark_case_count")
        or len(raw_cases) != 20
    ):
        raise NarrativeError("narrative_case_count_changed")
    cases: list[NarrativeCase] = []
    seen: set[str] = set()
    for row in raw_cases:
        case_id = _text(row.get("id"), "case.id")
        if case_id in seen:
            raise NarrativeError("duplicate_narrative_case")
        seen.add(case_id)
        question = _text(row.get("question"), "case.question")
        scope = row.get("scope") or {}
        day = _text(scope.get("game_date"), "scope.game_date")
        date.fromisoformat(day)
        opponent = _text(scope.get("opponent_id"), "scope.opponent_id")
        period = _integer(scope.get("period"), "scope.period")
        if period < 1:
            raise NarrativeError("period_out_of_range")
        clock = _text(scope.get("clock"), "scope.clock")
        nba_id = _text(row.get("nba_game_id"), "nba_game_id")
        game_row = (mapping.get("rows") or {}).get(f"game:{nba_id}")
        if not isinstance(game_row, dict):
            raise NarrativeError("narrative_game_not_in_sql_mapping")
        game_id = _integer(game_row.get("game_id"), "mapped.game_id")
        source_row = game_row.get("source_row") or {}
        if source_row.get("game_date") != day or {
            source_row.get("home_team_id"),
            source_row.get("away_team_id"),
        } != {"NYK", opponent}:
            raise NarrativeError("question_scope_disagrees_with_source_game")
        ordinal = {1: "first", 2: "second", 3: "third", 4: "fourth"}.get(period)
        question_period = re.search(rf"\bquarter\s+{period}\b", question, re.I) or (
            ordinal is not None and re.search(rf"\b{ordinal}\s+quarter\b", question, re.I)
        )
        if (
            day not in question
            or not re.search(rf"\b{re.escape(opponent)}\b", question)
            or clock not in question
            or not question_period
        ):
            raise NarrativeError("scope_not_explicit_in_question")

        relevant = row.get("relevant_document_ids")
        targets = row.get("target_records")
        if (
            not isinstance(relevant, list)
            or not relevant
            or len(set(relevant)) != len(relevant)
            or not isinstance(targets, list)
            or len(targets) != len(relevant)
        ):
            raise NarrativeError("narrative_relevance_unresolved")
        checked: set[str] = set()
        for target in targets:
            document = documents.get(target.get("runtime_document_id"))
            if (
                document is None
                or document.canonical_id != target.get("canonical_document_id")
                or document.point_id != target.get("point_id")
                or document.payload_sha256 != target.get("payload_sha256")
                or document.game_id != game_id
                or document.nba_game_id != nba_id
            ):
                raise NarrativeError("gold_document_not_in_frozen_corpus")
            checked.add(document.canonical_id)
        if checked != set(relevant):
            raise NarrativeError("gold_target_set_disagrees")
        source = row.get("source") or {}
        _hash(source.get("snapshot_sha256"), "source.snapshot_sha256")
        _text(source.get("url"), "source.url")
        _text(source.get("description"), "source.description")
        cases.append(
            NarrativeCase(
                id=case_id,
                question=question,
                season=_text(row.get("season"), "case.season"),
                nba_game_id=nba_id,
                game_id=game_id,
                game_date=day,
                opponent_id=opponent,
                period=period,
                clock=clock,
                relevant_ids=frozenset(relevant),
            )
        )

    identity = {
        "protocol": PROTOCOL,
        "primary_identity_sha256": primary_identity_sha256,
        "labels_sha256": labels_hash,
        "corpus_sha256": corpus_hash,
        "mapping_sha256": mapping_hash,
        "profile_sha256": profile_hash,
        "version": version,
        "case_ids": [case.id for case in cases],
    }
    problems = ["narrative_labels_owner_unapproved"]
    if approval_path is not None:
        approval, _ = _read(approval_path)
        try:
            datetime.fromisoformat(str(approval.get("approved_at") or "").replace("Z", "+00:00"))
            valid = (
                approval.get("schema") == APPROVAL_SCHEMA
                and approval.get("approved") is True
                and bool(str(approval.get("approver") or "").strip())
                and approval.get("identity_sha256") == digest(identity)
            )
        except ValueError:
            valid = False
        problems = [] if valid else ["narrative_approval_unverified"]
    return NarrativeBenchmark(
        version=version,
        cases=tuple(cases),
        documents=documents,
        identity=identity,
        profile=profile,
        approval_problems=tuple(problems),
    )
