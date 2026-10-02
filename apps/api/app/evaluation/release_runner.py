"""Fixed-cohort execution and explicit semantic review, never phrase matching.

This internal runner uses the real ASGI analyst path and its ContextVar capture.
It does not add an HTTP diagnostics endpoint. Production-derived artifacts stay
at the caller's private local destination. Gold and owner approval precede runs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.evaluation.trace_capture import capture_turn
from app.evaluation.verification_adapter import MODEL, CountedRun
from app.services.release_evidence import evaluation_request_id

SCORING_VERSION = "release-review-v1"
QUESTIONS = Path(__file__).with_name("questions.jsonl")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(contract: dict) -> None:
    original = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    cases = contract.get("cases", [])
    if (
        contract.get("version") != 1
        or contract.get("status") != "frozen"
        or contract.get("scoring_version") != SCORING_VERSION
        or contract.get("questions_sha256") != file_hash(QUESTIONS)
        or len(cases) != 120
        or [c["id"] for c in cases] != [q["id"] for q in original]
    ):
        raise ValueError("Missing immutable frozen 120-case contract")
    for case, question in zip(cases, original, strict=True):
        semantic = question["answerable"] and question.get("expected_route") == "retrieval_rag"
        if (
            case["question"] != question["question"]
            or case.get("context", []) != question.get("context", [])
            or case.get("semantic_member") is not semantic
            or case.get("disposition") not in {"answer", "clarify", "refuse"}
            or case.get("decision_status") != "settled"
            or not case.get("decision_basis")
            or (semantic and not case.get("semantic_targets"))
            or (case.get("disposition") == "answer" and not case.get("facts"))
        ):
            raise ValueError(f"Unresolved or changed expectation: {case['id']}")


def load_contract(path: Path, approval_path: Path) -> dict:
    contract = json.loads(path.read_text())
    validate_contract(contract)
    approval = json.loads(approval_path.read_text())
    if (
        not approval.get("owner")
        or not approval.get("approved_at")
        or approval.get("expectations_sha256") != file_hash(path)
    ):
        raise ValueError("Missing explicit hash-bound owner evaluation approval")
    return contract


def _mean(values: list[float | bool]) -> float | None:
    return statistics.fmean(values) if values else None


def _mapped_sources(mapping: dict, refs: list[str]) -> set[str]:
    sources: set[str] = set()
    for ref in refs:
        value = mapping.get(ref, [])
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError("Invalid canonical source mapping")
        sources.update(values)
    return sources


def _review_assertions(case: dict, observation: dict, assertions: list, mapping: dict) -> bool:
    """Check review provenance; semantic judgments still belong to the reviewer."""
    answer = observation["response"].get("answer", "")
    facts = {digest(fact): fact for fact in case["facts"]}
    cited = {
        citation.get("metadata", {}).get("evidence_id")
        for citation in observation["response"].get("citations", [])
    } - {None}
    covered: set[str] = set()
    last = 0
    if not assertions:
        return False
    for assertion in assertions:
        start, end = assertion.get("start"), assertion.get("end")
        kind = assertion.get("classification")
        refs = assertion.get("canonical_fact_ids", [])
        if (
            type(start) is not int
            or type(end) is not int
            or start != last
            or not start < end <= len(answer)
            or kind not in {"factual", "clarification", "refusal", "nonfactual"}
            or not isinstance(refs, list)
            or any(not isinstance(ref, str) for ref in refs)
        ):
            return False
        last = end
        if kind != "factual":
            if refs:
                return False
            continue
        receipts = assertion.get("citation_evidence_ids", [])
        if (
            not refs
            or not set(refs) <= facts.keys()
            or not isinstance(receipts, list)
            or not receipts
            or any(not isinstance(ref, str) for ref in receipts)
            or not set(receipts) <= cited
            or any(ref not in mapping for ref in receipts)
        ):
            return False
        sources = _mapped_sources(mapping, receipts)
        if any(
            not sources.intersection(facts[ref].get("canonical_evidence_ids", [])) for ref in refs
        ):
            return False
        covered.update(refs)
    return last == len(answer) and (case["disposition"] != "answer" or covered == facts.keys())


def score_reviewed(
    contract: dict, observations: list, reviews: list, mapping: dict, mode: str
) -> dict:
    """Aggregate independently recorded, output-bound per-assertion reviews.

    Reviewers must inspect meaning, typed facts, scope and expanded receipts.
    Booleans without a complete bound assertion review are not accepted labels.
    Unknown/unreviewed cases remain in the appropriate fixed denominators.
    """
    validate_contract(contract)
    ids = [c["id"] for c in contract["cases"]]
    if mode not in {"primary", "disabled", "shadow"}:
        raise ValueError("Unknown evaluation mode")
    by_id = {o["case_id"]: o for o in observations}
    reviewed = {r["case_id"]: r for r in reviews}
    if len(by_id) != len(observations) or set(by_id) != set(ids):
        raise ValueError("Observations must cover exactly the original 120 cases")
    if len(reviewed) != len(reviews) or not set(reviewed) <= set(ids):
        raise ValueError("Duplicate or foreign reviews")
    numeric, entities, citations, paraphrase, abstention, clarify, refuse, recall = (
        [] for _ in range(8)
    )
    failures, missing, missing_traces = [], 0, 0
    for case in contract["cases"]:
        observation = by_id[case["id"]]
        review = reviewed.get(case["id"], {})
        assertions = review.get("assertions", [])
        complete_spans = _review_assertions(case, observation, assertions, mapping)
        valid = (
            review.get("observation_sha256") == digest(observation)
            and bool(review.get("reviewer"))
            and bool(review.get("rationale"))
            and review.get("actual_disposition") in {"answer", "clarify", "refuse"}
            and all(
                type(review.get(k)) is bool
                for k in (
                    "numeric_correct",
                    "entity_correct",
                    "citation_correct",
                    "paraphrase_correct",
                    "unsupported_assertions",
                )
            )
            and complete_spans
        )
        missing += not valid
        outcome_ok = valid and review["actual_disposition"] == case["disposition"]
        supported = valid and not review["unsupported_assertions"]
        if case["disposition"] == "answer":
            for scores, key in [
                (numeric, "numeric_correct"),
                (entities, "entity_correct"),
                (citations, "citation_correct"),
                (paraphrase, "paraphrase_correct"),
            ]:
                scores.append(bool(outcome_ok and supported and review.get(key)))
        else:
            hit = bool(outcome_ok and supported)
            abstention.append(hit)
            (clarify if case["disposition"] == "clarify" else refuse).append(hit)
        searches = observation.get("capture", {}).get("searches", [])
        if case["semantic_member"]:
            # Use only actual analyst searches. Missing retrieval stays a zero, never N/A.
            ranked = list(
                dict.fromkeys(ref for s in searches for ref in s.get("returned_evidence_ids", []))
            )[:5]
            candidates = list(
                dict.fromkeys(ref for s in searches for ref in s.get("candidate_evidence_ids", []))
            )[:20]
            absent = not ranked or not candidates
            missing_traces += absent
            relevant = set(case["semantic_targets"])
            resolved = _mapped_sources(mapping, ranked)
            recall.append(len(relevant & resolved) / len(relevant) if not absent else 0)
        if not valid or not outcome_ok or not supported:
            failures.append(
                {
                    "case_id": case["id"],
                    "review_valid": bool(valid),
                    "outcome_correct": bool(outcome_ok),
                    "supported": bool(supported),
                }
            )
    return {
        "scoring_version": SCORING_VERSION,
        "mode": mode,
        "metrics": {
            "query_count": 120,
            "semantic_case_count": 50,
            "missing_labels": missing,
            "missing_ranked_traces": missing_traces,
            "semantic_recall_at_5": _mean(recall) if mode != "disabled" else None,
            "exact_numeric_correctness": _mean(numeric),
            "canonical_entity_correctness": _mean(entities),
            "citation_correctness": _mean(citations),
            "paraphrase_success": _mean(paraphrase),
            "correct_abstention_rate": _mean(abstention),
            "correct_clarification_rate": _mean(clarify),
            "correct_refusal_rate": _mean(refuse),
        },
        "failures": failures,
    }


async def collect(
    contract_path: Path,
    approval_path: Path,
    output: Path,
    mode: str,
    *,
    execution: CountedRun | None = None,
) -> dict:
    """No paid mode is possible without an installed counted verification wrapper."""
    from app.api import analysis
    from app.core.config import get_settings
    from app.main import create_app
    from app.services import analyst_loop

    if output.exists():
        raise FileExistsError("Refusing to overwrite existing evaluation evidence")
    contract = load_contract(contract_path, approval_path)
    initial = file_hash(contract_path)
    settings = get_settings()
    database = urlsplit(settings.effective_db_url)
    if database.hostname not in {None, "127.0.0.1", "localhost"} and (
        mode == "disabled" or execution is None
    ):
        raise ValueError("Hosted databases require explicit counted isolation verification")
    if mode not in {"primary", "shadow", "disabled"}:
        raise ValueError("Unknown execution mode")
    request_ids = [evaluation_request_id(initial, mode, c["id"]) for c in contract["cases"]]
    shadow_membership = (
        [analysis._sample_shadow(request_id, 0.1) for request_id in request_ids]
        if mode == "shadow"
        else []
    )
    identity = {
        "mode": mode,
        "database": {
            "scheme": database.scheme,
            "host": database.hostname,
            "port": database.port,
            "name": database.path.removeprefix("/"),
        },
        "expectations_sha256": initial,
        "request_ids": request_ids,
        "shadow_membership": shadow_membership,
    }
    starting_requests = 0
    if mode != "disabled":
        if execution is None:
            raise ValueError(
                "Paid execution requires verified accounting and a counted provider wrapper"
            )
        if (
            settings.ai_chat_model != MODEL
            or settings.openrouter_monthly_cutoff_usd != 2
            or settings.analysis_answer_mode != ("llm_primary" if mode == "primary" else "shadow")
            or (mode == "shadow" and settings.analysis_shadow_sample_rate != 0.1)
            or not settings.analyst_evidence_loop_enabled
            or settings.sentry_dsn
        ):
            raise ValueError(
                "Evaluation configuration differs from authorized model, budget or mode"
            )
        execution.check()
        if mode == "shadow" and execution.budget.request_cap("shadow") != 6 * sum(
            shadow_membership
        ):
            raise ValueError("Journal shadow cap differs from fixed sampler membership")
        starting_requests = execution.budget.snapshot()["stages"][mode]["requests"]
        await execution.verify_environment(identity)
    elif (
        execution is not None
        or settings.rag_qdrant_enabled
        or settings.redis_url
        or settings.ai_provider not in {"none", "disabled"}
        or not settings.analyst_evidence_loop_enabled
        or settings.sentry_dsn
    ):
        raise ValueError("Disabled mode requires Qdrant, Redis and provider disabled")

    def denied(**_kwargs):
        raise RuntimeError("Paid call forbidden in disabled evaluation")

    original_adapter = analyst_loop.get_llm_adapter
    original_legacy_adapter = analysis.get_llm_adapter

    def counted(**_kwargs):
        assert execution is not None
        return execution.adapter(mode, settings.ai_reasoning_effort)

    observations: list[dict] = []
    result = {
        "status": "in_progress",
        "mode": mode,
        "expectations_sha256": initial,
        "approval_sha256": file_hash(approval_path),
        "runner_sha256": file_hash(Path(__file__)),
        "configuration": {
            name: getattr(settings, name)
            for name in (
                "test_mode",
                "analysis_answer_mode",
                "analysis_shadow_sample_rate",
                "analyst_evidence_loop_enabled",
                "rag_qdrant_enabled",
                "rag_archive_source_units_enabled",
                "ai_provider",
                "public_chat_rate_limit_per_minute",
                "public_chat_rate_limit_per_day",
            )
        },
        "workload": "120 independent synthetic clients; one fixed case per client",
        "paid_requests": 0,
        "request_ids": request_ids,
        "shadow_membership": shadow_membership,
        "shadow_selected_count": sum(shadow_membership),
        "observations": observations,
    }
    # Exclusive creation preserves earlier attempts. Incremental snapshots retain
    # every completed observation even when a later request fails.
    with output.open("x") as artifact:
        json.dump(result, artifact, indent=2)

    def persist():
        if execution is not None:
            result["accounting"] = execution.budget.snapshot()
            result["paid_requests"] = (
                result["accounting"]["stages"][mode]["requests"] - starting_requests
            )
        output.write_text(json.dumps(result, indent=2) + "\n")

    try:
        analyst_loop.get_llm_adapter = counted if execution is not None else denied
        analysis.get_llm_adapter = denied
        app = create_app()
        for index, case in enumerate(contract["cases"]):
            request_id = request_ids[index]
            if execution is not None:
                execution.check()
            # These in-process clients have independent quotas, just as distinct
            # users do. Limits are exercised unchanged; no forwarded IP header
            # or rate-limit reset is used. This is a cohort run, not a load test.
            synthetic_client = f"192.0.2.{index + 1}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app, client=(synthetic_client, 12345)),
                base_url="https://test",
                timeout=35,
            ) as client:
                with capture_turn() as capture:
                    start = time.monotonic()
                    response = await client.post(
                        "/analysis/query",
                        json={
                            "question": case["question"],
                            "season": "2025-26",
                            "context": case.get("context", []),
                            "turn_id": request_id,
                            "expected_revision": 0,
                        },
                        headers={"x-request-id": request_id},
                    )
                    observations.append(
                        {
                            "case_id": case["id"],
                            "request_id": request_id,
                            "synthetic_client": synthetic_client,
                            "http_status": response.status_code,
                            "response": response.json(),
                            "capture": capture,
                            "latency_ms": (time.monotonic() - start) * 1000,
                        }
                    )
                persist()
                response.raise_for_status()
                if execution is not None:
                    execution.check()
        if (
            file_hash(contract_path) != initial
            or file_hash(approval_path) != result["approval_sha256"]
        ):
            raise ValueError("Expectations or approval changed during evaluation")
        result["status"] = "captured_pending_semantic_review"
    except BaseException as exc:
        result["status"] = "failed"
        result["error_type"] = type(exc).__name__
        raise
    finally:
        analyst_loop.get_llm_adapter = original_adapter
        analysis.get_llm_adapter = original_legacy_adapter
        persist()
    return result


def score_artifact(
    contract_path: Path,
    approval_path: Path,
    observations_path: Path,
    reviews_path: Path,
    mapping_path: Path,
    output: Path,
    mode: str,
) -> dict:
    """Produce local metrics with all review inputs bound, without running inference."""
    if output.exists():
        raise FileExistsError("Refusing to overwrite existing evaluation evidence")
    paths = {
        "contract": contract_path,
        "approval": approval_path,
        "observations": observations_path,
        "reviews": reviews_path,
        "mapping": mapping_path,
    }
    hashes = {key: file_hash(path) for key, path in paths.items()}
    contract = load_contract(contract_path, approval_path)
    captured = json.loads(observations_path.read_text())
    if (
        captured.get("status") != "captured_pending_semantic_review"
        or captured.get("mode") != mode
        or captured.get("expectations_sha256") != hashes["contract"]
        or captured.get("approval_sha256") != hashes["approval"]
    ):
        raise ValueError("Collection status or contract/approval/mode binding mismatch")
    result = score_reviewed(
        contract,
        captured["observations"],
        json.loads(reviews_path.read_text()),
        json.loads(mapping_path.read_text()),
        mode,
    )
    if any(file_hash(path) != hashes[key] for key, path in paths.items()):
        raise ValueError("Scoring input binding changed during review")
    result.update(inputs=hashes, runner_sha256=file_hash(Path(__file__)), status="scored")
    # Scored is not a release-pass assertion. Existing release thresholds and
    # source/candidate/staging identity checks remain separate mandatory gates.
    with output.open("x") as artifact:
        json.dump(result, artifact, indent=2)
        artifact.write("\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["disabled", "primary", "shadow"], required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--mapping", type=Path)
    args = parser.parse_args()
    if any((args.observations, args.reviews, args.mapping)):
        if not all((args.observations, args.reviews, args.mapping)):
            parser.error("Scoring requires observations, reviews and runtime mapping together")
        score_artifact(
            args.contract,
            args.approval,
            args.observations,
            args.reviews,
            args.mapping,
            args.output,
            args.mode,
        )
    else:
        asyncio.run(collect(args.contract, args.approval, args.output, args.mode))


if __name__ == "__main__":
    main()
