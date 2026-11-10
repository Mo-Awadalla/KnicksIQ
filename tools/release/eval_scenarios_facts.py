"""Fact, value and attribution scenarios for the evaluation scorer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eval_scenario_fixtures import (
    dump,
    load,
    review_payload,
    run_score,
    synthetic_mapping,
    synthetic_questions,
    synthetic_scoreline,
    write_dataset,
)
from eval_scenario_records import (
    answer_response,
    baseline_observations,
    claim,
    observation,
    receipt_record,
)
from eval_scenario_support import RELEASE, canonical, expect, failures, metric


def scenario_clean(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    reviews = dump(
        directory / "review-decisions.json",
        review_payload(
            observations,
            questions_path=questions_path,
            expectations_path=expectations_path,
            mapping_path=mapping,
        ),
    )
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(report["dataset"]["case_count"] == 120, "case_count must be 120", problems)
    expect(
        report["dataset"]["semantic_case_count"] == 50,
        "semantic_case_count must be 50",
        problems,
    )
    expect(
        metric(report, "disposition_accuracy")["denominator"] == 120,
        "disposition denominator must stay 120",
        problems,
    )
    expect(
        metric(report, "canonical_numeric_correctness")["value"] == 1.0,
        "numeric must be measured and passing",
        problems,
    )
    expect(
        metric(report, "citation_receipt_correctness")["value"] == 1.0,
        "citations must be measured and passing",
        problems,
    )
    expect(
        metric(report, "narrative_recall_at_5")["status"] == "blocked",
        "missing separate narrative evidence blocks, never passes",
        problems,
    )
    expect(
        all(case["reviewed"] for case in report["cases"]),
        "every one of the 120 responses carries a bound review",
        problems,
    )
    expect(report["release_blocked"] is True, "unapproved labels block release", problems)
    expect(
        "labels_owner_unapproved" in {item["code"] for item in report["blockers"]},
        "owner approval blocker must be explicit",
        problems,
    )
    return problems


def scenario_integer_mismatch(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[4] = observation("answer-005", answer_response(game=106, value=64))
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
    expect("numeric_mismatch" in failures(report, "answer-005"), "68 vs 65 must fail", problems)
    expect(metric(report, "canonical_numeric_correctness")["numerator"] == 57, "57/58", problems)
    expect(
        metric(report, "canonical_numeric_correctness")["denominator"] == 58,
        "denominator stays 58",
        problems,
    )
    return problems


def scenario_decimal_display_precision(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] == "answer-001":
            case["proposed_expectation"]["canonical_facts"][0]["value"] = 112.3456
            case["proposed_expectation"]["canonical_facts"][0]["metric"] = "points"
    canonical_rows = [
        canonical(json.loads(line))
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    digest_input = hashlib.sha256(("\n".join(canonical_rows) + "\n").encode()).hexdigest()
    expectations["labels_sha256"] = digest_input
    dump(expectations_path, expectations)
    observations = baseline_observations(synthetic_questions())
    # Displayed to two decimals and rounded accordingly: 112.35 is correct at that precision.
    observations[0] = observation(
        "answer-001",
        answer_response(game=103, value=112.35, metric="points", unit="points", text="112.35 wins"),
    )
    observations[5] = observation("answer-006", answer_response(game=108, value=60 + 6))
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
        "numeric_mismatch" not in failures(report, "answer-001"),
        "112.35 at 2dp passes",
        problems,
    )
    return problems


def scenario_extra_claim(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    extra = claim(game=103, value=61, metric="rebounds", subject="player:114", unit="rebounds")
    observations[1] = observation(
        "answer-002",
        answer_response(
            game=103,
            value=62,
            claims=[claim(game=103, value=62), extra],
        ),
    )
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
        "unsupported_additional_fact" in failures(report, "answer-002"),
        "extra typed claim must fail even when the requested value is present",
        problems,
    )
    return problems


def scenario_unattributed_numeric(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[2] = observation(
        "answer-003",
        answer_response(
            game=104,
            value=63,
            claims=[claim(game=104, value=63)],
            text="Synthetic wins 63 over 99 archived games.",
        ),
    )
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
        "unattributed_numeric" in failures(report, "answer-003"),
        "63 must not pass silently",
        problems,
    )
    return problems


def scenario_scoreline_and_signed_facts(directory: Path) -> list[str]:
    """Dict-valued scoreline facts compare their canonical ids; signed facts stay attributable."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    scoreline = synthetic_scoreline()
    for case in expectations["cases"]:
        if case["id"] == "answer-001":
            case["proposed_expectation"]["canonical_facts"][0].update(
                {"metric": "game_score", "value": scoreline}
            )
        if case["id"] == "answer-002":
            case["proposed_expectation"]["canonical_facts"][0].update(
                {"metric": "margin", "value": -38}
            )
    expectations["labels_sha256"] = hashlib.sha256(questions_path.read_bytes()).hexdigest()
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    # The producer's scoreline value carries the NBA game id itself; the fixture delivers
    # that same canonical dictionary rather than a runtime id in its place.
    runtime_scoreline = dict(scoreline)
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=0,
            claims=[
                claim(
                    game=103,
                    value=runtime_scoreline,
                    metric="game_score",
                    unit="game",
                    sample_size=1,
                )
            ],
            text="Synthetic game Score 120 66.",
        ),
    )
    observations[1] = observation(
        "answer-002",
        answer_response(
            game=104,
            value=-38,
            claims=[claim(game=104, value=-38, metric="margin", unit="points")],
            text="Synthetic margin 38.",
        ),
    )
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    if result.returncode != 0 or report is None:
        return problems + [f"score failed: {result.stderr[-800:]}"]
    expect(failures(report, "answer-001") == [], "mapped scoreline fact passes", problems)
    expect(failures(report, "answer-002") == [], "signed fact stays attributable", problems)
    broken = dict(runtime_scoreline)
    broken["home_score"] = 121
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=0,
            claims=[
                claim(
                    game=103,
                    value=broken,
                    metric="game_score",
                    unit="game",
                    sample_size=1,
                )
            ],
            text="Synthetic game Score 121 66.",
        ),
    )
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    if result.returncode != 0 or report is None:
        return problems + [f"score failed: {result.stderr[-800:]}"]
    expect(
        "numeric_mismatch" in failures(report, "answer-001"),
        "a different scoreline must fail",
        problems,
    )
    broken = {**scoreline, "nba_game_id": 103}
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=0,
            claims=[claim(game=103, value=broken, metric="game_score", unit="game", sample_size=1)],
            text="Synthetic game Score 120 66.",
        ),
    )
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    if result.returncode != 0 or report is None:
        return problems + [f"score failed: {result.stderr[-800:]}"]
    expect(
        "numeric_mismatch" in failures(report, "answer-001"),
        "a SQL game id cannot substitute for the canonical NBA game id",
        problems,
    )

    player_scoreline = {**scoreline, "nba_player_id": "1628384"}
    for case in expectations["cases"]:
        if case["id"] == "answer-001":
            case["proposed_expectation"]["canonical_facts"][0]["value"] = player_scoreline
    dump(expectations_path, expectations)
    for player_id, should_match in (("1628384", True), (114, False)):
        value = {**player_scoreline, "nba_player_id": player_id}
        observations[0] = observation(
            "answer-001",
            answer_response(
                game=103,
                value=0,
                claims=[
                    claim(game=103, value=value, metric="game_score", unit="game", sample_size=1)
                ],
                text="Synthetic game Score 120 66.",
            ),
        )
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        if result.returncode != 0 or report is None:
            return problems + [f"score failed: {result.stderr[-800:]}"]
        expect(
            ("numeric_mismatch" not in failures(report, "answer-001")) == should_match,
            "canonical player id matches but a SQL player id cannot substitute for it",
            problems,
        )
    return problems


def scenario_attribution_inputs(directory: Path) -> list[str]:
    """Numbers attribute from immutable inputs and typed fields, never a blanket allowance."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    receipt = f"{RELEASE}:game:105"
    record = receipt_record(receipt)
    record["metadata"] = {"numerator": 2466, "denominator": 40.0, "sample_size": 40}
    stated = claim(
        game=105,
        value=63,
        sample_size=101,
        eligibility={
            "appearance": "minutes > 0",
            "considered_games": 2,
            "considered_game_ids": [103, 104],
        },
    )
    # The answer states a whole ISO date, the question's own criterion number, the
    # receipt's recorded numerator and the claim's considered population.
    allowed = (
        "Synthetic answer question 3: wins 63 over 101 archived games on 2026-01-21, "
        "2466 total points across 2 considered games."
    )
    observations[2] = observation(
        "answer-003",
        answer_response(
            game=105,
            value=63,
            claims=[stated],
            receipt=receipt,
            evidence=[record],
            text=allowed,
        ),
    )
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
        "unattributed_numeric" not in failures(report, "answer-003"),
        "a whole ISO date, a stated criterion, a receipt numerator and the considered "
        "population are attributable",
        problems,
    )
    observations[2] = observation(
        "answer-003",
        answer_response(
            game=105,
            value=63,
            claims=[stated],
            receipt=receipt,
            evidence=[record],
            text=f"{allowed} An invented 999 does not belong to any input.",
        ),
    )
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
            "unattributed_numeric" in failures(report, "answer-003"),
            "an invented number is still unattributed",
            problems,
        )
    return problems
