"""Citation, receipt and ranked-trace scenarios for the evaluation scorer."""

from __future__ import annotations

import hashlib
from pathlib import Path

from eval_scenario_fixtures import (
    dump,
    load,
    run_score,
    scored_game_row,
    synthetic_mapping,
    synthetic_questions,
    write_dataset,
)
from eval_scenario_records import (
    answer_response,
    baseline_observations,
    calculation_receipt,
    calculation_record,
    claim,
    observation,
    ranked,
    receipt_record,
    trace,
)
from eval_scenario_support import RELEASE, digest, expect, failures, metric


def scenario_receipt_prefix_is_not_identity(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    observations[3] = observation(
        "answer-004",
        answer_response(game=105, value=64, receipt=f"{RELEASE}:game:999"),
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
        "citation_unmapped_receipt" in failures(report, "answer-004"),
        "prefix-valid but unmapped receipt must fail",
        problems,
    )
    return problems


def scenario_calculation_receipts(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    game, value = 107, 65
    sources = [f"{RELEASE}:game:{game}"]
    good = calculation_receipt(game, "team:NYK", "wins", sources, value)
    observations[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=value,
            claims=[
                claim(
                    game=game,
                    value=value,
                    evidence=[good],
                )
            ],
            receipt=good,
            evidence=[calculation_record(good, sources, sample_size=101, denominator=None)],
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
            "calculation_receipt_mismatch" not in failures(report, "answer-005"),
            "verified calculation receipt must pass",
            problems,
        )
        expect(
            "calculation_sources_unverified" not in failures(report, "answer-005"),
            "resolvable sources must pass",
            problems,
        )

    bad = "calculation:" + "0" * 64
    observations[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=value,
            claims=[claim(game=game, value=value, evidence=[bad])],
            receipt=bad,
            evidence=[calculation_record(bad, sources, sample_size=101, denominator=None)],
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
            "calculation_receipt_mismatch" in failures(report, "answer-005"),
            "recomputed hash mismatch must fail",
            problems,
        )

    unknown_source = calculation_receipt(777, "team:NYK", "wins", [f"{RELEASE}:game:777"], value)
    observations[4] = observation(
        "answer-005",
        answer_response(
            game=777,
            value=value,
            claims=[claim(game=777, value=value, evidence=[unknown_source])],
            receipt=unknown_source,
            evidence=[
                calculation_record(
                    unknown_source,
                    [f"{RELEASE}:game:777"],
                    sample_size=101,
                    denominator=None,
                )
            ],
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
        case = [item for item in report["cases"] if item["id"] == "answer-005"][0]
        reasons = [reason for row in case["citations"] for reason in row.get("unverified") or []]
        expect(
            "calculation_sources_unverified" in reasons,
            "matching hash with unresolved sources is recorded as unverified",
            problems,
        )
        expect(
            "citation_content_unverified" in case["citation_blockers"],
            "unresolved sources earn no citation credit",
            problems,
        )
        expect(
            metric(report, "citation_receipt_correctness")["status"] == "blocked",
            "unresolved sources never publish a citation value",
            problems,
        )
    return problems


def _points_expectation(expectations_path: Path, case_id: str, *, value: int, text: str) -> None:
    """Keep the proposed expectation consistent with the claim a scenario delivers."""
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] != case_id:
            continue
        expectation = case["proposed_expectation"]
        expectation["canonical_facts"][0].update({"metric": "points", "value": value})
        expectation["required_facts"] = [f"archive — points: {value}"]
        expectation["claims"][0]["text"] = text
    dump(expectations_path, expectations)


def scenario_calculation_receipt_reuse(directory: Path) -> list[str]:
    """One receipt never verifies a second claim's own denominator."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    row = scored_game_row(107)
    _points_expectation(expectations_path, "answer-005", value=120, text="archive — points: 120")
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping(game_rows={107: row}))
    observations = baseline_observations(synthetic_questions())
    game, value = 107, 120
    sources = [f"{RELEASE}:game:{game}"]
    receipt = calculation_receipt(game, "team:NYK", "points", sources, value)
    evidence = [
        receipt_record(sources[0], source_row=row),
        calculation_record(receipt, sources, sample_size=1, denominator=None),
    ]
    verified = claim(
        game=game,
        value=value,
        metric="points",
        unit="points",
        sample_size=1,
        evidence=[receipt],
    )
    reused = claim(
        game=game,
        value=value,
        metric="points",
        unit="points",
        sample_size=1,
        denominator=2,
        evidence=[receipt],
    )
    observations[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=value,
            claims=[verified],
            receipt=receipt,
            evidence=evidence,
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
            failures(report, "answer-005") == [],
            "the first claim's own receipt verifies",
            problems,
        )
    observations[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=value,
            claims=[verified, reused],
            receipt=receipt,
            evidence=evidence,
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
            "calculation_denominator_mismatch" in failures(report, "answer-005"),
            "a reused receipt is re-verified against the second claim",
            problems,
        )
    return problems


def scenario_missing_trace_and_rank(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    response = answer_response(game=103, value=61)
    response["tool_calls"] = []
    observations[0] = observation("answer-001", response)
    broken = trace(104)
    broken["candidates"] = [ranked(104, 2), ranked(104, 1)]
    observations[1] = observation(
        "answer-002", answer_response(game=104, value=62, trace_entry=broken)
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
        "missing_ranked_trace" not in failures(report, "answer-001"),
        "a structured SQL answer does not require a retrieval trace",
        problems,
    )
    expect("trace_rank_invalid" in failures(report, "answer-002"), "bad ranks fail", problems)
    expect(
        metric(report, "narrative_recall_at_5")["status"] == "blocked",
        "legacy traces cannot supply a separate narrative benchmark",
        problems,
    )
    return problems


def scenario_possession_document_receipts(directory: Path) -> list[str]:
    """Narrative possession receipts resolve through the local index identity mapping."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    for case in expectations["cases"]:
        if case["id"] == "answer-001":
            case["proposed_expectation"]["canonical_facts"][0]["metric"] = "narrative"
    expectations["labels_sha256"] = hashlib.sha256(questions_path.read_bytes()).hexdigest()
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    documents = dump(
        directory / "runtime-document-mapping.json",
        {
            "version": RELEASE,
            "scope": "synthetic scenario documents",
            "documents": {
                "game:103:poss:1": {
                    "point_id": "00000000-0000-0000-0000-000000000001",
                    "collection": "knicks_possessions",
                    "game_id": 103,
                    "runtime_evidence_id": f"{RELEASE}:game:103:poss:1",
                    "payload_sha256": digest("scenario-document"),
                }
            },
        },
    )
    observations = baseline_observations(synthetic_questions())
    narrative_claim = claim(game=103, value=61, metric="narrative", unit="passage")
    response = answer_response(
        game=103,
        value=61,
        claims=[narrative_claim],
        text="Synthetic narrative 61.",
    )
    response["citations"].append(
        {
            "claim": "Synthetic narrative passage.",
            "type": "possession",
            "title": "scenario",
            "game_id": 103,
            "source_name": None,
            "source_url": None,
            "metadata": {"possession_id": "game:103:poss:1"},
        }
    )
    observations[0] = observation("answer-001", response)
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
        extra=["--documents", str(documents)],
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-800:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(
        "citation_document_not_in_mapping" not in failures(report, "answer-001"),
        "a recorded document identity resolves",
        problems,
    )
    expect(
        "citation_unrelated_receipt" not in failures(report, "answer-001"),
        "the document's game is the expected evidence",
        problems,
    )
    response["citations"][-1]["metadata"] = {"possession_id": "game:103:poss:9"}
    observations[0] = observation("answer-001", response)
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
        extra=["--documents", str(documents)],
    )
    if report is not None:
        expect(
            "citation_document_not_in_mapping" in failures(report, "answer-001"),
            "an unrecorded chunk id fails closed",
            problems,
        )
    return problems
