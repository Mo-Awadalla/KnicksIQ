"""Requires approval when the API uses a paid provider.

Run with normal API rate limits. The cooldown keeps warmup outside the
ten-request minute budget of clients sharing one address.
These observations do not approve a release."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import secrets
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from app.evaluation.chat_stream import stream_turn
from app.evaluation.collection_transport import validate_base_url


async def run(args: argparse.Namespace) -> dict:
    validate_base_url(args.base_url)
    headers = {"X-Forwarded-Proto": "https"} if args.local_https_proxy else {}
    samples: dict[str, list[float]] = {"archive": [], "analyst": []}
    errors: list[dict] = []
    question = {"question": "What was the Knicks record this season?", "season": "2025-26"}
    analyst_questions = [question] * 10
    if args.distinct_questions:
        analyst_questions = [
            {"question": value, "season": "2025-26"}
            for value in (
                "How many total points did the Knicks score?",
                "How many home games did the Knicks win?",
                "How many road games did the Knicks win?",
                "What was the Knicks biggest win by margin?",
                "How many games did the Knicks score at least 120?",
                "How many games did the Knicks hold opponents under 100?",
                "What was Jalen Brunson's scoring average?",
                "What was Karl-Anthony Towns' rebounding average?",
                "Who led the Knicks in assists?",
                "What was Mikal Bridges' three-point percentage?",
            )
        ]
    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, timeout=60, trust_env=False, follow_redirects=False
    ) as client:
        ready = await client.get("/health/ready")
        ready.raise_for_status()
        identity = await client.get("/health/ready")
        identity.raise_for_status()
        version = identity.json()["data_version"]
        if version != args.data_version:
            raise RuntimeError("Archive version does not match the requested target")
        warmup, _ = await stream_turn(
            client,
            {
                "kind": "message",
                "message": question["question"],
                "request_id": str(uuid.uuid4()),
                "expected_revision": 0,
            },
            secrets.token_urlsafe(32),
        )
        if warmup["status"] != "complete":
            raise RuntimeError("Chat warmup did not complete")
        print(f"Warmup passed for {version}; waiting 61s for the rate-limit window", flush=True)
        await asyncio.sleep(61)

        async def request(route: str, path: str, payload: dict | None = None) -> None:
            start = time.perf_counter()
            try:
                if payload is None:
                    response = await client.get(path)
                    response.raise_for_status()
                else:
                    body, _ = await stream_turn(
                        client,
                        {
                            "kind": "message",
                            "message": payload["question"],
                            "request_id": str(uuid.uuid4()),
                            "expected_revision": 0,
                        },
                        secrets.token_urlsafe(32),
                    )
                    if body["status"] != "complete" or not body["text"]:
                        raise RuntimeError("Chat did not complete")
            except Exception as exc:
                errors.append({"route": route, "type": type(exc).__name__, "detail": str(exc)})
            finally:
                samples[route].append((time.perf_counter() - start) * 1000)

        deadline = time.monotonic() + args.duration

        async def archive_reader() -> None:
            while time.monotonic() < deadline:
                await request("archive", "/health/ready")
                await asyncio.sleep(0.1)

        await asyncio.gather(
            *(archive_reader() for _ in range(10)),
            *(request("analyst", "/chat/turns", item) for item in analyst_questions),
        )

    def p95(values: list[float]) -> float:
        return sorted(values)[math.ceil(len(values) * 0.95) - 1]

    count = sum(map(len, samples.values()))
    metrics = {
        "concurrency": 10,
        "archive_p95_ms": p95(samples["archive"]),
        "analyst_p95_ms": p95(samples["analyst"]),
        "error_rate": len(errors) / count,
        "requests": count,
        "analyst_requests": len(samples["analyst"]),
    }
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "data_version": version,
        "readiness": ready.json(),
        "scope": (
            "Ten distinct chat questions with readiness readers"
            if args.distinct_questions
            else (
                "Ten fresh chat sessions and readiness readers; "
                "legacy latency metric names retained"
            )
        ),
        "metrics": metrics,
        "errors": errors,
        "passed": metrics["archive_p95_ms"] < 1000
        and metrics["analyst_p95_ms"] < 4000
        and not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--data-version", required=True)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-https-proxy", action="store_true")
    parser.add_argument("--distinct-questions", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
