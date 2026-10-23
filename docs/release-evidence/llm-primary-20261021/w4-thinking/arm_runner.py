"""Run one arm of the reasoning experiment on the fixed 30-question sample.

Arms differ only by environment variables; this script changes no application file. It reuses
the w4-bench runner (`bench_runner.run`) so outcomes, honest scores, priced ledger and stage
latency are computed by exactly the same code as the 70-question benchmark, then adds the
per-call usage the raw-body parser cannot see on the Responses API: normalized token counts,
reasoning tokens, finish reason and content kind.

Usage:
    uv run --package knicksiq-api python arm_runner.py --arm A --out-dir arm-A

The environment must already carry the production Go settings (`/tmp/go.env`) plus the arm's
overrides; see run.sh.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "w4-bench"
sys.path.insert(0, str(BENCH))

import bench_runner as br  # noqa: E402  (patches pricing + rate limits on import)
import app.services.report_llm as report_llm  # noqa: E402
from app.core.config import get_settings  # noqa: E402

e2e = br.e2e
_PREVIOUS_GENERATE = report_llm.OpenAICompatibleLLMAdapter.generate
EXTRA: list[dict[str, Any]] = []


async def _capture(self: Any, *, system: str, user: str) -> str:
    """Record the adapter's own normalized metadata for every attempt, failed or not."""
    row: dict[str, Any] = {"error": None}
    try:
        return await _PREVIOUS_GENERATE(self, system=system, user=user)
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
        row["error"] = type(exc).__name__
        raise
    finally:
        metadata = getattr(self, "last_metadata", {}) or {}
        usage = metadata.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        row.update(
            {
                "requested_model": self.model,
                "served_model": metadata.get("model"),
                "protocol": metadata.get("protocol"),
                "max_tokens": metadata.get("max_tokens"),
                "finish_reason": metadata.get("finish_reason"),
                "content_kind": metadata.get("content_kind"),
                "reasoning_chars": metadata.get("reasoning_chars"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                "usage_cost_usd": usage.get("cost"),
                "http_ttfb_ms": metadata.get("http_ttfb_ms"),
                "http_elapsed_ms": metadata.get("http_elapsed_ms"),
                "raw_usage": usage,
            }
        )
        EXTRA.append(row)


report_llm.OpenAICompatibleLLMAdapter.generate = _capture


def pick_cases(sample: Path) -> list[dict[str, Any]]:
    wanted = [row["id"] for row in json.loads(sample.read_text())]
    cases = {case["id"]: case for case in e2e.load_cases(e2e.QUESTIONS)}
    missing = [identifier for identifier in wanted if identifier not in cases]
    if missing:
        raise SystemExit(f"unknown ids in sample: {missing}")
    return [cases[identifier] for identifier in wanted]


def arm_summary(rows: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [
        {**call, **extra}
        for call, extra in zip(calls, EXTRA, strict=False)
    ]
    by_stage: dict[str, dict[str, Any]] = {}
    for call in normalized:
        stage = call.get("stage") or "unknown"
        bucket = by_stage.setdefault(
            stage,
            {
                "calls": 0,
                "reasoning_tokens": 0,
                "calls_with_reasoning": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "finish_reasons": {},
                "content_kinds": {},
                "max_tokens_seen": [],
                "errors": 0,
            },
        )
        bucket["calls"] += 1
        reasoning = call.get("reasoning_tokens")
        if reasoning:
            bucket["reasoning_tokens"] += int(reasoning)
            bucket["calls_with_reasoning"] += 1
        bucket["prompt_tokens"] += int(call.get("prompt_tokens") or 0)
        bucket["completion_tokens"] += int(call.get("completion_tokens") or 0)
        finish = str(call.get("finish_reason"))
        bucket["finish_reasons"][finish] = bucket["finish_reasons"].get(finish, 0) + 1
        kind = str(call.get("content_kind"))
        bucket["content_kinds"][kind] = bucket["content_kinds"].get(kind, 0) + 1
        if call.get("max_tokens"):
            bucket["max_tokens_seen"].append(call["max_tokens"])
        if call.get("error"):
            bucket["errors"] += 1
    for bucket in by_stage.values():
        bucket["max_tokens_seen"] = sorted(set(bucket["max_tokens_seen"]))
    outcomes: dict[str, int] = {}
    for row in rows:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "calls": len(normalized),
        "calls_with_extra": len(EXTRA),
        "by_stage": by_stage,
        "outcomes": outcomes,
        "truncated_calls": sum(
            1 for call in normalized if str(call.get("finish_reason")) == "length"
        ),
        "empty_output_calls": sum(
            1
            for call in normalized
            if str(call.get("content_kind")) in {"empty_string", "null", "None"}
            and not call.get("error")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=["A", "B", "C"])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sample", type=Path, default=HERE / "sample.json")
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()
    settings = get_settings()
    picked = pick_cases(args.sample)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"arm={args.arm} questions={len(picked)} trials={args.trials} "
        f"ai_reasoning_effort={settings.ai_reasoning_effort} "
        f"analyst_reasoning_effort={settings.analyst_reasoning_effort} "
        f"answer_max_tokens={settings.analyst_answer_max_tokens} "
        f"review_max_tokens={settings.analyst_review_max_tokens} "
        f"redis_db={os.environ.get('REDIS_URL', '').rsplit('/', 1)[-1]}",
        flush=True,
    )
    measured = asyncio.run(br.run(picked, args.trials))
    br.write_artifacts(
        args.out_dir, measured["rows"], measured["calls"], measured["ledger"], args.trials
    )
    extra = arm_summary(measured["rows"], measured["calls"])
    normalized = ([{**call, **item} for call, item in zip(measured["calls"], EXTRA, strict=False)])
    (args.out_dir / "calls_normalized.jsonl").write_text(
        "".join(json.dumps(row, default=str) + "\n" for row in normalized)
    )
    metrics = json.loads((args.out_dir / "metrics.json").read_text())
    metrics["arm"] = args.arm
    metrics["settings"] = {
        "ai_reasoning_effort": settings.ai_reasoning_effort,
        "analyst_reasoning_effort": settings.analyst_reasoning_effort,
        "analyst_answer_max_tokens": settings.analyst_answer_max_tokens,
        "analyst_review_max_tokens": settings.analyst_review_max_tokens,
        "ai_model_protocols": dict(settings.ai_model_protocols),
        "ai_chat_model": settings.ai_chat_model,
        "analyst_review_model": settings.analyst_review_model,
        "analyst_deadline_seconds": settings.analyst_deadline_seconds,
        "ai_request_timeout_seconds": settings.ai_request_timeout_seconds,
    }
    metrics["arm_extra"] = extra
    (args.out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps({"arm": args.arm, **extra}, indent=2))


if __name__ == "__main__":
    main()
