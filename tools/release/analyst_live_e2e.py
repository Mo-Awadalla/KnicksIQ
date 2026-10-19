"""End-to-end check of the llm_primary analyst against a real provider and a restored release.

Runs candidate questions through the in-process FastAPI app (same code path as production) and
records, per question, whether the model's answer was validated or fell back, and why.
Needs a loaded and activated release (DB_URL), Redis with the monthly ledger (REDIS_URL), and
the provider settings (AI_*, ANALYSIS_ANSWER_MODE=llm_primary). Never contacts Qdrant.

    uv run --package knicksiq-api python tools/release/analyst_live_e2e.py --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import re
import uuid
from pathlib import Path

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

QUESTIONS = Path(__file__).resolve().parents[2] / "apps/api/app/evaluation/questions.jsonl"


class FailureCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if "analyst_execution_failed" in record.getMessage():
            self.records.append(
                {
                    "error_type": getattr(record, "error_type", None),
                    "stage": getattr(record, "stage", None),
                }
            )


class Trace:
    """Per-question record of every model call and the first exception that ended the turn."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: dict | None = None

    def reset(self) -> None:
        self.calls, self.error = [], None


TRACE = Trace()
RAW_LIMIT = 1500


class RecordingAdapter:
    """Wraps the provider adapter to keep what the model was sent and what it returned."""

    def __init__(self, inner):
        object.__setattr__(self, "inner", inner)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __setattr__(self, name, value):
        setattr(self.inner, name, value)

    async def generate(self, **kwargs):
        from app.services.analyst_loop import _claim_choice_domains

        if os.environ.get("E2E_SCHEMA_SCOPE") == "writer" and "review_spans" in kwargs["user"]:
            # Experiment knob: keep provider schema enforcement for the writer, not the reviewer.
            self.inner.response_schema = None
        record: dict = {
            "kind": "review" if "review_spans" in kwargs["user"] else "writer",
            "system_bytes": len(kwargs["system"].encode()),
            "user_bytes": len(kwargs["user"].encode()),
            "schema_enforced": getattr(self.inner, "response_schema", None) is not None,
        }
        try:
            payload = json.loads(kwargs["user"])
            required = payload.get("required_claim_indexes")
            if required:
                slots, related = _claim_choice_domains(payload)
                record["slots"] = [
                    {"claims": len(claims), "choices": len(choices)}
                    for claims, choices in zip(required, slots, strict=True)
                ]
                record["related_choices"] = len(related)
                record["claim_uses"] = len(payload.get("claim_uses") or [])
        except (ValueError, TypeError, KeyError):
            record["payload_unreadable"] = True
        TRACE.calls.append(record)
        try:
            raw = await self.inner.generate(**kwargs)
        except Exception as exc:
            record["provider_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            raise
        meta = getattr(self.inner, "last_metadata", {}) or {}
        record.update(provider=meta.get("provider"), model=meta.get("model"), raw=raw[:RAW_LIMIT])
        record["raw_bytes"] = len(raw.encode())
        return raw


def install_tracing() -> None:
    from app.services import analyst_loop

    real_get = analyst_loop.get_llm_adapter
    analyst_loop.get_llm_adapter = lambda *a, **k: RecordingAdapter(real_get(*a, **k))
    real_investigate = analyst_loop.AnalystLoop.investigate

    async def investigate(self, *args, **kwargs):
        try:
            return await real_investigate(self, *args, **kwargs)
        except Exception as exc:
            TRACE.error = {"type": type(exc).__name__, "message": str(exc)[:500]}
            raise

    analyst_loop.AnalystLoop.investigate = investigate


def sample(per_category: int, ids: set[str]) -> list[dict]:
    rows = [json.loads(line) for line in QUESTIONS.read_text().splitlines()]
    if ids:
        return [row for row in rows if row["id"] in ids]
    seen: collections.Counter[str] = collections.Counter()
    picked = []
    for row in rows:
        if row["category"] == "follow_ups":
            continue
        if seen[row["category"]] < per_category:
            seen[row["category"]] += 1
            picked.append(row)
    return picked


DECLINE = re.compile(
    r"\b(i can(?:'|’)?t|i cannot|i do(?:n't| not) have|"
    r"can(?:'|’)?t (?:give|provide|answer|predict|verify)|"
    r"cannot (?:give|provide|answer|predict)|not able to|unable to|do(?:es)? not (?:include|"
    r"cover|contain)|doesn(?:'|’)?t (?:include|cover|contain)|no (?:live|future|current))",
    re.I,
)


CLARIFY = re.compile(r"\b(which|do you mean|should i use|did you mean)\b[^?]*\?", re.I)


def classify(body: dict, failures: list[dict]) -> str:
    answer = body.get("answer") or ""
    kind = (
        "declined"
        if DECLINE.search(answer)
        else "clarification"
        if CLARIFY.search(answer)
        else "answer"
    )
    if body.get("llm_validated"):
        return "validated" if kind == "answer" else f"validated_{kind}"
    if failures:
        return f"failed:{failures[-1]['stage']}:{failures[-1]['error_type']}"
    warnings = " ".join(body.get("warnings") or [])
    if "evidence review" in warnings:
        return "fallback:review_rejected"
    if "could not be verified" in warnings:
        return "fallback:unverified"
    return f"deterministic_{kind}"


def meets_expectation(row: dict, outcome: str) -> bool:
    """Answerable questions need a substantive answer; unsupported ones a decline.

    A clarification meets neither, so it is counted on its own.
    """
    if row["answerable"]:
        return outcome in {"validated", "deterministic_answer"}
    return outcome.endswith("_declined")


async def run(per_category: int, ids: set[str], repeat: int) -> dict:
    capture = FailureCapture()
    logging.getLogger().addHandler(capture)
    install_tracing()
    app = create_app()
    results = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as client:
            for row in sample(per_category, ids) * repeat:
                capture.records.clear()
                TRACE.reset()
                response = await client.post(
                    "/analysis/query",
                    json={
                        "question": row["question"],
                        "season": "2025-26",
                        "turn_id": "e2e-" + uuid.uuid4().hex,
                        "expected_revision": 0,
                    },
                )
                body = response.json() if response.status_code == 200 else {}
                outcome = (
                    classify(body, capture.records) if body else f"http_{response.status_code}"
                )
                results.append(
                    {
                        "id": row["id"],
                        "category": row["category"],
                        "answerable": row["answerable"],
                        "question": row["question"],
                        "outcome": outcome,
                        "error": TRACE.error,
                        "model_calls": TRACE.calls,
                        "meets_expectation": meets_expectation(row, outcome),
                        "answer": body.get("answer") or "",
                        "citations": len(body.get("citations") or []),
                        "warnings": body.get("warnings") or [],
                    }
                )
    by_outcome = collections.Counter(item["outcome"] for item in results)
    by_category: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for item in results:
        by_category[item["category"]]["meets_expectation"] += item["meets_expectation"]
        by_category[item["category"]]["questions"] += 1
    met = sum(item["meets_expectation"] for item in results)
    return {
        "scope": "llm_validated is reviewer acceptance. meets_expectation also requires a "
        "substantive answer for answerable questions and a decline for unsupported ones. "
        "Expectations come from unreviewed draft labels.",
        "questions": len(results),
        "meets_expectation": met,
        "meets_expectation_rate": round(met / len(results), 3),
        "outcomes": dict(by_outcome),
        "by_category": {k: dict(v) for k, v in by_category.items()},
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument(
        "--ids", default="", help="comma-separated question ids; overrides sampling"
    )
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    report = asyncio.run(
        run(args.per_category, set(filter(None, args.ids.split(","))), args.repeat)
    )
    results = report.pop("results")
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    responses = args.out.with_suffix(".responses.jsonl")
    responses.write_text("".join(json.dumps(item) + "\n" for item in results))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
