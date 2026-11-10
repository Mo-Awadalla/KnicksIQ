"""Subject, population, alias and precision scenarios for typed facts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from eval_scenario_fixtures import (
    dump,
    load,
    review_payload,
    run_score,
    synthetic_mapping,
    synthetic_questions,
    write_dataset,
)
from eval_scenario_records import (
    answer_response,
    baseline_observations,
    observation,
    write_observations,
)
from eval_scenario_support import RELEASE, expect, failures, metric


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


def scenario_team_subject_substitution(directory: Path) -> list[str]:
    """Another team's claim cannot satisfy a Knicks fact."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[2] = observation(
        "answer-003",
        answer_response(game=104, value=63, subject="team:BOS"),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "entity_mismatch" in failures(report, "answer-003"),
        "the substituted team fails",
        problems,
    )
    expect(
        metric(report, "canonical_entity_correctness")["numerator"] < 58,
        "the entity metric cannot pass",
        problems,
    )
    return problems


def scenario_subject_unverifiable_blocks(directory: Path) -> list[str]:
    """A fact without an approved canonical subject blocks the entity metric."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    _set_fact(expectations, "answer-007", subject=None)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "subject_unverifiable" in failures(report, "answer-007"),
        "the unverifiable subject is explicit",
        problems,
    )
    expect(
        metric(report, "canonical_entity_correctness")["status"] == "blocked",
        "the entity metric is blocked, not measured",
        problems,
    )
    return problems


def scenario_player_population_checked(directory: Path) -> list[str]:
    """A player fact's approved box-score population is expanded and compared."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    _set_fact(
        expectations,
        "answer-008",
        player_name="Jalen Brunson",
        subject="player:114",
        canonical_evidence_ids=["box:0022500007:1628384"],
    )
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[7] = observation(
        "answer-008",
        answer_response(game=110, value=68, subject="player:114"),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "evidence_scope_mismatch" in failures(report, "answer-008"),
        "the wrong box-score population fails",
        problems,
    )
    # Keep the value and population fixed while changing only the delivered player.
    _set_fact(
        expectations,
        "answer-008",
        subject=None,
        canonical_evidence_ids=["box:0022500008:1628384"],
    )
    identities = synthetic_mapping()
    identities["players"]["1626157"] = {"id": 115, "name": "Karl-Anthony Towns"}
    dump(mapping, identities)
    for subject, expected in (
        ("player:114", None),
        ("player:115", "entity_mismatch"),
        ("player:9999", "subject_unverifiable"),
    ):
        rows[7] = observation(
            "answer-008",
            answer_response(game=110, value=68, subject=subject),
        )
        result, report = _score(directory, questions, expectations, mapping, rows)
        if result.returncode != 0 or report is None:
            return problems + [f"score failed: {result.stderr[-500:]}"]
        codes = failures(report, "answer-008")
        if expected is None:
            expect(
                not (
                    {"entity_mismatch", "subject_unverifiable", "evidence_scope_mismatch"}
                    & set(codes)
                ),
                "the mapped named player and matching population pass",
                problems,
            )
        else:
            expect(expected in codes, f"{subject} must produce {expected}", problems)
            if expected == "subject_unverifiable":
                expect(
                    metric(report, "canonical_entity_correctness")["status"] == "blocked",
                    "an unmapped player blocks the entity metric",
                    problems,
                )
    return problems


def scenario_window_direction_required(directory: Path) -> list[str]:
    """A stated last-N window must be recorded in that direction."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    _set_fact(expectations, "answer-009", scope="last 5 games")
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[8] = observation(
        "answer-009",
        answer_response(game=110, value=69, sample_size=5, window={"first_n": 5}),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "window_mismatch" in failures(report, "answer-009"),
        "the wrong direction fails",
        problems,
    )
    return problems


def scenario_season_mismatch_fails(directory: Path) -> list[str]:
    """A claim from another season cannot satisfy the same-Season case."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    response = answer_response(game=105, value=64)
    response["citations"][0]["metadata"]["claim"]["season"] = "2024-25"
    rows[3] = observation("answer-004", response)
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "season_mismatch" in failures(report, "answer-004"),
        "the other season fails",
        problems,
    )
    return problems


def scenario_runtime_metric_forms_pass(directory: Path) -> list[str]:
    """The metric ids and units the runtime actually emits are reachable."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    payload = load(expectations)
    for case in payload["cases"]:
        if case["id"] == "answer-001":
            case["proposed_expectation"]["canonical_facts"][0].update(
                {"metric": "points_per_game", "value": 112.5}
            )
        if case["id"] == "answer-002":
            case["proposed_expectation"]["canonical_facts"][0].update(
                {"metric": "margin_per_game", "value": -3.5}
            )
        if case["id"] == "answer-003":
            case["proposed_expectation"]["canonical_facts"][0].update(
                {"metric": "Jalen Brunson: average points", "value": 26.5, "player_name": None}
            )
            case["proposed_expectation"]["canonical_facts"][0].pop("subject", None)
    dump(expectations, payload)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[0] = observation(
        "answer-001",
        answer_response(game=103, value=112.5, metric="points_per_game", unit="points per game"),
    )
    rows[1] = observation(
        "answer-002",
        answer_response(game=104, value=-3.5, metric="margin_per_game", unit="points per game"),
    )
    rows[2] = observation(
        "answer-003",
        answer_response(
            game=104,
            value=26.5,
            metric="points:average",
            unit="points per appearance",
            subject="player:114",
        ),
    )
    _set_fact(expectations, "answer-003", subject="player:114")
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    for case_id in ("answer-001", "answer-002", "answer-003"):
        expect(
            "no_typed_claim_for_fact" not in failures(report, case_id),
            f"{case_id} resolves the emitted metric form",
            problems,
        )
    expect(
        "numeric_mismatch" not in failures(report, "answer-001"),
        "the per-game value matches",
        problems,
    )
    _set_fact(
        expectations,
        "answer-008",
        metric="Jalen Brunson: total points",
        value=28,
        subject=None,
        player_name="Jalen Brunson",
        appearances=1,
        canonical_evidence_ids=["game:0022500008"],
    )
    for delivered_metric, unit, should_match in (
        ("points:game", "points", True),
        ("points:average", "points per appearance", False),
    ):
        rows[7] = observation(
            "answer-008",
            answer_response(
                game=110,
                value=28,
                metric=delivered_metric,
                unit=unit,
                subject="player:114",
                sample_size=1,
            ),
        )
        result, report = _score(directory, questions, expectations, mapping, rows)
        if result.returncode != 0 or report is None:
            return problems + [f"score failed: {result.stderr[-500:]}"]
        codes = failures(report, "answer-008")
        expect(
            ("no_typed_claim_for_fact" not in codes) == should_match,
            f"{delivered_metric} {'matches' if should_match else 'does not match'} a game total",
            problems,
        )
        if should_match:
            expect(
                not (
                    {"numeric_mismatch", "entity_mismatch", "evidence_scope_mismatch"} & set(codes)
                ),
                "the game total also matches its value, player and population",
                problems,
            )
    return problems


def scenario_displayed_precision_additions(directory: Path) -> list[str]:
    """Rounded display precision is consistent in matching and attribution."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    _set_fact(expectations, "answer-010", metric="points", value=116.3366)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[9] = observation(
        "answer-010",
        answer_response(
            game=112,
            value=116.3366,
            metric="points",
            unit="points",
            text="Synthetic points 116.3.",
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    codes = failures(report, "answer-010")
    expect("numeric_mismatch" not in codes, "the displayed precision matches", problems)
    expect("unattributed_numeric" not in codes, "the rounded display is attributed", problems)
    expect("unsupported_additional_fact" not in codes, "the claim is not an addition", problems)
    rows[9] = observation(
        "answer-010",
        answer_response(
            game=112,
            value=116.9,
            metric="points",
            unit="points",
            text="Synthetic points 116.9.",
        ),
    )
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is not None:
        expect(
            "numeric_mismatch" in failures(report, "answer-010"),
            "a genuinely different rounded value fails",
            problems,
        )
    return problems


def scenario_unmapped_references_do_not_verify(directory: Path) -> list[str]:
    """Mapping coverage is identity only; it never stands in for verified content."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    response = answer_response(game=105, value=64)
    response["evidence"] = [
        {
            "evidence_id": f"{RELEASE}:game:105",
            "release_id": RELEASE,
            "text": "a different row payload",
            "game_id": 105,
            "source_row_id": 105,
            "metadata": {"row_sha256": hashlib.sha256(b"other").hexdigest()},
        }
    ]
    rows[3] = observation("answer-004", response)
    result, report = _score(directory, questions, expectations, mapping, rows)
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    case = [item for item in report["cases"] if item["id"] == "answer-004"][0]
    expect(
        "citation_content_mismatch" in case["citation_blockers"],
        "a mismatched row payload blocks the citation measurement",
        problems,
    )
    expect(
        metric(report, "citation_receipt_correctness")["status"] == "blocked",
        "identity coverage alone does not publish a citation value",
        problems,
    )
    return problems
