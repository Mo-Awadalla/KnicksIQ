"""Check compound selectors against a local archive and optionally the real model API."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.main import create_app
from app.models.dataset_release import DatasetRelease
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

CASES = (
    (
        "What were Brunson's average points, rebounds and assists in December?",
        (("points", "average"), ("rebounds", "average"), ("assists", "average")),
    ),
    (
        "What were Brunson's total and average points in December?",
        (("points", "total"), ("points", "average")),
    ),
)


async def run(live: bool) -> dict:
    if urlparse(get_settings().db_url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("A local read-only archive is required")
    rows = []
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        for question, selections in CASES:
            tools = AnalystTools(db, release, question, release.season, {})
            await tools.prepare()
            claims = []
            for metric, aggregation in selections:
                result = await tools.execute(
                    ToolCall(
                        name="get_player_stats",
                        question=question,
                        metric=metric,
                        aggregation=aggregation,
                    )
                )
                claims.extend(result.claims)
            expected = {f"{metric}:{aggregation}" for metric, aggregation in selections}
            rows.append(
                {
                    "question": question,
                    "expected_metrics": sorted(expected),
                    "direct_claims": [{"metric": c.metric_id, "value": c.value} for c in claims],
                    "coverage": [c.coverage_limitations for c in claims],
                    "direct_passed": {c.metric_id for c in claims} == expected,
                }
            )
    if live:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", timeout=60
            ) as client:
                for row in rows:
                    response = await client.post(
                        "/analysis/query",
                        json={
                            "question": row["question"],
                            "turn_id": uuid.uuid4().hex,
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    delivered = {
                        c["metadata"]["claim"]["metric_id"]
                        for c in body["citations"]
                        if c.get("metadata", {}).get("claim")
                    }
                    row["api"] = {
                        "answer": body["answer"],
                        "llm_validated": body["llm_validated"],
                        "degraded": body["degraded"],
                        "refused": body["refused"],
                        "state_committed": body["state_committed"],
                        "delivered_metrics": sorted(delivered),
                        "warnings": body["warnings"],
                        "trace": body["tool_calls"],
                        "passed": set(row["expected_metrics"]) <= delivered,
                    }
    return {
        "release": release.version,
        "live": live,
        "cases": rows,
        "passed": all(r["direct_passed"] and (not live or r["api"]["passed"]) for r in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.live))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    for row in result["cases"]:
        print(json.dumps({k: v for k, v in row.items() if k != "api"}))
        if "api" in row:
            print(json.dumps({k: v for k, v in row["api"].items() if k != "trace"}))
    print("PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
