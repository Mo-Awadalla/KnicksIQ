"""End-to-end benchmark of the llm_primary analyst against a real provider and a restored release.

Live mode sends benchmark questions through the in-process FastAPI app (same code path as
production) and records, per question, the full response payload, every model call and the first
exception that ended the turn. Offline mode re-scores a committed responses artifact without the
provider. Both modes run the deterministic checks in analyst_scoring.py and write one JSONL row
per question plus a category table.

This is a benchmark, not the formal release evaluation: it never gates a release and its numbers
are not release evidence. The human-reviewed release evaluation lives in app.evaluation
(analyst_evaluation.py, release_runner.py, guarded_release.py).

Both modes need the archive database (DB_URL) for numeric re-scoring. Live runs additionally
need an activated release, Redis with the monthly ledger (REDIS_URL), and provider settings
(AI_*, ANALYSIS_ANSWER_MODE=llm_primary). Offline mode does not call the provider or start the API.

    uv run --package knicksiq-api python tools/release/analyst_live_e2e.py --out report.json
    uv run --package knicksiq-api python tools/release/analyst_live_e2e.py \
        --responses old.responses.jsonl --out rescored.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path

os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["PUBLIC_CHAT_RATE_LIMIT_PER_DAY"] = "1000000"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyst_scoring import score_response  # noqa: E402
from archive_values import build as build_archive_values  # noqa: E402
from archive_values import scoped_corpus

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "apps/api/app/evaluation/benchmark_questions.jsonl"
HELDOUT = ROOT / "apps/api/app/evaluation/heldout_questions.jsonl"


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
_TRACING_INSTALLED = False


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
    """Send every analyst provider call through the recording adapter, once per process."""
    global _TRACING_INSTALLED
    if _TRACING_INSTALLED:
        return
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
    _TRACING_INSTALLED = True


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sample(
    rows: list[dict], per_category: int, all_rows: bool = False, ids: set[str] | None = None
) -> list[dict]:
    """First `per_category` rows of every non-follow-up category, or exactly the requested ids."""
    if ids:
        return [row for row in rows if row["id"] in ids]
    if all_rows:
        return [row for row in rows if row["category"] != "follow_ups"]
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


def old_meets_expectation(case: dict, outcome: str) -> bool:
    """The pre-existing screen, kept only for the old-versus-new gap."""
    if case["answerable"]:
        return outcome == "validated"
    return outcome == "validated_declined"


def meets_expectation(row: dict, outcome: str) -> bool:
    """Coarse outcome screen: answerable questions need a substantive answer.

    Unsupported ones need a decline, so a clarification meets neither and is counted on its own.
    The scored verdict is `score()["meets_expectation"]`; this screen only keeps the per-outcome
    counts comparable with earlier benchmark runs.
    """
    if row["answerable"]:
        return outcome in {"validated", "deterministic_answer"}
    return outcome.endswith("_declined")


def score(case: dict, response: dict, archive) -> dict:
    scoped = scoped_corpus(archive, case.get("question", ""), case, response.get("answer", ""))
    best = score_response(
        case,
        response,
        universe=archive.universe,
        archive=archive,
        scoped=scoped,
        strict=True,
        require_claims=False,
    )
    proof = score_response(
        case,
        response,
        universe=archive.universe,
        archive=archive,
        scoped=scoped,
        strict=True,
        require_claims=True,
    )
    best["claim_backed_meets_expectation"] = proof["meets_expectation"]
    best["claim_backed_failures"] = proof["failures"]
    best["old_meets_expectation"] = bool(
        response.get(
            "old_meets_expectation", old_meets_expectation(case, response.get("outcome", ""))
        )
    )
    return best


async def run_live(cases: list[dict], archive, timeout: float, repeat: int = 1) -> list[dict]:
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    capture = FailureCapture()
    logging.getLogger().addHandler(capture)
    install_tracing()
    app = create_app()
    results = []
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", timeout=timeout
        ) as client:
            for case in list(cases) * repeat:
                capture.records.clear()
                TRACE.reset()
                response = await client.post(
                    "/analysis/query",
                    json={
                        "question": case["question"],
                        "season": "2025-26",
                        "turn_id": "e2e-" + uuid.uuid4().hex,
                        "expected_revision": 0,
                    },
                )
                body = response.json() if response.status_code == 200 else {}
                outcome = (
                    classify(body, capture.records) if body else f"http_{response.status_code}"
                )
                record = {
                    "id": case["id"],
                    "category": case["category"],
                    "answerable": case["answerable"],
                    "question": case["question"],
                    "outcome": outcome,
                    "outcome_meets_expectation": meets_expectation(case, outcome),
                    "old_meets_expectation": old_meets_expectation(case, outcome),
                    "answer": body.get("answer") or "",
                    "citations": body.get("citations") or [],
                    "warnings": body.get("warnings") or [],
                    "refused": body.get("refused", False),
                    "degraded": body.get("degraded", False),
                    "llm_validated": body.get("llm_validated", False),
                    "route": body.get("route"),
                    "follow_up_questions": body.get("follow_up_questions") or [],
                    "tool_calls": body.get("tool_calls") or [],
                    "data_version": body.get("data_version"),
                    "status_code": response.status_code,
                    "error": TRACE.error,
                    "model_calls": TRACE.calls,
                }
                results.append({**record, "score": score(case, record, archive)})
    return results


def run_offline(cases: list[dict], responses_path: Path, archive) -> list[dict]:
    by_id = {case["id"]: case for case in cases}
    results = []
    for line in responses_path.read_text().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        case = by_id.get(raw["id"]) or {
            "id": raw["id"],
            "category": raw["category"],
            "answerable": raw["answerable"],
            "question": raw["question"],
            "required_facts": [],
            "required_entities": [],
            "required_phrases": [],
        }
        reduced = isinstance(raw.get("citations"), int)
        record = {
            **raw,
            "outcome": raw.get("outcome", "unknown"),
            "old_meets_expectation": raw.get(
                "old_meets_expectation",
                raw.get("meets_expectation", old_meets_expectation(case, raw.get("outcome", ""))),
            ),
            "llm_validated": raw.get(
                "llm_validated", str(raw.get("outcome", "")).startswith("validated")
            ),
            "degraded": str(raw.get("outcome", "")).startswith(
                ("fallback", "failed", "http_", "deterministic_")
            ),
            "citations_reduced": reduced,
            "reconstructed_fields": reduced or "llm_validated" not in raw,
        }
        record["outcome_meets_expectation"] = meets_expectation(case, record["outcome"])
        results.append({**record, "score": score(case, record, archive)})
    return results


def summarize(mode: str, dataset: str, results: list[dict]) -> dict:
    by_category: dict[str, dict] = {}
    for item in results:
        score_row = item["score"]
        bucket = by_category.setdefault(
            score_row["category"],
            {"questions": 0, "old": 0, "new": 0, "claim_backed": 0},
        )
        bucket["questions"] += 1
        bucket["old"] += int(score_row["old_meets_expectation"])
        bucket["new"] += int(score_row["meets_expectation"])
        bucket["claim_backed"] += int(score_row["claim_backed_meets_expectation"])
    failures: collections.Counter[str] = collections.Counter()
    for item in results:
        for failure in item["score"]["failures"]:
            failures[failure.split(":")[0]] += 1
    outcomes = collections.Counter(item.get("outcome") or "unknown" for item in results)
    screened = sum(int(item.get("outcome_meets_expectation", 0)) for item in results)
    answerable = [item for item in results if item["score"]["answerable"]]
    unsupported = [item for item in results if not item["score"]["answerable"]]
    old = sum(int(item["score"]["old_meets_expectation"]) for item in results)
    new = sum(int(item["score"]["meets_expectation"]) for item in results)
    backed = sum(int(item["score"]["claim_backed_meets_expectation"]) for item in results)
    return {
        "scope": (
            "Benchmark, never the formal release evaluation. meets_expectation requires: not "
            "declined or clarification, validated delivery, substantive content, no unbacked "
            "number or entity, required facts present, no echo, and no unbacked causal hedge. "
            "claim_backed additionally requires cited claim values. "
            "outcome_meets_expectation is the earlier coarse screen: a validated or deterministic "
            "answer for answerable questions and a decline for unsupported ones. Expectations "
            "come from unreviewed draft labels."
        ),
        "mode": mode,
        "dataset": dataset,
        "questions": len(results),
        "old_meets_expectation": old,
        "meets_expectation": new,
        "claim_backed_meets_expectation": backed,
        "delta": old - new,
        "outcome_meets_expectation": screened,
        "outcome_meets_expectation_rate": round(screened / len(results), 3) if results else 0.0,
        "outcomes": dict(outcomes.most_common()),
        "by_answerable": {
            "answerable": {
                "questions": len(answerable),
                "old": sum(int(item["score"]["old_meets_expectation"]) for item in answerable),
                "new": sum(int(item["score"]["meets_expectation"]) for item in answerable),
            },
            "unsupported": {
                "questions": len(unsupported),
                "old": sum(int(item["score"]["old_meets_expectation"]) for item in unsupported),
                "new": sum(int(item["score"]["meets_expectation"]) for item in unsupported),
            },
        },
        "survived": [
            item["score"]["id"]
            for item in results
            if item["score"]["old_meets_expectation"] and item["score"]["meets_expectation"]
        ],
        "lost": [
            {
                "id": item["score"]["id"],
                "category": item["score"]["category"],
                "failures": item["score"]["failures"],
                "reason": loss_reason(item["score"]["failures"]),
                "answer": item.get("answer", ""),
            }
            for item in results
            if item["score"]["old_meets_expectation"] and not item["score"]["meets_expectation"]
        ],
        "gained": [
            {"id": item["score"]["id"], "failures": item["score"]["failures"]}
            for item in results
            if not item["score"]["old_meets_expectation"] and item["score"]["meets_expectation"]
        ],
        "failure_counts": dict(failures.most_common()),
        "by_category": dict(sorted(by_category.items())),
    }


def loss_reason(failures: list[str]) -> str:
    names = {failure.split(":")[0] for failure in failures}
    if "clarification" in names:
        return "skipped_work_clarification"
    if "declined" in names:
        return "declined_answerable"
    if "unbacked_numbers" in names:
        return "unbacked_number"
    if "unbacked_entities" in names:
        return "wrong_subject"
    if "required_facts" in names or "required_entities" in names or "required_phrases" in names:
        return "missing_required_fact"
    if "missing_turning_detail" in names:
        return "missing_turning_detail"
    if "not_substantive" in names:
        return "not_substantive"
    return "other"


def print_table(summary: dict) -> None:
    print(f"mode={summary['mode']} dataset={summary['dataset']} questions={summary['questions']}")
    print("| Category | Questions | Old | New | Claim-backed |")
    print("| --- | --- | --- | --- | --- |")
    for category, row in summary["by_category"].items():
        print(
            f"| {category} | {row['questions']} | {row['old']} | {row['new']} | "
            f"{row['claim_backed']} |"
        )
    print(
        f"| Total | {summary['questions']} | {summary['old_meets_expectation']} | "
        f"{summary['meets_expectation']} | {summary['claim_backed_meets_expectation']} |"
    )


async def build_archive():
    return await build_archive_values()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--questions", type=Path, default=None)
    parser.add_argument("--heldout", action="store_true", help="use the held-out question set")
    parser.add_argument(
        "--responses", type=Path, help="offline mode: re-score this responses JSONL"
    )
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--all", action="store_true", help="run every question in the set")
    parser.add_argument("--limit", type=int, default=0, help="cap live questions")
    parser.add_argument(
        "--ids", default="", help="comma-separated case ids; overrides live sampling"
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="run each live question this many times"
    )
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    questions = args.questions or (HELDOUT if args.heldout else QUESTIONS)
    cases = load_cases(questions)
    archive = asyncio.run(build_archive())
    wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
    if args.responses:
        results = run_offline(cases, args.responses, archive)
        mode = "offline"
    else:
        picked = sample(cases, args.per_category, args.all, wanted)
        if args.limit:
            picked = picked[: args.limit]
        results = asyncio.run(run_live(picked, archive, args.timeout, args.repeat))
        mode = "live"
    summary = summarize(mode, str(questions), results)
    summary["source"] = str(args.responses) if args.responses else "live in-process API"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    scored = args.out.with_suffix(".scored.jsonl")
    scored.write_text(
        "".join(json.dumps(item["score"]) + "\n" for item in results),
        encoding="utf-8",
    )
    if mode == "live":
        raw = args.out.with_suffix(".responses.jsonl")
        raw.write_text(
            "".join(
                json.dumps({key: value for key, value in item.items() if key != "score"}) + "\n"
                for item in results
            ),
            encoding="utf-8",
        )
    print_table(summary)
    print(f"report: {args.out}")
    print(f"scored: {scored}")


if __name__ == "__main__":
    main()
