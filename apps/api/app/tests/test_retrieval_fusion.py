"""Weighted fusion and diversity policies."""

from __future__ import annotations

from types import SimpleNamespace

from app.services import archive_retrieval
from app.services.archive_retrieval import ArchiveEvidence, fuse_archive_evidence
from app.services.retrieval_fusion import weighted_reciprocal_rank_fusion


def test_repeated_query_variants_cannot_stack_dense_credit():
    fused = weighted_reciprocal_rank_fusion(
        [
            ("dense", ["a", "b"], 1.0),
            ("dense", ["a", "c"], 1.0),
            ("lexical", ["b", "a"], 1.25),
        ],
        k=60,
    )
    by_id = {item.key: item for item in fused}

    assert [component.source for component in by_id["a"].components] == [
        "dense",
        "lexical",
    ]
    assert by_id["a"].score == (1 / 61) + (1.25 / 62)


def test_multi_game_diversity_caps_results_per_game(monkeypatch):
    monkeypatch.setattr(
        archive_retrieval,
        "get_settings",
        lambda: SimpleNamespace(
            rag_lexical_weight=1.25,
            rag_dense_weight=1.0,
            rag_rrf_k=60,
            rag_fused_candidate_limit=20,
            rag_collection_weights={},
            rag_exact_match_boost=0.25,
        ),
    )
    lexical = [
        ArchiveEvidence(
            f"lexical:possessions:{index}",
            "possessions",
            f"event {index}",
            1.0,
            {
                "game_id": game_id,
                "source_row_id": index,
                "retrieval_sources": ["lexical"],
            },
        )
        for index, game_id in enumerate([1, 1, 1, 2, 3], start=1)
    ]

    results = fuse_archive_evidence(
        lexical,
        [],
        limit=5,
        max_per_game=2,
    )

    assert [item.metadata["game_id"] for item in results].count(1) == 2
    assert {item.metadata["game_id"] for item in results} == {1, 2, 3}


def test_fusion_records_component_ranks_weights_and_exact_matches(monkeypatch):
    monkeypatch.setattr(
        archive_retrieval,
        "get_settings",
        lambda: SimpleNamespace(
            rag_lexical_weight=1.25,
            rag_dense_weight=1.0,
            rag_rrf_k=60,
            rag_fused_candidate_limit=20,
            rag_collection_weights={"reports": 1.1},
            rag_exact_match_boost=0.25,
        ),
    )
    metadata = {
        "game_id": 7,
        "report_id": 3,
        "team_ids": ["BOS"],
        "date": "2026-01-14",
    }

    result = fuse_archive_evidence(
        [ArchiveEvidence("lexical:reports:3", "reports", "report", 1.0, metadata)],
        [ArchiveEvidence("vector:reports:3", "reports", "report", 0.9, metadata)],
        limit=5,
        filters={
            "game_ids": [7],
            "team_ids": ["BOS"],
            "dates": ["2026-01-14"],
        },
    )[0]

    assert result.metadata["component_ranks"] == {"lexical": 1, "dense": 1}
    assert {item["source"] for item in result.metadata["fusion_components"]} == {
        "lexical",
        "dense",
    }
    assert result.metadata["exact_match_fields"] == ["game_id", "date", "team_ids"]
