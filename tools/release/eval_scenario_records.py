"""Synthetic runtime responses and the observations that record them.

Every response carries the identity a real candidate emits: its own request id
matching the recorded sent id, a backend-style evidence registry for its receipts,
and typed claims bound to a release. Nothing here is a measurement.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval_scenario_support import RELEASE, canonical, digest

# ---------------------------------------------------------------------- observations


def claim(
    *,
    game: int,
    value: int | float | str | dict[str, Any],
    metric: str = "wins",
    subject: str = "team:NYK",
    unit: str = "wins",
    sample_size: int = 101,
    denominator: int | None = None,
    release: str = RELEASE,
    evidence: list[str] | None = None,
    population: str = "available release archive",
    window: dict[str, Any] | None = None,
    filters: dict[str, Any] | None = None,
    eligibility: dict[str, Any] | None = None,
    season_type: str | None = "regular",
) -> dict[str, Any]:
    supporting = evidence or [f"{RELEASE}:game:{game}"]
    body = {
        "subject_id": subject,
        "metric_id": metric,
        "metric_definition_version": "box-score-v1",
        "value": value,
        "unit": unit,
        "population": population,
        "filters": filters
        or {"opponent_id": None, "periods": [], "home_away": None, "game_result": None},
        "season": "2025-26",
        "season_type": season_type,
        "game_ids": [game],
        "window": window,
        "sample_size": sample_size,
        "denominator": denominator,
        "baseline_claim_ids": [],
        "calculation_version": "analyst-v1",
        "release_id": release,
        "supporting_evidence_ids": supporting,
        "coverage_limitations": ["Available archive only; no causal inference."],
        "eligibility": eligibility or {"appearance": "minutes > 0"},
    }
    body["statement"] = f"Synthetic {body['metric_id']} {body['value']}."
    body["claim_id"] = "claim:" + digest(body)
    return body


def receipt_record(evidence_id: str, *, source_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """The registry entry the candidate emits for one SQL-row receipt.

    The snapshot is the content the digest is computed from, so the scorer verifies
    the row instead of trusting the recorded hash. A scenario that needs a complete
    row passes the same content the mapping carries for that game.
    """
    parts = evidence_id.split(":")
    game = int(parts[2])
    if len(parts) == 5 and parts[3] == "player":
        row = {"game": game, "player": 114}
        return {
            "evidence_id": evidence_id,
            "release_id": RELEASE,
            "text": "synthetic box row",
            "game_id": game,
            "source_row_id": 9000 + game,
            "source_row": row,
            "row_sha256": digest(row),
            "metadata": {},
        }
    row = source_row if source_row is not None else {"game": game}
    return {
        "evidence_id": evidence_id,
        "release_id": RELEASE,
        "text": "synthetic game row",
        "game_id": game,
        "source_row_id": game,
        "source_row": row,
        "row_sha256": digest(row),
        "metadata": {},
    }


def calculation_record(
    receipt: str,
    sources: list[str],
    *,
    sample_size: int,
    denominator: int | float | None,
    numerator: int | float | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": receipt,
        "release_id": RELEASE,
        "text": "synthetic calculation",
        "game_id": None,
        "source_row_id": None,
        "metadata": {
            "calculation_version": "analyst-v1",
            "source_evidence_ids": sources,
            "sample_size": sample_size,
            "denominator": denominator,
            "numerator": numerator,
        },
    }


def ranked(game: int, rank: int, collection: str = "games", score: float = 0.5) -> dict[str, Any]:
    return {
        "evidence_id": f"{collection}:{game}:{game}",
        "collection": collection,
        "game_id": game,
        "player_ids": [],
        "team_ids": ["NYK"],
        "source_row_id": game,
        "sequence_id": None,
        "score": score,
        "rank": rank,
    }


def trace(
    game: int,
    *,
    request_id: str = "req",
    candidates: list[dict[str, Any]] | None = None,
    selected: list[dict[str, Any]] | None = None,
    data_version: str = RELEASE,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "retrieval",
        "tool": "archive_retrieval",
        "kind": "retrieval_trace",
        "request_id": request_id,
        "data_version": data_version,
        "latency_ms": 12,
        "errors": errors or [],
        "lexical": [ranked(game, 1)],
        "dense": [ranked(game, 1, score=0.4)],
        "candidates": candidates or [ranked(game, 1)],
        "selected": selected or [ranked(game, 1)],
    }


def answer_response(
    *,
    game: int,
    value: int | float,
    text: str | None = None,
    claims: list[dict[str, Any]] | None = None,
    trace_entry: dict[str, Any] | None = None,
    receipt: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    outcome: str | None = "answer",
    **claim_kwargs: Any,
) -> dict[str, Any]:
    delivered = claims or [claim(game=game, value=value, **claim_kwargs)]
    citations = []
    for item in delivered:
        citations.append(
            {
                "claim": item["statement"],
                "type": "verified_claim",
                "title": item["statement"],
                "game_id": item["game_ids"][0] if item["game_ids"] else None,
                "source_name": None,
                "source_url": None,
                "metadata": {
                    "claim": item,
                    "evidence_id": receipt
                    or (
                        item["supporting_evidence_ids"][0]
                        if item["supporting_evidence_ids"]
                        else ""
                    ),
                },
            }
        )
    registry = evidence
    if registry is None:
        registry = [
            receipt_record(reference)
            for item in delivered
            for reference in item["supporting_evidence_ids"]
            if not reference.startswith("calculation:")
        ]
    response: dict[str, Any] = {
        "answer": text if text is not None else " ".join(item["statement"] for item in delivered),
        "citations": citations,
        "tool_calls": [trace_entry if trace_entry is not None else trace(game)],
        "evidence": registry,
        "route": "factual_fallback",
        "refused": False,
        "degraded": True,
        "llm_validated": False,
        "data_version": RELEASE,
        "request_id": "req",
        "outcome": outcome,
        "warnings": [],
    }
    if outcome is None:
        response.pop("outcome")
    return response


def disposition_response(outcome: str) -> dict[str, Any]:
    return {
        "answer": f"Synthetic {outcome}.",
        "citations": [],
        "tool_calls": [],
        "evidence": [],
        "route": None,
        "refused": outcome == "refuse",
        "degraded": False,
        "llm_validated": False,
        "data_version": RELEASE,
        "request_id": "req",
        "outcome": outcome,
        "warnings": [],
    }


def observation(case_id: str, response: dict[str, Any], *, latency_ms: int = 20) -> dict[str, Any]:
    """One recorded request/response pair with a consistent request identity."""
    from eval_scenario_fixtures import question_for

    turn_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    response["request_id"] = request_id
    for entry in response.get("tool_calls") or []:
        if isinstance(entry, dict) and entry.get("kind") == "retrieval_trace":
            entry["request_id"] = request_id
    response.pop("response_sha256", None)
    return {
        "case_id": case_id,
        "request_id": request_id,
        "turn_id": turn_id,
        "session_token": None,
        "expected_revision": 0,
        "request": {
            "question": question_for(case_id),
            "season": "2025-26",
            "context": [],
            "turn_id": turn_id,
            "expected_revision": 0,
        },
        "response": response,
        "http_status": 200,
        "latency_ms": latency_ms,
        "started_at": datetime.now(UTC).isoformat(),
        "response_sha256": digest(response),
    }


def baseline_observations(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    answer_index = 0
    for row in questions:
        case_id = row["id"]
        if case_id.startswith("answer-"):
            answer_index += 1
            game = 102 + answer_index
            rows.append(observation(case_id, answer_response(game=game, value=60 + answer_index)))
        elif case_id.startswith("clarify-"):
            rows.append(observation(case_id, disposition_response("clarify")))
        else:
            rows.append(observation(case_id, disposition_response("refuse")))
    return rows


def write_observations(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(canonical(row) for row in rows) + "\n", encoding="utf-8")
    return path


def calculation_receipt(
    game: int, subject: str, metric: str, sources: list[str], value: int
) -> str:
    """The documented receipt digest: json.dumps of the five fields, default separators."""
    import json

    payload = json.dumps([RELEASE, subject, metric, sources, value], sort_keys=True)
    return "calculation:" + hashlib.sha256(payload.encode()).hexdigest()
