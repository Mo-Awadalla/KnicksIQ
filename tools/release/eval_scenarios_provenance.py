"""Provenance and retrieval scenarios: receipts, subjects, windows, aliases, precision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eval_scenario_fixtures import (
    dump,
    load,
    review_payload,
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
    write_observations,
)
from eval_scenario_support import RELEASE, digest, expect, failures, metric


def _score(directory: Path, questions: Path, expectations: Path, mapping: Path, rows: list[Any]):
    write_observations(directory / "responses.jsonl", rows)
    reviews = dump(
        directory / "review-decisions.json",
        review_payload(
            rows,
            questions_path=questions,
            expectations_path=expectations,
            mapping_path=mapping,
        ),
    )
    return run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=rows,
        reviews=reviews,
    )


def _set_fact(expectations: Path, case_id: str, **changes: Any) -> None:
    payload = load(expectations)
    for case in payload["cases"]:
        if case["id"] == case_id:
            case["proposed_expectation"]["canonical_facts"][0].update(changes)
    dump(expectations, payload)


def scenario_calculation_evidence_required(directory: Path) -> list[str]:
    """A calculation receipt without its registry record blocks the citation metric."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    game, value = 107, 65
    sources = [f"{RELEASE}:game:{game}"]
    receipt = calculation_receipt(game, "team:NYK", "wins", sources, value)
    rows[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=value,
            claims=[claim(game=game, value=value, evidence=[receipt])],
            receipt=receipt,
            evidence=[],
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    case = [item for item in report["cases"] if item["id"] == "answer-005"][0]
    expect(
        "calculation_evidence_missing" in [f["code"] for f in case["failures"]],
        "the missing committed record is explicit",
        problems,
    )
    expect(
        "citation_content_unverified" in case["citation_blockers"],
        "the citation metric is blocked, not credited",
        problems,
    )
    expect(
        metric(report, "citation_receipt_correctness")["status"] == "blocked",
        "no citation value is published without content",
        problems,
    )
    return problems


def scenario_calculation_arithmetic_checked(directory: Path) -> list[str]:
    """A reproducible hash with wrong recorded arithmetic fails."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    _set_fact(expectations, "answer-005", metric="points", denominator=100, numerator=112.0)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    game = 107
    sources = [f"{RELEASE}:game:{game}"]
    receipt = calculation_receipt(game, "team:NYK", "points", sources, 112)
    rows[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=112,
            metric="points",
            unit="points",
            sample_size=100,
            denominator=100,
            claims=[
                claim(
                    game=game,
                    value=112,
                    metric="points",
                    unit="points",
                    sample_size=100,
                    denominator=100,
                    evidence=[receipt],
                )
            ],
            receipt=receipt,
            evidence=[
                calculation_record(
                    receipt, sources, sample_size=100, denominator=100, numerator=999.0
                )
            ],
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "calculation_arithmetic_mismatch" in failures(report, "answer-005"),
        "wrong recorded arithmetic fails",
        problems,
    )
    return problems


def scenario_per_claim_support_required(directory: Path) -> list[str]:
    """A claim with no receipts of its own is never covered by another claim's receipt."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    supported = claim(game=104, value=63)
    unsupported = claim(game=104, value=64, metric="losses", unit="losses", evidence=[""])
    rows[2] = observation(
        "answer-003",
        answer_response(
            game=104,
            value=63,
            claims=[supported, dict(unsupported, supporting_evidence_ids=[])],
            text="Synthetic wins 63.",
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    codes = failures(report, "answer-003")
    expect("claim_without_receipt" in codes, "the unsupported claim is explicit", problems)
    expect(
        metric(report, "citation_receipt_correctness")["numerator"] < 58,
        "case-wide overlap does not pass the citation metric",
        problems,
    )
    return problems


def scenario_additional_claim_other_subject(directory: Path) -> list[str]:
    """A same-valued claim for another subject is an unsupported additional fact."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    nyk = claim(game=104, value=63)
    other = claim(game=104, value=63, subject="team:BOS")
    rows[2] = observation(
        "answer-003",
        answer_response(game=104, value=63, claims=[nyk, other]),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "unsupported_additional_fact" in failures(report, "answer-003"),
        "the other-team claim is unsupported",
        problems,
    )
    return problems


def scenario_scoreline_extra_field_fails(directory: Path) -> list[str]:
    """A scoreline dictionary with an unapproved numeric field fails."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    scoreline = {
        "nba_game_id": "0022500003",
        "home_team_id": "NYK",
        "away_team_id": "BKN",
        "home_score": 120,
        "away_score": 66,
    }
    _set_fact(expectations, "answer-001", metric="game_score", value=scoreline)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    runtime = {**scoreline, "free_throws_made": 21}
    rows[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=0,
            claims=[
                claim(game=103, value=runtime, metric="game_score", unit="game", sample_size=1)
            ],
            text="Synthetic game Score 120 66.",
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "numeric_mismatch" in failures(report, "answer-001"),
        "an extra numeric field is not an approved fact",
        problems,
    )
    return problems


def scenario_foreign_release_receipt_rejected(directory: Path) -> list[str]:
    """A receipt from another release is never credited."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    foreign = "other-release:game:104:104"
    rows[2] = observation(
        "answer-003",
        answer_response(
            game=104,
            value=63,
            claims=[claim(game=104, value=63, evidence=[foreign])],
            receipt=foreign,
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "citation_foreign_release" in failures(report, "answer-003"),
        "the foreign release is explicit",
        problems,
    )
    return problems


def scenario_invalid_trace_no_behavior_credit(directory: Path) -> list[str]:
    """An invalid recorded trace denies behavior credit without shrinking the cohort."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    broken = trace(103)
    broken["candidates"] = [ranked(103, 2), ranked(103, 1)]
    rows[0] = observation("answer-001", answer_response(game=103, value=61, trace_entry=broken))
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "trace_rank_invalid" in failures(report, "answer-001"),
        "the invalid ranks are explicit",
        problems,
    )
    expect(
        metric(report, "legacy_semantic_behavior_accuracy")["numerator"] == 49,
        "the one rank-invalid response earns no behavior credit",
        problems,
    )
    expect(
        metric(report, "legacy_semantic_behavior_accuracy")["denominator"] == 50,
        "the case stays in the fixed 50",
        problems,
    )
    return problems


def scenario_legacy_trace_does_not_supply_narrative_gold(directory: Path) -> list[str]:
    """A legacy possession trace cannot invent independently labelled narrative gold."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    entry = ranked(103, 1, collection="possessions")
    rows[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=61,
            trace_entry=trace(103, candidates=[entry], selected=[entry]),
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        metric(report, "narrative_recall_at_5")["numerator"] == 0
        and metric(report, "narrative_recall_at_5")["status"] == "blocked",
        "a game-level trace earns no document-retrieval credit",
        problems,
    )
    return problems


def scenario_denominator_not_sample_size(directory: Path) -> list[str]:
    """A required denominator is compared with the denominator, not the sample size."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    _set_fact(expectations, "answer-006", denominator=101, numerator=6565.0)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[5] = observation(
        "answer-006",
        answer_response(game=108, value=66, sample_size=101, denominator=7),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "denominator_mismatch" in failures(report, "answer-006"),
        "the wrong denominator fails although the sample size matches",
        problems,
    )
    return problems


def scenario_source_content_verified(directory: Path) -> list[str]:
    """A receipt is verified by its row content, never by its claimed digest."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    game, value = 103, 61
    reference = f"{RELEASE}:game:{game}"
    row = {"game": game}

    def registry(**changes: Any) -> list[dict[str, Any]]:
        entry = {
            "evidence_id": reference,
            "release_id": RELEASE,
            "text": "synthetic game row",
            "game_id": game,
            "source_row_id": game,
            "source_row": row,
            "metadata": {"row_sha256": digest(row)},
        }
        entry.update(changes)
        return [entry]

    rows[0] = observation(
        "answer-001", answer_response(game=game, value=value, evidence=registry())
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    case = [item for item in report["cases"] if item["id"] == "answer-001"][0]
    expect(
        "citation_content_mismatch" not in case["citation_blockers"],
        "verified row content passes",
        problems,
    )
    expect(
        "citation_content_unverified" not in case["citation_blockers"],
        "verified row content resolves",
        problems,
    )

    rows[0] = observation(
        "answer-001",
        answer_response(game=game, value=value, evidence=registry(source_row={"game": game + 1})),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is not None:
        case = [item for item in report["cases"] if item["id"] == "answer-001"][0]
        expect(
            "citation_content_mismatch" in case["citation_blockers"],
            "row content that contradicts its digest fails",
            problems,
        )

    claimed_only = registry()
    claimed_only[0].pop("source_row")
    rows[0] = observation(
        "answer-001", answer_response(game=game, value=value, evidence=claimed_only)
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is not None:
        case = [item for item in report["cases"] if item["id"] == "answer-001"][0]
        expect(
            "citation_content_unverified" in case["citation_blockers"],
            "a claimed digest without content stays unverified",
            problems,
        )
        expect(
            metric(report, "citation_receipt_correctness")["status"] == "blocked",
            "claimed digests never publish a citation value",
            problems,
        )
    return problems


def scenario_calculation_population_bounded(directory: Path) -> list[str]:
    """A sample larger than the recorded expansion was never computed from it."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    # The receipt declares the same sample the claim does, so only the expansion can
    # contradict it: one complete game row cannot have counted 101 games.
    _set_fact(expectations, "answer-005", metric="points", value=12000)
    row = scored_game_row(107)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping(game_rows={107: row}))
    rows = baseline_observations(synthetic_questions())
    game, value = 107, 12000
    sources = [f"{RELEASE}:game:{game}"]
    receipt = calculation_receipt(game, "team:NYK", "points", sources, value)
    rows[4] = observation(
        "answer-005",
        answer_response(
            game=game,
            value=value,
            claims=[
                claim(
                    game=game,
                    value=value,
                    metric="points",
                    unit="points",
                    sample_size=101,
                    evidence=[receipt],
                )
            ],
            receipt=receipt,
            evidence=[
                receipt_record(sources[0], source_row=row),
                calculation_record(receipt, sources, sample_size=101, denominator=None),
            ],
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "calculation_population_mismatch" in failures(report, "answer-005"),
        "a sample beyond its receipts fails",
        problems,
    )
    return problems
