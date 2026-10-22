#!/usr/bin/env python3
"""Measure the reviewer's supported-without-ids rate and correlate it with provider and payload.

Three modes:

- live: send the same question set through the in-process app with the real provider, twice,
  retrying provider-level failures. Review recording is the existing
  tools/release/analyst_review_record.py monkeypatch, imported, not duplicated.
- replay: re-send recorded reviewer payloads N times without the writer, recording the
  upstream provider, finish reason and raw verdict of every call. This is how the review-call
  sample grows past the question budget.
- correlate: read recorded live/replay JSONL and emit the correlation table.

    DB_URL=... REDIS_URL=redis://localhost:56500/2 ANALYSIS_ANSWER_MODE=llm_primary \
    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/revids/probe.py live --trials 2 --tag base

No model output is written from application code; recording is a monkeypatch that exists only
in the harness (analyst_review_record.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_DAY", "1000000")
os.environ.setdefault("ANALYSIS_ANSWER_MODE", "llm_primary")
os.environ.setdefault("ANALYST_EVIDENCE_LOOP_ENABLED", "true")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "release"))

import analyst_review_record as recorder  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.services.analyst_provider import (  # noqa: E402
    configure_reviewer,
    encoded,
    get_llm_adapter,
    reviewer_system_prompt,
)
from app.services.evidence_contracts import AnswerReview  # noqa: E402
from pydantic import ValidationError  # noqa: E402

QUESTIONS = ROOT / "apps/api/app/evaluation/questions.jsonl"
IDS = (
    "exact_statistics-001,exact_statistics-002,exact_statistics-005,exact_statistics-006,"
    "exact_statistics-008,exact_statistics-010,exact_statistics-014,exact_statistics-017,"
    "exact_statistics-024,date_range_last_n-001,date_range_last_n-002,date_range_last_n-004,"
    "date_range_last_n-005,date_range_last_n-010,date_range_last_n-013,comparisons-002,"
    "comparisons-008,comparisons-015,single_game_narrative-001,single_game_narrative-006"
)


def failed(outcome: str) -> bool:
    return outcome.startswith("failed:")


def load_questions(ids: str) -> list[dict[str, Any]]:
    wanted = {item.strip() for item in ids.split(",") if item.strip()}
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    return [row for row in rows if row["id"] in wanted]


async def run_trial(
    rows: list[dict[str, Any]], attempts: int, pause: float
) -> list[dict[str, Any]]:
    got: list[dict[str, Any]] = []
    pending = list(rows)
    for attempt in range(attempts):
        if not pending:
            break
        if attempt:
            await asyncio.sleep(pause * attempt)
        batch = await recorder.run(pending)
        done = {item["id"] for item in batch if not failed(item["outcome"])}
        got = [item for item in got if item["id"] not in done] + [
            item for item in batch if item["id"] in done
        ]
        pending = [row for row in rows if row["id"] not in {item["id"] for item in got}]
        print(
            json.dumps({"attempt": attempt, "done": len(got), "pending": len(pending)}),
            flush=True,
        )
    return got


async def live(args: argparse.Namespace) -> None:
    rows = load_questions(args.ids)
    results: list[dict[str, Any]] = []
    for trial in range(args.trials):
        batch = await run_trial(rows, args.attempts, args.pause)
        for item in batch:
            item["trial"] = trial
        results += batch
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for item in results:
            handle.write(json.dumps(item) + "\n")
    summary = {
        "tag": args.tag,
        "questions": len(rows),
        "trials": args.trials,
        "turns": len(results),
        "outcomes": {
            key: sum(item["outcome"] == key for item in results)
            for key in sorted({item["outcome"] for item in results})
        },
    }
    print(json.dumps(summary, indent=2))


async def call_reviewer(payload: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    adapter = get_llm_adapter()
    configure_reviewer(adapter, get_settings())
    adapter.max_tokens = max_tokens
    adapter.timeout_seconds = 30
    if hasattr(adapter, "response_schema"):
        adapter.response_schema = None
    if hasattr(adapter, "reasoning_effort"):
        adapter.reasoning_effort = "none"
    started = time.monotonic()
    try:
        raw = await asyncio.wait_for(
            adapter.generate(system=reviewer_system_prompt(), user=encoded(payload)), timeout=30
        )
    except Exception as exc:
        return {
            "error": f"{type(exc).__name__}: {exc}"[:2000],
            "metadata": dict(getattr(adapter, "last_metadata", None) or {}),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
    metadata = dict(getattr(adapter, "last_metadata", None) or {})
    row: dict[str, Any] = {
        "raw": raw,
        "metadata": metadata,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "payload_bytes": len(encoded(payload)),
    }
    try:
        row["parsed"] = AnswerReview.model_validate_json(raw).model_dump(mode="json")
    except ValidationError as exc:
        row["error"] = f"ValidationError: {exc}"[:2000]
    return row


def unit_rows(
    record: dict[str, Any], attempt_index: int, attempt: dict[str, Any]
) -> list[dict[str, Any]]:
    payload = attempt.get("payload") or {}
    parsed = attempt.get("parsed")
    if not payload or not parsed:
        return []
    spans = payload.get("review_spans") or []
    return [
        {
            "mode": "live",
            "id": record["id"],
            "category": record.get("category"),
            "trial": record.get("trial"),
            "call": attempt_index,
            "provider": (attempt.get("metadata") or {}).get("provider"),
            "finish_reason": (attempt.get("metadata") or {}).get("finish_reason"),
            "payload_bytes": len(encoded(payload)),
            "claims": len(payload.get("claims") or []),
            "evidence": len(payload.get("evidence") or []),
            "spans": len(spans),
            "answer_chars": len((payload.get("proposed_answer") or {}).get("text") or ""),
            "assertion": item,
            "span_text": spans[index] if index < len(spans) else item.get("text"),
            "validation": attempt.get("validation"),
        }
        for index, item in enumerate(parsed.get("assertions") or [])
    ]


async def replay(args: argparse.Namespace) -> None:
    records = [json.loads(line) for line in Path(args.records).read_text().splitlines()]
    payloads = []
    for record in records:
        index = 0
        for attempt in record.get("attempts") or []:
            if attempt.get("kind") != "review":
                continue
            index += 1
            if attempt.get("payload") and attempt.get("parsed"):
                payloads.append((record, index - 1, attempt))
    print(json.dumps({"payloads": len(payloads), "trials": args.trials}), flush=True)
    rows: list[dict[str, Any]] = []
    for trial in range(args.trials):
        for record, attempt_index, attempt in payloads:
            for call_attempt in range(args.attempts):
                result = await call_reviewer(attempt["payload"], args.max_tokens)
                error = result.get("error") or ""
                if "402" in error or "429" in error or "AI provider request failed" in error:
                    await asyncio.sleep(args.pause * (call_attempt + 1))
                    continue
                result.update(
                    {
                        "mode": "replay",
                        "id": record["id"],
                        "category": record.get("category"),
                        "record_trial": record.get("trial"),
                        "trial": trial,
                        "call": attempt_index,
                        "recorded_provider": (attempt.get("metadata") or {}).get("provider"),
                        "claim_count": len((attempt.get("payload") or {}).get("claims") or []),
                        "span_count": len((attempt.get("payload") or {}).get("review_spans") or []),
                    }
                )
                rows.append(result)
                print(
                    json.dumps(
                        {
                            "id": record["id"],
                            "trial": trial,
                            "provider": (result.get("metadata") or {}).get("provider"),
                            "parsed": "parsed" in result,
                        }
                    ),
                    flush=True,
                )
                break
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for item in rows:
            handle.write(json.dumps(item) + "\n")
    print(json.dumps({"calls": len(rows)}, indent=2))


def span_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        item = json.loads(line)
        if "attempts" in item:
            # tools/release/analyst_review_record.py output: one record per question.
            for call, attempt in enumerate(item.get("attempts") or []):
                if attempt.get("kind") != "review" or not attempt.get("parsed"):
                    continue
                payload = attempt.get("payload") or {}
                spans = payload.get("review_spans") or []
                for index, assertion in enumerate(attempt["parsed"].get("assertions") or []):
                    rows.append(
                        {
                            "mode": "live",
                            "source": path.stem,
                            "id": item["id"],
                            "category": item.get("category"),
                            "trial": item.get("trial"),
                            "call": call,
                            "provider": (attempt.get("metadata") or {}).get("provider"),
                            "finish_reason": (attempt.get("metadata") or {}).get("finish_reason"),
                            "payload_bytes": len(encoded(payload)),
                            "claims": len(payload.get("claims") or []),
                            "evidence": len(payload.get("evidence") or []),
                            "spans": len(spans),
                            "answer_chars": len(
                                (payload.get("proposed_answer") or {}).get("text") or ""
                            ),
                            "assertion": assertion,
                            "span_text": spans[index]
                            if index < len(spans)
                            else assertion.get("text"),
                            "validation": attempt.get("validation"),
                        }
                    )
            continue
        if item.get("mode") == "live":
            rows.append(item)
            continue
        if "parsed" not in item:
            continue
        spans = item.get("span_count") or 0
        for _index, assertion in enumerate(item["parsed"].get("assertions") or []):
            rows.append(
                {
                    "mode": "replay",
                    "source": path.stem,
                    "id": item["id"],
                    "category": item.get("category"),
                    "trial": item.get("trial"),
                    "call": item.get("call"),
                    "provider": (item.get("metadata") or {}).get("provider"),
                    "finish_reason": (item.get("metadata") or {}).get("finish_reason"),
                    "payload_bytes": item.get("payload_bytes"),
                    "claims": item.get("claim_count"),
                    "evidence": None,
                    "spans": spans,
                    "answer_chars": None,
                    "assertion": assertion,
                    "span_text": None,
                    "validation": None,
                }
            )
    return rows


def bucket(value: int | None, edges: list[int]) -> str:
    if value is None:
        return "unknown"
    for edge in edges:
        if value <= edge:
            return f"<={edge}"
    return f">{edges[-1]}"


def correlate(args: argparse.Namespace) -> None:
    rows: list[dict[str, Any]] = []
    for path in args.records:
        rows += span_rows(Path(path))
    rows = [
        row
        for row in rows
        if row["assertion"].get("assertion_type") in {"factual", "interpretation"}
    ]
    for row in rows:
        assertion = row["assertion"]
        row["target"] = bool(
            assertion.get("verdict") == "supported"
            and not assertion.get("supporting_claim_ids")
            and not assertion.get("supporting_evidence_ids")
        )
    calls = {}
    for row in rows:
        key = (row["mode"], row["source"], row["id"], row["trial"], row["call"])
        calls.setdefault(key, {**row, "spans": 0, "hits": 0})
        calls[key]["spans"] += 1
        calls[key]["hits"] += int(row["target"])
    call_rows = list(calls.values())
    hit_calls = sum(1 for row in call_rows if row["hits"])
    total_spans = len(rows)
    hit_spans = sum(row["target"] for row in rows)

    def table(key: str, values: list[str] | None = None) -> list[dict[str, Any]]:
        out = []
        groups = values or sorted({str(row.get(key)) for row in call_rows})
        for value in groups:
            selected = [row for row in call_rows if str(row.get(key)) == value]
            if not selected:
                continue
            out.append(
                {
                    key: value,
                    "calls": len(selected),
                    "calls_with_empty_ids": sum(1 for row in selected if row["hits"]),
                    "call_rate": round(
                        sum(1 for row in selected if row["hits"]) / len(selected), 3
                    ),
                    "factual_spans": sum(row["spans"] for row in selected),
                    "empty_id_spans": sum(row["hits"] for row in selected),
                }
            )
        return out

    for key, edges in (
        ("payload_bytes", [5000, 8000, 11000]),
        ("claims", [1, 2, 3]),
        ("spans", [1, 2, 3, 4]),
        ("answer_chars", [200, 400, 800]),
    ):
        for row in call_rows:
            row[key + "_bucket"] = bucket(row.get(key), edges)
    summary: dict[str, Any] = {
        "records": [str(path) for path in args.records],
        "review_calls": len(call_rows),
        "calls_with_empty_ids": hit_calls,
        "call_rate": round(hit_calls / len(call_rows), 3) if call_rows else None,
        "factual_spans": total_spans,
        "empty_id_spans": hit_spans,
        "span_rate": round(hit_spans / total_spans, 3) if total_spans else None,
        "by_provider": table("provider"),
        "by_finish_reason": table("finish_reason"),
        "by_payload_bytes": table("payload_bytes_bucket"),
        "by_claims": table("claims_bucket"),
        "by_spans": table("spans_bucket"),
        "by_answer_chars": table("answer_chars_bucket"),
        "by_mode": table("mode"),
        "empty_id_calls": [
            {
                "mode": row["mode"],
                "source": row["source"],
                "id": row["id"],
                "provider": row["provider"],
                "finish_reason": row["finish_reason"],
                "assertion_type": row["assertion"].get("assertion_type"),
            }
            for row in rows
            if row["target"]
        ],
    }
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    live_parser = sub.add_parser("live")
    live_parser.add_argument("--trials", type=int, default=2)
    live_parser.add_argument("--attempts", type=int, default=4)
    live_parser.add_argument("--pause", type=float, default=15)
    live_parser.add_argument("--ids", default=IDS)
    live_parser.add_argument("--tag", default="run")
    live_parser.add_argument("--out", type=Path, required=True)
    replay_parser = sub.add_parser("replay")
    replay_parser.add_argument("--records", type=Path, required=True)
    replay_parser.add_argument("--trials", type=int, default=3)
    replay_parser.add_argument("--attempts", type=int, default=4)
    replay_parser.add_argument("--pause", type=float, default=10)
    replay_parser.add_argument("--max-tokens", type=int, default=3000)
    replay_parser.add_argument("--out", type=Path, required=True)
    corr = sub.add_parser("correlate")
    corr.add_argument("--records", nargs="+", type=Path, required=True)
    corr.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.mode == "live":
        asyncio.run(live(args))
    elif args.mode == "replay":
        asyncio.run(replay(args))
    else:
        correlate(args)


if __name__ == "__main__":
    main()
