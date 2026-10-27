#!/usr/bin/env python3
"""End-to-end offline proof for supported factual spans with empty reviewer ids.

A scripted adapter stands in for the provider (no network, no credits):

- the writer answers with one real claim from the prefetched tool result;
- the reviewer returns verdict supported on every factual span but empties both citing
  arrays, the exact reported malformed verdict;
- `--policy old` validates with the codex/llmp-integration 5b585e6 rule, `--policy new`
  with the current rule, so the same request shows the before/after difference.

Two cases per policy:
- backed: every number in the span is a declared claim value, so the new rule attaches the
  claim id and the answer is delivered.
- unbacked: the answer appends a factual sentence with no numbers and no claim, so the new
  rule still fails closed and the deterministic fallback is delivered.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/2 TEST_MODE=false \
    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/revids/empty_ids_e2e.py --policy new
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_DAY", "1000000")
os.environ.setdefault("ANALYSIS_ANSWER_MODE", "llm_primary")
os.environ.setdefault("ANALYST_EVIDENCE_LOOP_ENABLED", "true")
os.environ.setdefault("TEST_MODE", "false")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import app.services.analyst_loop as loop_module  # noqa: E402
import app.services.analyst_provider as provider_module  # noqa: E402
from app.services.evidence_contracts import (  # noqa: E402
    AnswerReview,
    validate_review,
)
from evaluate_empty_ids import old_validate_review  # noqa: E402

UNBACKED = " This is the team's best mark."


class ScriptedAdapter:
    """Answer once from the first numeric claim, then drop the reviewer citations."""

    def __init__(self) -> None:
        self.max_tokens = 3000
        self.timeout_seconds = 20
        self.response_schema: dict[str, Any] | None = None
        self.reasoning_effort = "none"
        self.last_metadata: dict[str, Any] = {
            "provider": "scripted",
            "finish_reason": "stop",
            "usage": {"cost": 0.0},
        }

    async def generate(self, *, system: str, user: str) -> str:
        payload = json.loads(user)
        schema = payload.get("schema") or {}
        title = schema.get("title")
        if title == "AnswerReview" or "review_spans" in payload:
            spans = payload["review_spans"]
            review = AnswerReview(
                assertions=[
                    {
                        "text": span,
                        "assertion_type": "factual",
                        "verdict": "supported",
                        "offending_text": None,
                        "supporting_claim_ids": [],
                        "supporting_evidence_ids": [],
                        "reason": "Scripted supported verdict with dropped citations.",
                    }
                    for span in spans
                ]
            )
            return review.model_dump_json()
        answer = payload.get("proposed_answer")
        if answer is not None:
            # Repair request: repeat the same answer, so the second review fails again.
            return json.dumps(answer)
        claim = next(
            (
                item
                for item in payload.get("claims") or []
                if isinstance(item.get("value"), (int, float))
                and not isinstance(item.get("value"), bool)
                and item.get("statement")
            ),
            None,
        )
        if claim is None:
            return json.dumps(
                {
                    "action": "decline",
                    "tools": [],
                    "answer": {
                        "text": "I can't answer that from the available archive.",
                        "claims": [],
                        "evidence_ids": [],
                        "fact_ids": [],
                        "follow_up_questions": [],
                    },
                }
            )
        used = [
            {
                "claim_id": claim["claim_id"],
                "displayed_value": claim["value"],
                "decimal_places": None,
            }
        ]
        text = claim["statement"]
        question = payload.get("question") or payload.get("requested_question") or ""
        if "control" in question:
            text += UNBACKED
        fact_ids = [
            candidate["fact_id"]
            for candidate in payload.get("candidates") or []
            if set(candidate["claim_ids"]) <= {claim["claim_id"]}
        ]
        return json.dumps(
            {
                "action": "answer_from_available_evidence",
                "tools": [],
                "answer": {
                    "text": text,
                    "claims": used,
                    "evidence_ids": [],
                    "fact_ids": fact_ids,
                    "follow_up_questions": [],
                },
            }
        )


def install(policy: str) -> None:
    provider_module.get_llm_adapter = lambda *args, **kwargs: ScriptedAdapter()
    if policy == "old":

        def old(*args: Any, **kwargs: Any) -> bool:
            return old_validate_review(*args, **kwargs)

        loop_module.validate_review = old
    else:
        loop_module.validate_review = validate_review


async def run_case(client: Any, question: str) -> dict[str, Any]:
    response = await client.post(
        "/analysis/query",
        json={
            "question": question,
            "season": "2025-26",
            "turn_id": "revids-" + uuid.uuid4().hex,
            "expected_revision": 0,
        },
    )
    body = response.json() if response.status_code == 200 else {}
    review_calls = [
        {
            key: item.get(key)
            for key in (
                "provider",
                "finish_reason",
                "review_spans",
                "review_empty_id_spans",
                "review_attachable_spans",
                "review_accepted",
            )
        }
        for item in body.get("tool_calls") or []
        if item.get("stage") == "review"
    ]
    return {
        "status": response.status_code,
        "llm_validated": body.get("llm_validated"),
        "review_calls": review_calls,
        "answer": body.get("answer") or "",
        "warnings": body.get("warnings") or [],
        "citations": len(body.get("citations") or []),
    }


async def main(policy: str, out: Path | None) -> None:
    install(policy)
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app()
    results: dict[str, Any] = {}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=60
        ) as client:
            results["backed"] = await run_case(
                client, "How many total points did the Knicks score?"
            )
            results["unbacked"] = await run_case(
                client, "control: how many total points did the Knicks score?"
            )
    artifact = {
        "policy": policy,
        "cases": results,
        "backed_delivered": bool(results["backed"]["llm_validated"]),
        "unbacked_fell_back": not bool(results["unbacked"]["llm_validated"]),
    }
    if out is not None:
        out.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps({key: value for key, value in artifact.items() if key != "cases"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=["old", "new"], required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.policy, args.out))
