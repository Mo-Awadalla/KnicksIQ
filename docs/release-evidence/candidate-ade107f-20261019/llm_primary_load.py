"""Ten concurrent llm_primary analyst turns with distinct questions, measured end to end.

tools/release/stress.py sends no turn_id, so the API treats it as a legacy client and never calls
the model. This probe sends a turn_id, so every request takes the model path.

    python llm_primary_load.py --base-url http://localhost:8000 --output OUT.json
"""

import argparse
import asyncio
import json
import math
import time
import uuid

import httpx

QUESTIONS = [
    "How many total points did the Knicks score?",
    "How many home games did the Knicks win?",
    "How many road games did the Knicks win?",
    "What was the Knicks average margin?",
    "How many games did the Knicks lose?",
    "What was the Knicks record in their last 5 games?",
    "What was Jalen Brunson's scoring average?",
    "Who led the Knicks in assists?",
    "How did the Knicks perform from January 1 through January 31?",
    "What was the Knicks worst loss by margin?",
]


def p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


async def run(args: argparse.Namespace) -> dict:
    latencies, outcomes, errors = [], [], []
    async with httpx.AsyncClient(base_url=args.base_url, timeout=90) as client:

        async def turn(question: str) -> None:
            body = {
                "question": question,
                "season": "2025-26",
                "turn_id": "load-" + uuid.uuid4().hex,
                "expected_revision": 0,
            }
            start = time.perf_counter()
            try:
                response = await client.post("/analysis/query", json=body)
                response.raise_for_status()
                data = response.json()
                outcomes.append(bool(data.get("llm_validated")))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                latencies.append((time.perf_counter() - start) * 1000)

        for _ in range(args.rounds):
            await asyncio.gather(*(turn(q) for q in QUESTIONS))
            await asyncio.sleep(61)
    return {
        "concurrency": len(QUESTIONS),
        "turns": len(latencies),
        "p50_ms": sorted(latencies)[len(latencies) // 2],
        "p95_ms": p95(latencies),
        "max_ms": max(latencies),
        "model_validated": sum(outcomes),
        "error_rate": len(errors) / len(latencies),
        "errors": errors[:5],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    with open(args.output, "w") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
