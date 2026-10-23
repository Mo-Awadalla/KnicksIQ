"""Exercise local archive conversations and compound facts through the real API.

Supply a localhost DB_URL and REDIS_URL. The caller chooses deterministic or live model
settings. This command never initializes a budget ledger or changes basketball data.
Session bearer tokens are held in memory and omitted from artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient


async def run() -> dict:
    settings = get_settings()
    if urlsplit(settings.db_url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("A local archive is required")
    app = create_app()
    rows = []
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=60
        ) as client:
            prior = {}
            for question in (
                "How many points did Brunson average in December?",
                "Hello",
                "Which parlay should I bet on tonight?",
                "And his assists?",
                "What were Brunson's average points, rebounds and assists in December?",
                "What were Brunson's total and average points in December?",
            ):
                request = {
                    "question": question,
                    "turn_id": uuid.uuid4().hex,
                    "session_token": prior.get("session_token"),
                    "expected_revision": prior.get("revision", 0),
                }
                response = await client.post("/analysis/query", json=request)
                response.raise_for_status()
                body = response.json()
                claim_map = {
                    citation["metadata"]["claim"]["claim_id"]: citation["metadata"]["claim"]
                    for citation in body["citations"]
                    if citation.get("metadata", {}).get("claim")
                }
                rows.append(
                    {
                        "question": question,
                        "answer": body["answer"],
                        "revision": body["revision"],
                        "committed": body["state_committed"],
                        "same_session": not prior
                        or body["session_token"] == prior["session_token"],
                        "llm_validated": body["llm_validated"],
                        "degraded": body["degraded"],
                        "warnings": body["warnings"],
                        "claims": [
                            {
                                key: c.get(key)
                                for key in (
                                    "metric_id",
                                    "value",
                                    "sample_size",
                                    "game_ids",
                                    "window",
                                )
                            }
                            for c in claim_map.values()
                        ],
                        "models": [
                            {
                                key: trace.get(key)
                                for key in ("stage", "model", "served_model", "protocol")
                            }
                            for trace in body["tool_calls"]
                            if trace.get("tool", "").startswith("llm")
                        ],
                    }
                )
                prior = body
    first_population = {g for c in rows[0]["claims"] for g in c["game_ids"]}
    followed_population = {g for c in rows[3]["claims"] for g in c["game_ids"]}
    checks = {
        "session_continuity": all(
            r["committed"] and r["same_session"] and r["revision"] == i + 1
            for i, r in enumerate(rows)
        ),
        "followup_window": bool(first_population) and first_population == followed_population,
        "compound_metrics": {"points:average", "rebounds:average", "assists:average"}
        <= {c["metric_id"] for c in rows[4]["claims"]},
        "compound_aggregations": {"points:average", "points:total"}
        <= {c["metric_id"] for c in rows[5]["claims"]},
    }
    return {
        "mode": settings.analysis_answer_mode,
        "provider": settings.ai_provider,
        "checks": checks,
        "passed": all(checks.values()),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(run())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps({"mode": result["mode"], "checks": result["checks"], "passed": result["passed"]})
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
