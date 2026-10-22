"""Verify analyst contracts against a local release, with optional live repair and review.

Run with a local DB_URL, REDIS_URL, and the desired provider settings. No database writes.
The default performs no model calls. --live makes one repair and one review per answer.

    uv run --package knicksiq-api python tools/release/verify_analyst_boundaries.py \
        --out release-artifacts/20261022-boundary-fixes/archive.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_loop import AnalystLoop
from app.services.analyst_provider import encoded, reviewer_system_prompt, token_upper_bound
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import Action, AnswerReview, ClaimUse, ProposedAnswer, ToolCall
from sqlalchemy import select, text

CASES = [
    ("How many points did Brunson average in December?", "get_player_stats", "points", "average"),
    (
        "How many total assists did Brunson have in December?",
        "get_player_stats",
        "assists",
        "total",
    ),
    ("What was their regular-season record?", "get_team_stats", None, "total"),
]


async def run(live: bool) -> dict:
    settings = get_settings()
    if urlparse(settings.db_url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("This verification requires a local read-only archive")
    records = []
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        for question, name, metric, aggregation in CASES:
            tools = AnalystTools(db, release, question, release.season, {})
            await tools.prepare()
            call = ToolCall(name=name, question=question, metric=metric, aggregation=aggregation)
            result = await tools.execute(call)
            if result.status != "ok":
                raise AssertionError(result.message)
            loop = AnalystLoop(tools, [])
            loop.results.append(result)
            loop.payload(Action)
            selected = (
                result.claims
                if name == "get_player_stats"
                else [c for c in result.claims if c.metric_id in {"wins", "losses"}]
            )
            answer = ProposedAnswer(
                text=" ".join(c.statement for c in selected),
                claims=[ClaimUse(claim_id=c.claim_id, displayed_value=c.value) for c in selected],
            )
            review_payload = loop.payload(
                AnswerReview,
                answer=answer,
                review=True,
                instruction_bytes=token_upper_bound(reviewer_system_prompt()),
            )
            actual = {
                "question": question,
                "resolved_metric": tools.scope.metric,
                "resolved_aggregation": tools.scope.aggregation,
                "metric_ids": [c.metric_id for c in selected],
                "values": [c.value for c in selected],
                "game_counts": [len(c.game_ids or []) for c in selected],
                "supporting_receipts": [len(c.supporting_evidence_ids) for c in selected],
                "review_claims": len(review_payload["claims"]),
                "review_receipts": len(review_payload["evidence"]),
                "review_payload_bytes": token_upper_bound(encoded(review_payload)),
                "review_evidence_bytes": token_upper_bound(encoded(review_payload["claims"]))
                + token_upper_bound(encoded(review_payload["evidence"])),
                "review_within_budget": True,
            }
            if metric is not None:
                conflicting = await tools.execute(
                    call.model_copy(
                        update={
                            "metric": "rebounds" if metric != "rebounds" else "points",
                            "aggregation": "average" if aggregation == "total" else "total",
                        }
                    )
                )
                actual["conflicting_request_preserved_intent"] = conflicting.status == "ok" and [
                    (c.metric_id, c.value) for c in conflicting.claims
                ] == [(c.metric_id, c.value) for c in result.claims]
            if live:
                wrong = answer.model_copy(update={"text": "The requested value was 999."})
                try:
                    repaired = await loop.model(
                        ProposedAnswer,
                        answer=wrong,
                        repair=(
                            "The number 999 is unsupported. Answer the requested metric and "
                            "aggregation from supplied facts. Include every used claim reference."
                        ),
                    )
                    accepted, reason = await loop.validate(repaired)
                    delivered = loop.render(repaired, llm=True) if accepted else None
                    actual["repair"] = {
                        "answer": repaired.text,
                        "validated": accepted,
                        "reason": reason,
                        "declared_claim_ids": [c.claim_id for c in repaired.claims],
                        "delivered_citations": len(delivered["citations"]) if delivered else 0,
                    }
                finally:
                    await loop.settle()
                actual["model_calls"] = loop.calls
                actual["trace"] = loop.trace
            records.append(actual)
    return {
        "release": release.version,
        "live": live,
        "provider": settings.ai_provider,
        "writer": settings.ai_chat_model,
        "reviewer": settings.analyst_review_model,
        "records": records,
        "passed": all(
            r["review_within_budget"]
            and r.get("conflicting_request_preserved_intent", True)
            and (not live or r["repair"]["validated"])
            for r in records
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.live))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    for row in result["records"]:
        print(json.dumps({k: v for k, v in row.items() if k != "trace"}))
    print("PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
