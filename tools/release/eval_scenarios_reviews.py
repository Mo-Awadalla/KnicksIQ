"""Disposition independence, submission-shape and reviewer-decision scenarios."""

from __future__ import annotations

import hashlib
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
    disposition_response,
    observation,
)
from eval_scenario_support import digest, expect, failures, metric


def scenario_disposition_separation(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations.append(observation("clarify-001", disposition_response("answer")))
    observations = [row for index, row in enumerate(observations) if index != 58]
    refused = [row for row in observations if row["case_id"] == "refuse-001"][0]
    refused["response"] = disposition_response("clarify")
    refused["response_sha256"] = digest(refused["response"])
    missing = [row for row in observations if row["case_id"] == "clarify-002"][0]
    missing["response"] = disposition_response("clarify")
    missing["response"].pop("outcome")
    missing["response_sha256"] = digest(missing["response"])
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(
        "disposition_mismatch" in failures(report, "clarify-001"),
        "answering a clarification must fail",
        problems,
    )
    expect(
        "disposition_mismatch" in failures(report, "refuse-001"),
        "clarifying instead of refusing must fail",
        problems,
    )
    expect("outcome_missing" in failures(report, "clarify-002"), "missing outcome fails", problems)
    expect(
        metric(report, "clarification_accuracy")["denominator"] == 53,
        "clarification denominator 53",
        problems,
    )
    expect(
        metric(report, "refusal_accuracy")["denominator"] == 9,
        "refusal denominator 9",
        problems,
    )
    expect(
        metric(report, "correct_abstention")["denominator"] == 62,
        "abstention denominator 62",
        problems,
    )
    return problems


def scenario_independence_from_flags(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    response = answer_response(game=103, value=61)
    response.update(degraded=True, refused=True, route=None)
    observations[0] = observation("answer-001", response)
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(failures(report, "answer-001") == [], "degraded/refused flags must not decide", problems)
    return problems


def scenario_missing_and_duplicate_observations(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations = [row for row in observations if row["case_id"] != "answer-010"]
    observations.append(observations[0])
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(
        "cases_missing" in report["profile"]["failures"],
        "missing case must be explicit",
        problems,
    )
    expect(
        "duplicate_observation" in report["profile"]["failures"],
        "duplicate observation must be explicit",
        problems,
    )
    expect(
        metric(report, "canonical_numeric_correctness")["denominator"] == 58,
        "denominator fixed at 58 despite missing case",
        problems,
    )
    expect(
        "answer-010" not in [case["id"] for case in report["cases"] if case["status"] == "pass"],
        "missing case must not pass",
        problems,
    )
    return problems


def scenario_provider_trace_in_disabled_run(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    response = answer_response(game=103, value=61)
    response["tool_calls"].append(
        {"stage": "orchestrate", "tool": "llm_orchestrate", "latency_ms": 900}
    )
    observations[0] = observation("answer-001", response)
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
        extra=["--profile", "disabled"],
    )
    expect(result.returncode != 0, "a provider call under the disabled profile must fail", problems)
    return problems


def scenario_review_decisions(directory: Path) -> list[str]:
    """A complete, bound review for all 120 cases is what makes any metric measured."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is not None:
        expect(
            metric(report, "answer_quality")["status"] == "blocked",
            "missing reviewed decisions must block answer quality",
            problems,
        )
        expect(
            metric(report, "disposition_accuracy")["status"] == "blocked",
            "dispositions are not scored before all 120 responses are reviewed",
            problems,
        )
        codes = {item["code"] for item in report["blockers"]}
        expect("labels_not_frozen" in codes, "an unfrozen label set blocks", problems)
        expect(
            "labels_approval_unverified" in codes,
            "an unverified approval artifact is an explicit blocker",
            problems,
        )

    approved = directory / "approved"
    approved.mkdir()
    questions_path, expectations_path = write_dataset(approved, owner_approved=True)
    observations = baseline_observations(synthetic_questions())
    reviews = dump(
        approved / "review-decisions.json",
        review_payload(
            observations,
            questions_path=questions_path,
            expectations_path=expectations_path,
            mapping_path=mapping,
        ),
    )
    result, report = run_score(
        approved,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is not None:
        expect(
            metric(report, "answer_quality")["status"] == "measured",
            "recorded decisions measure answer quality",
            problems,
        )
        expect(
            metric(report, "paraphrase_quality")["status"] == "measured",
            "recorded paraphrase decisions measure paraphrase",
            problems,
        )
        expect(
            metric(report, "disposition_accuracy")["status"] == "measured",
            "a complete bound review measures dispositions",
            problems,
        )
        expect(
            report["dataset"]["owner_approved"] == 120,
            "a verified freeze and approval bind the 120 approved cases",
            problems,
        )
        expect(report["dataset"]["frozen"] is True, "a verified freeze is recorded", problems)
        expect(
            report["gates"]["narrative_recall_at_5"]["status"] == "blocked",
            "approved primary labels do not approve or supply narrative retrieval evidence",
            problems,
        )
        expect(
            report["release_blocked"] is True,
            "a missing narrative benchmark must block the complete release decision",
            problems,
        )
    return problems


def scenario_stale_review_decisions(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory, owner_approved=True)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    reviews = dump(
        directory / "review-decisions.json",
        {
            "schema": "evaluation-review-decisions-v2",
            "evaluation_identity_sha256": "0" * 64,
            "dataset_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
            "reviewer": "scenario-fixture",
            "reviewed_at": "2026-10-30T00:00:00+00:00",
            "notes": "bound to a different evaluation identity",
            "cases": [],
        },
    )
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(
        result.returncode != 0,
        "review decisions bound to other labels must be rejected",
        problems,
    )
    return problems
