#!/usr/bin/env python3
"""Record live reviewer calls so review behaviour can be replayed without the writer.

Each artifact line is one question and contains every reviewer attempt from that turn: the exact
system prompt and user payload the provider received, the raw response, the parsed review, the
backend validation outcome, and the writer answer plus the complete claims and evidence the
reviewer could see. Nothing is written from application code; recording is a monkeypatch that
exists only in this harness.

Requires the local restored release, a disposable Redis database, and the real provider:

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
    REDIS_URL=redis://localhost:56500/11 \
    ANALYST_EVIDENCE_LOOP_ENABLED=true ANALYSIS_ANSWER_MODE=llm_primary \
    uv run --package knicksiq-api python tools/release/analyst_review_record.py \
      --ids exact_statistics-001,exact_statistics-002 --out /tmp/reviews.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_DAY", "1000000")
os.environ.setdefault("ANALYSIS_ANSWER_MODE", "llm_primary")
os.environ.setdefault("ANALYST_EVIDENCE_LOOP_ENABLED", "true")

import app.services.analyst_provider as provider_module  # noqa: E402
from app.services.analyst_loop import AnalystLoop  # noqa: E402

QUESTIONS = Path(__file__).resolve().parents[2] / "apps/api/app/evaluation/questions.jsonl"

SINK: list[dict[str, Any]] = []
ATTEMPTS: list[dict[str, Any]] = []


class RecordingAdapter:
    """Delegate to the real adapter and retain the exact provider input and output."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "inner", inner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.inner, name, value)

    async def generate(self, *, system: str, user: str) -> str:
        raw = await self.inner.generate(system=system, user=user)
        SINK.append(
            {
                "system": system,
                "user": user,
                "raw": raw,
                "metadata": dict(getattr(self.inner, "last_metadata", None) or {}),
                "max_tokens": getattr(self.inner, "max_tokens", None),
                "has_response_schema": getattr(self.inner, "response_schema", None) is not None,
            }
        )
        return raw


_original_adapter = provider_module.get_llm_adapter
provider_module.get_llm_adapter = lambda *args, **kwargs: RecordingAdapter(
    _original_adapter(*args, **kwargs)
)

_original_model = AnalystLoop.model


async def recording_model(
    self: AnalystLoop,
    schema: type,
    *,
    review: bool = False,
    answer: Any = None,
    repair: str | None = None,
    timeout_seconds: float | None = None,
) -> Any:
    entry: dict[str, Any] | None = None
    start = len(SINK)
    if review:
        reviewable = dict(self.sent_evidence)
        for claim in self.sent_claims.values():
            for ref in claim.supporting_evidence_ids:
                if ref in self.tools.evidence:
                    reviewable.setdefault(ref, self.tools.evidence[ref])
        entry = {
            "kind": "review",
            "question": self.tools.question,
            "answer": answer.model_dump(mode="json") if answer else None,
            "claims": {
                key: claim.model_dump(mode="json") for key, claim in self.sent_claims.items()
            },
            "evidence": {
                key: evidence.model_dump(mode="json") for key, evidence in reviewable.items()
            },
            "candidates": {
                key: candidate.model_dump(mode="json")
                for key, candidate in self.sent_candidates.items()
            },
        }
    try:
        value = await _original_model(
            self,
            schema,
            review=review,
            answer=answer,
            repair=repair,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        if not review:
            calls = SINK[start:]
            ATTEMPTS.append(
                {
                    "kind": "writer",
                    "stage": "repair" if repair else "orchestrate",
                    "error": f"{type(exc).__name__}: {exc}"[:2000],
                    "raw": calls[-1]["raw"] if calls else None,
                    "system": calls[-1]["system"] if calls else None,
                }
            )
        else:
            calls = SINK[start:]
            entry = entry or {"kind": "review", "question": self.tools.question}
            entry["error"] = f"{type(exc).__name__}: {exc}"[:2000]
            if calls:
                entry["system"], entry["payload"] = (
                    calls[-1]["system"],
                    json.loads(calls[-1]["user"]),
                )
                entry["raw"] = calls[-1]["raw"]
                entry["metadata"] = calls[-1]["metadata"]
                entry["max_tokens"] = calls[-1]["max_tokens"]
                entry["has_response_schema"] = calls[-1]["has_response_schema"]
            ATTEMPTS.append(entry)
        raise
    if entry is not None:
        calls = SINK[start:]
        if calls:
            entry["system"], entry["payload"] = calls[-1]["system"], json.loads(calls[-1]["user"])
            entry["raw"] = calls[-1]["raw"]
            entry["metadata"] = calls[-1]["metadata"]
            entry["max_tokens"] = calls[-1]["max_tokens"]
            entry["has_response_schema"] = calls[-1]["has_response_schema"]
        entry["parsed"] = value.model_dump(mode="json")
        ATTEMPTS.append(entry)
    return value


AnalystLoop.model = recording_model  # type: ignore[method-assign]

_original_validate = AnalystLoop.validate


async def recording_validate(
    self: AnalystLoop, answer: Any, *, timeout_seconds: float | None = None
) -> tuple[bool, str]:
    result = await _original_validate(self, answer, timeout_seconds=timeout_seconds)
    if not result[0] and (
        result[1].startswith("Invalid claim value")
        or result[1].startswith("Deterministic evidence check failed")
    ):
        ATTEMPTS.append(
            {
                "kind": "structure"
                if result[1].startswith("Invalid claim value")
                else "deterministic",
                "question": self.tools.question,
                "answer": answer.model_dump(mode="json"),
                "claims": {
                    key: claim.model_dump(mode="json") for key, claim in self.sent_claims.items()
                },
                "capabilities": self.tools.manifest(),
                "validation": False,
                "validation_reason": result[1],
            }
        )
    elif ATTEMPTS and ATTEMPTS[-1].get("answer") == answer.model_dump(mode="json"):
        ATTEMPTS[-1]["validation"] = result[0]
        ATTEMPTS[-1]["validation_reason"] = result[1]
        ATTEMPTS[-1]["accepted_suggestions"] = list(self.accepted_suggestions)
    return result


AnalystLoop.validate = recording_validate  # type: ignore[method-assign]


class FailureCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "analyst_execution_failed" in record.getMessage():
            self.records.append(
                {
                    "error_type": getattr(record, "error_type", None),
                    "stage": getattr(record, "stage", None),
                }
            )


def load_questions(ids: list[str], category: str | None, limit: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    if ids:
        wanted = set(ids)
        return [row for row in rows if row["id"] in wanted]
    picked = [row for row in rows if category is None or row["category"] == category]
    return picked[:limit]


def classify(body: dict[str, Any], failures: list[dict[str, Any]]) -> str:
    if body.get("llm_validated"):
        return "validated"
    if failures:
        return f"failed:{failures[-1]['stage']}:{failures[-1]['error_type']}"
    warnings = " ".join(body.get("warnings") or [])
    if "evidence review" in warnings:
        return "fallback:review_rejected"
    if "could not be verified" in warnings:
        return "fallback:unverified"
    return "fallback:other"


async def run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    capture = FailureCapture()
    logging.getLogger().addHandler(capture)
    output: list[dict[str, Any]] = []
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            for row in rows:
                capture.records.clear()
                ATTEMPTS.clear()
                SINK.clear()
                response = await client.post(
                    "/analysis/query",
                    json={
                        "question": row["question"],
                        "season": "2025-26",
                        "turn_id": "review-" + uuid.uuid4().hex,
                        "expected_revision": 0,
                    },
                )
                body = response.json() if response.status_code == 200 else {}
                attempt_views = []
                for attempt in ATTEMPTS:
                    attempt_views.append(
                        {key: value for key, value in attempt.items() if key != "question"}
                    )
                output.append(
                    {
                        "id": row["id"],
                        "category": row["category"],
                        "question": row["question"],
                        "answerable": row["answerable"],
                        "http_status": response.status_code,
                        "outcome": classify(body, capture.records),
                        "answer": body.get("answer") or "",
                        "warnings": body.get("warnings") or [],
                        "citations": len(body.get("citations") or []),
                        "attempts": attempt_views,
                        "provider_calls": len(SINK),
                    }
                )
                print(
                    json.dumps(
                        {
                            "id": row["id"],
                            "outcome": output[-1]["outcome"],
                            "attempts": len(attempt_views),
                        }
                    ),
                    flush=True,
                )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default="")
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=999)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = load_questions(
        [item.strip() for item in args.ids.split(",") if item.strip()], args.category, args.limit
    )
    if not rows:
        raise SystemExit("No questions selected")
    output = asyncio.run(run(rows))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in output))
    print(
        json.dumps(
            {
                "questions": len(output),
                "outcomes": {
                    name: sum(row["outcome"] == name for row in output)
                    for name in {row["outcome"] for row in output}
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
