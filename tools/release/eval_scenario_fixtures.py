"""Synthetic label, observation and response fixtures for the evaluation scenarios.

These fixtures stand in for the frozen 120-case labels: 58 answer, 53 clarify and
9 refuse cases with 50 semantic members, so every scenario keeps the production
denominators without touching the real dataset. The freeze, approval, review and
evidence-registry artifacts are built with the documented digests so a scenario
can prove that a stale or fabricated copy is refused.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from eval_scenario_records import write_observations
from eval_scenario_support import (
    ANSWER_CASES,
    CLARIFY_CASES,
    REFUSE_CASES,
    RELEASE,
    SEMANTIC_CASES,
    canonical,
    digest,
    dump,
    load,
    run_cli,
)

PROTOCOL = "evaluation-protocol-v2-route-aware"


def synthetic_questions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, ANSWER_CASES + 1):
        rows.append(
            {
                "id": f"answer-{index:03d}",
                "category": "exact_statistics",
                "question": f"Synthetic answer question {index}?",
                "expected_route": "table_rag",
                "relevant_evidence_ids": [],
                "required_facts": [],
                "answerable": True,
                "filters": {},
                "label_status": "reviewed",
            }
        )
    for index in range(1, CLARIFY_CASES + 1):
        rows.append(
            {
                "id": f"clarify-{index:03d}",
                "category": "date_range_last_n",
                "question": f"Synthetic clarification question {index}?",
                "expected_route": None,
                "relevant_evidence_ids": [],
                "required_facts": [],
                "answerable": False,
                "filters": {},
                "label_status": "reviewed",
            }
        )
    for index in range(1, REFUSE_CASES + 1):
        rows.append(
            {
                "id": f"refuse-{index:03d}",
                "category": "unsupported",
                "question": f"Synthetic unsupported question {index}?",
                "expected_route": None,
                "relevant_evidence_ids": [],
                "required_facts": [],
                "answerable": False,
                "filters": {},
                "label_status": "reviewed",
            }
        )
    return rows


def question_for(case_id: str) -> str:
    for row in synthetic_questions():
        if row["id"] == case_id:
            return str(row["question"])
    raise KeyError(case_id)


def answer_fact(case_id: str, index: int) -> dict[str, Any]:
    """One independently proposed typed fact: 101 games won at a stated scope."""
    return {
        "metric": "wins",
        "value": 60 + index,
        "scope": "archive",
        "subject": "team:NYK",
        "canonical_evidence_ids": [f"game:00225000{index:02d}"],
    }


def synthetic_expectations(
    *,
    owner_approved: bool = False,
) -> dict[str, Any]:
    questions = synthetic_questions()
    cases: list[dict[str, Any]] = []
    answer_index = 0
    for row in questions:
        case_id = row["id"]
        if case_id.startswith("answer-"):
            answer_index += 1
            fact = answer_fact(case_id, answer_index)
            expectation = {
                "disposition": "answer",
                "answerable": True,
                "expected_route": "table_rag",
                "canonical_facts": [fact],
                "required_facts": [f"{fact['scope']} — {fact['metric']}: {fact['value']}"],
                "claims": [
                    {
                        "text": f"{fact['scope']} — {fact['metric']}: {fact['value']}",
                        "accepted_phrasings": [],
                        "evidence_ids": fact["canonical_evidence_ids"],
                    }
                ],
                "canonical_evidence_ids": fact["canonical_evidence_ids"],
                "notes": [],
            }
        elif case_id.startswith("clarify-"):
            expectation = {
                "disposition": "clarify",
                "answerable": False,
                "expected_route": None,
                "canonical_facts": [],
                "required_facts": [],
                "claims": [],
                "canonical_evidence_ids": [],
                "notes": ["Synthetic scope ambiguity; ask which definition is intended."],
            }
        else:
            expectation = {
                "disposition": "refuse",
                "answerable": False,
                "expected_route": None,
                "canonical_facts": [],
                "required_facts": [],
                "claims": [],
                "canonical_evidence_ids": [],
                "notes": ["Synthetic out-of-archive request."],
            }
        semantic_member = len(cases) < SEMANTIC_CASES
        cases.append(
            {
                "id": case_id,
                "question": row["question"],
                "category": row["category"],
                "original_answerable": expectation["answerable"],
                "original_route": expectation["expected_route"],
                "proposed_expectation": expectation,
                "original_semantic_member": semantic_member,
                "provisional_canonical_support": [],
                "remaining_owner_decisions": [] if owner_approved else ["Approve proposed label."],
                "owner_approved": owner_approved,
            }
        )
    return {
        "status": "scenario_fixture",
        "candidate": "scenario",
        "labels_sha256": digest_questions(questions),
        "case_count": len(cases),
        "semantic_case_count": SEMANTIC_CASES,
        "proposed_dispositions": {
            "answer": ANSWER_CASES,
            "clarify": CLARIFY_CASES,
            "refuse": REFUSE_CASES,
        },
        "cases": cases,
        "owner_approval": None,
        "frozen": False,
    }


def digest_questions(rows: list[dict[str, Any]]) -> str:
    text = "\n".join(canonical(row) for row in rows) + "\n"
    return hashlib.sha256(text.encode()).hexdigest()


def expectations_content_sha256(payload: dict[str, Any]) -> str:
    """The reviewable content digest, independent of the freeze metadata itself."""
    content = {
        "case_count": payload.get("case_count"),
        "semantic_case_count": payload.get("semantic_case_count"),
        "proposed_dispositions": payload.get("proposed_dispositions"),
        "cases": payload.get("cases"),
    }
    return hashlib.sha256(canonical(content).encode()).hexdigest()


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def freeze_artifact(questions_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """A freeze manifest over the artifacts actually on disk."""
    members = [case["id"] for case in payload["cases"] if case["original_semantic_member"]]
    return {
        "schema": "evaluation-freeze-v1",
        "questions_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
        "expectations_content_sha256": expectations_content_sha256(payload),
        "labels_sha256": payload["labels_sha256"],
        "case_count": len(payload["cases"]),
        "semantic_case_ids": members,
        "protocol": PROTOCOL,
        "frozen_at": "2026-10-30T00:00:00+00:00",
    }


def approval_artifact(freeze: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "evaluation-approval-v1",
        "approved": True,
        "approver": "scenario-fixture",
        "approved_at": "2026-10-30T00:00:00+00:00",
        "labels_sha256": payload["labels_sha256"],
        "freeze_sha256": _sha(freeze),
        "case_count": len(payload["cases"]),
    }


def write_dataset(
    directory: Path,
    *,
    owner_approved: bool = False,
    frozen: bool = False,
) -> tuple[Path, Path]:
    questions = synthetic_questions()
    questions_path = directory / "questions.jsonl"
    questions_path.write_text(
        "\n".join(canonical(row) for row in questions) + "\n", encoding="utf-8"
    )
    expectations = synthetic_expectations(owner_approved=owner_approved)
    expectations["labels_sha256"] = hashlib.sha256(questions_path.read_bytes()).hexdigest()
    if frozen or owner_approved:
        freeze = freeze_artifact(questions_path, expectations)
        expectations["freeze"] = freeze
        expectations["frozen"] = True
        expectations["owner_approval"] = approval_artifact(freeze, expectations)
    expectations_path = dump(directory / "expectation-review.json", expectations)
    return questions_path, expectations_path


def scored_game_row(
    game: int,
    *,
    home_team: str = "NYK",
    home_score: int = 120,
    away_team: str = "BKN",
    away_score: int = 66,
    game_date: str = "2026-01-21",
) -> dict[str, Any]:
    """A complete SQL game row, as a real restore carries it.

    Arithmetic recipes recompute from the row's own columns. A row that carries only
    its id is not a complete snapshot, so a scenario that needs a recomputable score
    supplies this row to both the mapping and the evidence registry.
    """
    return {
        "id": game,
        "nba_game_id": f"00225000{game - 102:02d}",
        "game_date": game_date,
        "home_team_id": home_team,
        "away_team_id": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "season": "2025-26",
        "season_type": "regular",
    }


def synthetic_scoreline() -> dict[str, Any]:
    """The canonical scoreline dictionary a producer states for game 103."""
    return {
        "nba_game_id": "0022500001",
        "game_date": "2026-01-21",
        "home_team_id": "NYK",
        "away_team_id": "BKN",
        "home_score": 120,
        "away_score": 66,
    }


def synthetic_mapping(*, game_rows: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The local mapping fixture; ``game_rows`` upgrades named games to full rows."""
    rows: dict[str, Any] = {}
    full = game_rows or {}
    for index in range(1, 60):
        game = 102 + index
        content = full.get(game, {"game": game})
        rows[f"game:00225000{index:02d}"] = {
            "collection": "games",
            "row_sha256": digest(content),
            "database_row_id": game,
            "game_id": game,
            "release_id": 1,
            "runtime_receipt": f"{RELEASE}:game:{game}",
            "player_id": None,
        }
        rows[f"box:00225000{index:02d}:1628384"] = {
            "collection": "player_game_stats",
            "row_sha256": digest({"game": game, "player": 114}),
            "database_row_id": 9000 + game,
            "game_id": game,
            "release_id": 1,
            "runtime_receipt": f"{RELEASE}:game:{game}:player:114",
            "player_id": 114,
        }
    return {
        "scope": "synthetic scenario mapping; not a local restore",
        "bundle_sha256": digest("scenario-bundle"),
        "version": RELEASE,
        "release_id": 1,
        "verified_source_references": 0,
        "rows": rows,
        "players": {"1628384": {"id": 114, "name": "Jalen Brunson"}},
    }


def evidence_identity(
    questions_path: Path,
    expectations_path: Path,
    mapping_path: Path,
    documents_path: Path | None = None,
) -> str:
    """The review identity digest, computed from the artifacts on disk."""
    expectations = load(expectations_path)
    identity = {
        "questions_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
        "expectations_content_sha256": expectations_content_sha256(expectations),
        "labels_sha256": expectations["labels_sha256"],
        "protocol": PROTOCOL,
        "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
        "documents_sha256": (
            hashlib.sha256(documents_path.read_bytes()).hexdigest() if documents_path else ""
        ),
        "narrative_labels_sha256": "",
    }
    return _sha(identity)


def review_payload(
    rows: list[dict[str, Any]],
    *,
    questions_path: Path,
    expectations_path: Path,
    mapping_path: Path,
    documents_path: Path | None = None,
    reviewer: str = "scenario-fixture",
) -> dict[str, Any]:
    """A complete 120-case review bound to the exact artifacts and responses."""
    expectations = load(expectations_path)
    dispositions = {
        case["id"]: case["proposed_expectation"]["disposition"] for case in expectations["cases"]
    }
    cases: list[dict[str, Any]] = []
    for row in rows:
        case_id = row["case_id"]
        response = row["response"]
        disposition = dispositions[case_id]
        assertions: list[dict[str, Any]] = []
        if disposition == "answer":
            indices = list(range(len(expectations_by_id(expectations)[case_id]["canonical_facts"])))
            for index in indices:
                assertions.append(
                    {
                        "text": response["answer"],
                        "decision": "supported",
                        "canonical_fact_indices": [index],
                        "evidence": "scenario fixture evidence",
                    }
                )
        cases.append(
            {
                "case_id": case_id,
                "response_sha256": row["response_sha256"],
                "disposition": disposition,
                "assertions": assertions,
                "paraphrase": "supported",
            }
        )
    return {
        "schema": "evaluation-review-decisions-v2",
        "evaluation_identity_sha256": evidence_identity(
            questions_path, expectations_path, mapping_path, documents_path
        ),
        "dataset_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
        "reviewer": reviewer,
        "reviewed_at": "2026-10-30T00:00:00+00:00",
        "notes": "Synthetic scenario fixture; not a real review and not an approval.",
        "cases": cases,
    }


def expectations_by_id(expectations: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["id"]: case["proposed_expectation"] for case in expectations["cases"]}


def run_score(
    directory: Path,
    *,
    questions: Path,
    expectations: Path,
    mapping: Path,
    observations: list[dict[str, Any]],
    reviews: Path | None = None,
    extra: list[str] | None = None,
) -> tuple[Any, dict[str, Any] | None]:
    responses = write_observations(directory / "responses.jsonl", observations)
    output = directory / "report.json"
    args = [
        "score",
        "--questions",
        str(questions),
        "--expectations",
        str(expectations),
        "--mapping",
        str(mapping),
        "--responses",
        str(responses),
        "--output",
        str(output),
    ]
    if reviews is not None:
        args.extend(["--reviews", str(reviews)])
    args.extend(extra or [])
    result = run_cli(args, cwd=directory)
    return result, (load(output) if output.exists() else None)
