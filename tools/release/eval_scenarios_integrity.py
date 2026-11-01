"""Integrity scenarios: gates, reviews, approvals, immutable labels and request identity."""

from __future__ import annotations

from pathlib import Path

from eval_scenario_fixtures import (
    dump,
    review_payload,
    run_score,
    synthetic_mapping,
    synthetic_questions,
    write_dataset,
)
from eval_scenario_records import (
    answer_response,
    baseline_observations,
    claim,
    observation,
)
from eval_scenario_support import expect, failures, metric


def _reviewed(directory: Path, questions: Path, expectations: Path, mapping: Path):
    import json

    rows = [
        json.loads(line)
        for line in (directory / "responses.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return dump(
        directory / "review-decisions.json",
        review_payload(
            rows,
            questions_path=questions,
            expectations_path=expectations,
            mapping_path=mapping,
        ),
    )


def _score_reviewed(directory: Path, **kwargs):
    questions = kwargs["questions"]
    expectations = kwargs["expectations"]
    mapping = kwargs["mapping"]
    observations = kwargs["observations"]
    from eval_scenario_records import write_observations

    write_observations(directory / "responses.jsonl", observations)
    reviews = _reviewed(directory, questions, expectations, mapping)
    return run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )


def scenario_required_fact_coverage_gated(directory: Path) -> list[str]:
    """Omitting a required claim while keeping another valid receipt must fail the gates."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[4] = observation(
        "answer-005",
        answer_response(game=108, value=66, metric="losses", unit="losses"),
    )
    result, report = _score_reviewed(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    codes = set(failures(report, "answer-005"))
    expect("no_typed_claim_for_fact" in codes, "a missing required claim is explicit", problems)
    expect(
        metric(report, "canonical_numeric_correctness")["value"] < 1.0,
        "the numeric metric cannot pass while a required claim is absent",
        problems,
    )
    expect(
        "gate_failed:canonical_numeric_correctness"
        in {item["code"] for item in report["blockers"]},
        "the failed gate is an explicit blocker",
        problems,
    )
    return problems


def scenario_response_digest_mismatch_not_credited(directory: Path) -> list[str]:
    """A digest mismatch stops that response contributing a passing measurement."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[0]["response_sha256"] = "0" * 64
    result, report = _score_reviewed(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    case = [item for item in report["cases"] if item["id"] == "answer-001"][0]
    expect(case["verified"] is False, "the tampered response is not verified", problems)
    expect(
        "response_hash_mismatch" in [f["code"] for f in case["failures"]], "digest fails", problems
    )
    expect(
        metric(report, "canonical_numeric_correctness")["numerator"] == 57,
        "the tampered case is not counted as passing",
        problems,
    )
    expect(
        metric(report, "disposition_accuracy")["numerator"] == 119,
        "the tampered case earns no disposition credit",
        problems,
    )
    return problems


def scenario_unsupported_review_gates_additions(directory: Path) -> list[str]:
    """A negative human assertion fails the absence-of-unsupported-facts gate."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    from eval_scenario_records import write_observations

    write_observations(directory / "responses.jsonl", observations)
    decisions = review_payload(
        observations,
        questions_path=questions,
        expectations_path=expectations,
        mapping_path=mapping,
    )
    target = next(item for item in decisions["cases"] if item["case_id"] == "answer-003")
    target["assertions"][0]["decision"] = "unsupported"
    target["paraphrase"] = "supported"
    reviews = dump(directory / "review-decisions.json", decisions)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(
        "review_unsupported_assertion" in failures(report, "answer-003"),
        "an unsupported assertion is recorded as a failure",
        problems,
    )
    metric_row = metric(report, "unsupported_additional_fact_rate")
    expect(metric_row["value"] < 1.0, "the additions gate fails", problems)
    expect(
        "gate_failed:unsupported_additional_fact_rate"
        in {item["code"] for item in report["blockers"]},
        "the gate failure blocks release",
        problems,
    )
    return problems


def scenario_unresolved_assertion_blocks(directory: Path) -> list[str]:
    """An insufficient-evidence decision blocks aggregate passing results."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    from eval_scenario_records import write_observations

    write_observations(directory / "responses.jsonl", observations)
    decisions = review_payload(
        observations,
        questions_path=questions,
        expectations_path=expectations,
        mapping_path=mapping,
    )
    target = next(item for item in decisions["cases"] if item["case_id"] == "answer-004")
    target["assertions"][0]["decision"] = "insufficient_evidence"
    reviews = dump(directory / "review-decisions.json", decisions)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "assertion_evidence_unresolved" in {item["code"] for item in report["blockers"]},
        "an unresolved evidence decision blocks",
        problems,
    )
    expect(
        metric(report, "unsupported_additional_fact_rate")["status"] == "blocked",
        "the affected metric is blocked, not measured",
        problems,
    )
    return problems


def scenario_empty_review_assertions_rejected(directory: Path) -> list[str]:
    """An answer review without assertions cannot pass as a review."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    from eval_scenario_records import write_observations

    write_observations(directory / "responses.jsonl", observations)
    decisions = review_payload(
        observations,
        questions_path=questions,
        expectations_path=expectations,
        mapping_path=mapping,
    )
    target = next(item for item in decisions["cases"] if item["case_id"] == "answer-001")
    target["assertions"] = []
    reviews = dump(directory / "review-decisions.json", decisions)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(result.returncode != 0, "an empty answer review is rejected", problems)
    expect("assertion" in result.stderr.lower(), "the error names the missing assertion", problems)
    return problems


def scenario_review_span_not_in_response_rejected(directory: Path) -> list[str]:
    """A reviewed span that the response never contained is not a review of that response."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    from eval_scenario_records import write_observations

    write_observations(directory / "responses.jsonl", observations)
    decisions = review_payload(
        observations,
        questions_path=questions,
        expectations_path=expectations,
        mapping_path=mapping,
    )
    target = next(item for item in decisions["cases"] if item["case_id"] == "answer-002")
    target["assertions"][0]["text"] = "a span the answer never contained"
    reviews = dump(directory / "review-decisions.json", decisions)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    case = [item for item in report["cases"] if item["id"] == "answer-002"][0]
    expect(case["reviewed"] is False, "the review is not bound to this response", problems)
    expect(
        "review_unbound_assertion" in [f["code"] for f in case["failures"]],
        "the unbound span is explicit",
        problems,
    )
    expect(
        metric(report, "answer_quality")["status"] == "blocked",
        "an unbound review leaves quality blocked",
        problems,
    )
    return problems


def scenario_abstention_content_checked(directory: Path) -> list[str]:
    """A clarification with claims and a refusal from a dependency failure earn nothing."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    wrong_clarify = dict(observations[58]["response"])
    wrong_clarify["citations"] = []
    wrong_clarify["outcome"] = "clarify"
    wrong_clarify["answer"] = "Synthetic clarify with a delivered fact."
    wrong_clarify["tool_calls"] = []
    wrong_clarify["citations"] = [
        {
            "claim": "Synthetic wins 61.",
            "type": "verified_claim",
            "title": "Synthetic wins 61.",
            "game_id": 108,
            "source_name": None,
            "source_url": None,
            "metadata": {
                "claim": claim(game=108, value=66),
                "evidence_id": f"{claim(game=108, value=66)['supporting_evidence_ids'][0]}",
            },
        }
    ]
    observations[58] = observation("clarify-001", wrong_clarify)
    failed_refusal = dict(observations[-1]["response"])
    failed_refusal["tool_calls"] = [
        {
            "stage": "retrieval",
            "tool": "archive_retrieval",
            "kind": "retrieval_trace",
            "request_id": observations[-1]["request_id"],
            "data_version": "scenario.1",
            "latency_ms": 5,
            "errors": ["database_unavailable"],
            "lexical": [],
            "dense": [],
            "candidates": [],
            "selected": [],
        }
    ]
    observations[-1] = observation("refuse-009", failed_refusal)
    result, report = _score_reviewed(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(
        "clarification_with_claims" in failures(report, "clarify-001"),
        "a clarification carrying a claim fails",
        problems,
    )
    expect(
        "refusal_dependency_failure" in failures(report, "refuse-009"),
        "a dependency failure presented as refusal fails",
        problems,
    )
    expect(
        metric(report, "correct_abstention")["numerator"] == 60,
        "the two cases earn no abstention credit",
        problems,
    )
    return problems


def scenario_request_identity_required(directory: Path) -> list[str]:
    """A record without its request identity cannot be credited to a case."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    stripped = observations[0]
    stripped.pop("request_id")
    stripped.pop("turn_id")
    stripped["request"] = {}
    observations[0] = stripped
    result, report = _score_reviewed(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    case = [item for item in report["cases"] if item["id"] == "answer-001"][0]
    codes = [failure["code"] for failure in case["failures"]]
    for code in ("request_identity_missing", "turn_identity_missing", "request_id_missing"):
        expect(code in codes, f"{code} is explicit", problems)
    expect(case["verified"] is False, "an unbound response is not verified", problems)
    expect(
        metric(report, "canonical_numeric_correctness")["numerator"] == 57,
        "the unbound response contributes no passing measurement",
        problems,
    )
    return problems


def scenario_request_case_mismatch(directory: Path) -> list[str]:
    """A response is bound to the exact immutable question it was requested with."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[1]["request"] = dict(observations[1]["request"])
    observations[1]["request"]["question"] = observations[0]["request"]["question"]
    result, report = _score_reviewed(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "request_case_mismatch" in failures(report, "answer-002"),
        "a response for another question fails",
        problems,
    )
    return problems
