#!/usr/bin/env python3
"""Reproduce the Go repair-call ValidationError on the recorded failing questions.

Runs the production HTTP path in-process for the question ids that failed
`failed:revise:ValidationError` in the w4-bench trials, records every provider call
(stage, finish_reason, raw output) under --raw-dir (never in the repo) and writes a
committed summary with the validation error, the failing field paths and the raw
response length. Raw outputs are only kept locally because they contain prompts.

    . /tmp/go.env
    export REDIS_URL=redis://localhost:56500/7
    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/w4-failed/repro_repair.py \
      --trials 1 --out /tmp/w4-failed-before.json --raw-dir /tmp/w4-failed-raw
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import analyst_live_e2e as e2e  # noqa: E402
import app.services.analyst_loop as loop_module  # noqa: E402
import app.services.analyst_provider as provider_module  # noqa: E402
from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

BENCH = ROOT / "docs/release-evidence/llm-primary-20261021/w4-bench"
FAILING_IDS = (
    "date_range_last_n-005",
    "date_range_last_n-008",
    "comparisons-001",
    "comparisons-002",
    "comparisons-005",
    "comparisons-006",
    "comparisons-007",
    "comparisons-008",
    "comparisons-009",
    "comparisons-010",
    "single_game_narrative-004",
    "single_game_narrative-006",
    "single_game_narrative-009",
    "turning_points-002",
    "turning_points-003",
    "turning_points-007",
    "aliases_typos-003",
    "unsupported-004",
    "unsupported-006",
    "unsupported-008",
    "unsupported-009",
)

LAST: dict[str, Any] = {}
TRIAL = [0]
CALLS: list[dict[str, Any]] = []
FAILURES: list[dict[str, Any]] = []


class RecordingAdapter:
    """Delegates to the production adapter and keeps the raw reply locally."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "inner":
            object.__setattr__(self, name, value)
        else:
            setattr(self.inner, name, value)

    async def generate(self, *, system: str, user: str) -> str:
        try:
            raw = await self.inner.generate(system=system, user=user)
        except Exception as exc:
            LAST.update(
                {
                    "raw": None,
                    "error": repr(exc),
                    "meta": self.inner.last_metadata,
                    "system": system,
                    "user": user,
                }
            )
            raise
        LAST.update(
            {
                "raw": raw,
                "error": None,
                "meta": dict(self.inner.last_metadata),
                "system": system,
                "user": user,
            }
        )
        return raw


_ORIGINAL = loop_module.request_model


async def recorded_request_model(loop: Any, schema: type, **kwargs: Any) -> Any:
    stage = (
        "review" if kwargs.get("review") else "revise" if kwargs.get("repair") else "orchestrate"
    )
    started = time.monotonic()
    try:
        value = await _ORIGINAL(loop, schema, **kwargs)
    except Exception as exc:
        entry = {
            "question": loop.tools.question,
            "stage": stage,
            "schema": schema.__name__,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "raw": LAST.get("raw"),
            "raw_error": LAST.get("error"),
            "system": LAST.get("system"),
            "user": LAST.get("user"),
            "meta": LAST.get("meta") or {},
            "repair_reason": (kwargs.get("repair") or "")[:2000],
            "proposed_answer": (
                kwargs["answer"].model_dump(mode="json") if kwargs.get("answer") else None
            ),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        FAILURES.append(entry)
        trace = (loop.trace[-1] if loop.trace else {}) or {}
        CALLS.append(
            {
                "trial": TRIAL[0],
                "question": loop.tools.question,
                "stage": stage,
                "schema": schema.__name__,
                "error_type": type(exc).__name__,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "format_echo": trace.get("provider_format_echo"),
                "finish_reason": trace.get("finish_reason"),
                "completion_tokens": trace.get("completion_tokens"),
            }
        )
        raise
    trace = (loop.trace[-1] if loop.trace else {}) or {}
    CALLS.append(
        {
            "trial": TRIAL[0],
            "question": loop.tools.question,
            "stage": stage,
            "schema": schema.__name__,
            "error_type": None,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "format_echo": trace.get("provider_format_echo"),
            "finish_reason": trace.get("finish_reason"),
            "completion_tokens": trace.get("completion_tokens"),
            "raw": LAST.get("raw"),
        }
    )
    return value


def patch() -> None:
    adapter_factory = provider_module.get_llm_adapter
    provider_module.get_llm_adapter = lambda **kwargs: RecordingAdapter(  # type: ignore[assignment]
        adapter_factory(**kwargs)
    )
    loop_module.request_model = recorded_request_model  # type: ignore[assignment]


async def clear_answer_cache() -> None:
    from app.core.config import get_settings
    from redis.asyncio import Redis

    settings = get_settings()
    if not settings.redis_url:
        return
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        keys = [key async for key in redis.scan_iter(match="answer:*", count=500)]
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


def write_raw(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    by_schema: dict[str, int] = {}
    with (raw_dir / "failures.jsonl").open("w") as handle:
        for item in FAILURES:
            schema = item["schema"]
            index = by_schema.get(schema, 0)
            by_schema[schema] = index + 1
            raw = item.get("raw")
            if raw is not None:
                path = raw_dir / f"{schema}-{index}.txt"
                path.write_text(raw)
                item["raw_path"] = str(path)
            if item.get("system") is not None:
                prompt = raw_dir / f"{schema}-{index}.prompt.txt"
                prompt.write_text(str(item.get("system")) + "\n\n" + str(item.get("user")))
                item["prompt_path"] = str(prompt)
            item.pop("system", None)
            item.pop("user", None)
            handle.write(json.dumps(item) + "\n")
    (raw_dir / "calls.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in CALLS))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=Path("/tmp/w4-failed-raw"))
    parser.add_argument("--ids", default="", help="comma-separated question ids (default: all)")
    args = parser.parse_args()

    patch()
    cases = {row["id"]: row for row in e2e.load_cases(e2e.QUESTIONS)}
    wanted = [item for item in args.ids.split(",") if item] or list(FAILING_IDS)
    picked = [cases[question_id] for question_id in wanted]
    app = create_app()
    rows: list[dict[str, Any]] = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=90.0) as client:
            for trial in range(args.trials):
                TRIAL[0] = trial
                await clear_answer_cache()
                for case in picked:
                    capture = e2e.FailureCapture()
                    root = logging.getLogger()
                    root.addHandler(capture)
                    failures_before = len(FAILURES)
                    started = time.monotonic()
                    try:
                        response = await client.post(
                            "/analysis/query",
                            json={
                                "question": case["question"],
                                "season": "2025-26",
                                "turn_id": "repro-" + uuid.uuid4().hex,
                                "expected_revision": 0,
                            },
                        )
                        body = response.json() if response.status_code == 200 else {}
                    finally:
                        root.removeHandler(capture)
                    outcome = e2e.classify(body, capture.records) if body else "http"
                    rows.append(
                        {
                            "trial": trial,
                            "id": case["id"],
                            "category": case["category"],
                            "question": case["question"],
                            "outcome": outcome,
                            "latency_ms": round((time.monotonic() - started) * 1000),
                            "answer": body.get("answer") or "",
                            "citations": body.get("citations") or [],
                            "refused": body.get("refused", False),
                            "warnings": body.get("warnings") or [],
                            "llm_validated": body.get("llm_validated", False),
                            "validation_errors": [
                                {
                                    "stage": item["stage"],
                                    "schema": item["schema"],
                                    "error": item["error"],
                                    "raw_bytes": len(item["raw"] or ""),
                                    "finish_reason": (item["meta"] or {}).get("finish_reason"),
                                    "completion_tokens": (
                                        ((item["meta"] or {}).get("usage") or {}).get(
                                            "completion_tokens"
                                        )
                                    ),
                                }
                                for item in FAILURES[failures_before:]
                            ],
                        }
                    )
                    print(
                        f"trial={trial} {case['id']} {outcome} "
                        f"errors={len(FAILURES) - failures_before}",
                        flush=True,
                    )
    write_raw(args.raw_dir)
    repair_calls = sum(1 for call in CALLS if call["stage"] == "revise")
    repair_failures = sum(
        1 for item in FAILURES if item["stage"] == "revise" and item["schema"] == "ProposedAnswer"
    )
    repair_echoes = sum(
        1 for call in CALLS if call["stage"] == "revise" and call.get("format_echo")
    )
    per_trial = {}
    for trial in range(args.trials):
        trial_rows = [row for row in rows if row["trial"] == trial]
        repairs = [call for call in CALLS if call["trial"] == trial and call["stage"] == "revise"]
        per_trial[str(trial + 1)] = {
            "turns": len(trial_rows),
            "failed_repair_validation": sum(
                1 for row in trial_rows if row["outcome"] == "failed:revise:ValidationError"
            ),
            "repair_calls": len(repairs),
            "repair_validation_failures": sum(
                1 for call in repairs if call["error_type"] == "ValidationError"
            ),
            "format_echoes": sum(1 for call in repairs if call.get("format_echo")),
        }
    summary = {
        "questions": len(picked),
        "trials": args.trials,
        "outcomes": {
            outcome: sum(1 for row in rows if row["outcome"] == outcome)
            for outcome in sorted({row["outcome"] for row in rows})
        },
        "repair_calls": repair_calls,
        "repair_validation_failures": repair_failures,
        "repair_failure_rate": round(repair_failures / repair_calls, 4) if repair_calls else None,
        "repair_format_echoes": repair_echoes,
        "per_trial": per_trial,
        "other_validation_failures": [
            {
                "question": item["question"],
                "stage": item["stage"],
                "schema": item["schema"],
                "error": item["error"][:500],
            }
            for item in FAILURES
            if not (item["stage"] == "revise" and item["schema"] == "ProposedAnswer")
        ],
        "rows": rows,
    }
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    responses = args.out.with_suffix(".responses.jsonl")
    responses.write_text(
        "".join(
            json.dumps(
                {
                    key: row[key]
                    for key in (
                        "trial",
                        "id",
                        "category",
                        "question",
                        "outcome",
                        "answer",
                        "citations",
                        "refused",
                        "warnings",
                        "llm_validated",
                    )
                }
            )
            + "\n"
            for row in rows
        )
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))


asyncio.run(main())
