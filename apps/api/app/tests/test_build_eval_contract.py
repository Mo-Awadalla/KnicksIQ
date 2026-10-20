"""The contract builder freezes only when every case is settled, and never caps a scope to fit k."""

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[4] / "tools/release/build_eval_contract.py"
spec = importlib.util.spec_from_file_location("build_eval_contract", SOURCE)
assert spec is not None and spec.loader is not None
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

NINE = [f"game:{i}" for i in range(9)]


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    def question(case_id, text, semantic):
        return {
            "id": case_id,
            "category": "synthetic",
            "question": text,
            "context": [],
            "answerable": semantic,
            "expected_route": "retrieval_rag" if semantic else "refusal",
        }

    def label(case_id, text, disposition, targets, facts):
        return {
            "id": case_id,
            "question": text,
            "proposed_label": {
                "disposition": disposition,
                "canonical_facts": facts,
                "canonical_evidence_ids": targets,
                "notes": [],
            },
        }

    rows = [
        ("broad", "Every game against Boston?", True, "answer", NINE, [{"metric": "games"}]),
        ("that-game", "How did JB play in that game?", True, "clarify", [], []),
        ("off-topic", "Write me a poem.", False, "refuse", [], []),
    ]
    questions, labels = tmp_path / "questions.jsonl", tmp_path / "labels.jsonl"
    questions.write_text("".join(json.dumps(question(*r[:2], r[2])) + "\n" for r in rows))
    labels.write_text("".join(json.dumps(label(r[0], r[1], *r[3:])) + "\n" for r in rows))
    monkeypatch.setattr(builder, "QUESTIONS", questions)
    monkeypatch.setattr(builder, "LABELS", labels)


CONTEXT_FREE = {
    "that-game": {
        "semantic_targets": [],
        "decision_basis": "Owner ruling: with no earlier game, ask which game.",
        "context_free_clarification": True,
    }
}


def test_fully_adjudicated_contract_freezes_with_full_recall_ceiling(synthetic):
    contract, unresolved = builder.build(CONTEXT_FREE)
    assert unresolved == []
    assert contract["status"] == "frozen"
    assert contract["recall_ceiling"] == 1.0
    case = next(c for c in contract["cases"] if c["id"] == "that-game")
    assert case["semantic_targets"] == []
    assert case["context_free_clarification"] is True
    assert next(c for c in contract["cases"] if c["id"] == "broad")["semantic_targets"] == NINE


@pytest.mark.parametrize(
    "adjudications",
    [
        {},
        {"that-game": {**CONTEXT_FREE["that-game"], "context_free_clarification": False}},
        {"that-game": {**CONTEXT_FREE["that-game"], "semantic_targets": ["game:1"]}},
        {
            "broad": {
                "semantic_targets": [],
                "decision_basis": "x",
                "context_free_clarification": True,
            }
        },
    ],
)
def test_unresolved_or_inconsistent_cases_keep_the_contract_a_draft(synthetic, adjudications):
    contract, unresolved = builder.build(adjudications)
    assert contract["status"] == "draft"
    assert unresolved
    assert contract["recall_ceiling"] < 1.0
