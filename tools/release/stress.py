"""Measure ten concurrent archive readers and analyst requests against a real API.

Run with the API environment's normal rate limits. The cooldown keeps the
warmup outside the ten-request minute budget of clients sharing one address.
This records observations; it does not approve a release.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


async def run(args: argparse.Namespace) -> dict:
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
    async with httpx.AsyncClient(base_url=args.base_url, headers=headers, timeout=60) as client:
        ready = await client.get("/health/ready")
        ready.raise_for_status()
        identity = await client.get("/archive/status")
        identity.raise_for_status()
        version = identity.json()["data_version"]
        if version != args.data_version:
            raise RuntimeError("Archive version does not match the requested target")
        warmup = await client.post("/analysis/query", json=question)
        warmup.raise_for_status()
        if warmup.json().get("refused") or not warmup.json().get("answer"):
            raise RuntimeError("Analyst warmup did not produce a factual answer")
        print(f"Warmup passed for {version}; waiting 61s for the rate-limit window", flush=True)
        await asyncio.sleep(61)

        async def request(route: str, path: str, payload: dict | None = None) -> None:
            start = time.perf_counter()
            try:
                response = (
                    await client.get(path)
                    if payload is None
                    else await client.post(path, json=payload)
                )
                response.raise_for_status()
                body = response.json()
                if route == "analyst" and (
                    body.get("refused")
                    or not body.get("answer")
                    or not body.get("citations")
                    or body.get("data_version") != version
                ):
                    raise RuntimeError(
                        "Analyst response missing factual answer, citations or version"
                    )
            except Exception as exc:
                errors.append({"route": route, "type": type(exc).__name__, "detail": str(exc)})
            finally:
                samples[route].append((time.perf_counter() - start) * 1000)

        deadline = time.monotonic() + args.duration

        async def archive_reader() -> None:
            while time.monotonic() < deadline:
                await request("archive", "/archive/status")
                await asyncio.sleep(0.1)

        await asyncio.gather(
            *(archive_reader() for _ in range(10)),
            *(request("analyst", "/analysis/query", item) for item in analyst_questions),
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
            "Ten distinct factual analyst questions with archive readers; clear cache required"
            if args.distinct_questions
            else "Warm cached analyst response and archive metadata; ten users per scenario"
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
