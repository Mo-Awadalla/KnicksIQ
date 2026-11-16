"""Collect real chat replies from a loopback API. Requires bounded provider approval.

This records protocol outcomes, never automatically grades conversational quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import uuid
from pathlib import Path

import httpx
from app.evaluation.chat_stream import stream_turn
from app.evaluation.collection_transport import validate_base_url

QUESTIONS = Path(__file__).resolve().parents[2] / "apps/api/app/evaluation/questions.jsonl"


async def run(base_url: str, per_category: int) -> dict:
    validate_base_url(base_url)
    counts, results = {}, []
    async with httpx.AsyncClient(
        base_url=base_url, timeout=60, trust_env=False, follow_redirects=False
    ) as client:
        for line in QUESTIONS.read_text().splitlines():
            row = json.loads(line)
            category = row["category"]
            if counts.get(category, 0) >= per_category:
                continue
            counts[category] = counts.get(category, 0) + 1
            token, revision = secrets.token_urlsafe(32), 0
            context = row.get("context", [])
            messages = [item["content"] for item in context if item["role"] == "user"] + [
                row["question"]
            ]
            turns = []
            try:
                for message in messages:
                    command = {
                        "kind": "message",
                        "request_id": str(uuid.uuid4()),
                        "expected_revision": revision,
                        "message": message,
                    }
                    body, _ = await stream_turn(client, command, token)
                    revision = body["revision"]
                    turns.append({"request": command, "response": body})
                    if body["status"] != "complete":
                        break
                results.append(
                    {"id": row["id"], "category": category, "turns": turns, "human_review": None}
                )
            except (httpx.HTTPError, ValueError) as exc:
                results.append({"id": row["id"], "turns": turns, "error": type(exc).__name__})
    return {
        "scope": "Chat protocol collection; quality and factual attribution require review.",
        "citation_gate": (
            "inapplicable: public citations retired; owner-approved rubric migration pending"
        ),
        "questions": len(results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=5)
    args = parser.parse_args()
    report = asyncio.run(run(args.base_url, args.per_category))
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
