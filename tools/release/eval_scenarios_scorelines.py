"""Public scoring controls for projected scorelines and verified source content."""

from __future__ import annotations

from pathlib import Path

from eval_scenario_fixtures import (
    dump,
    load,
    run_score,
    scored_game_row,
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
from eval_scenario_support import RELEASE, expect, failures


def scenario_scoreline_scope_projection(directory: Path) -> list[str]:
    """A projected scoreline answers to the same scope invariants as a typed fact."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    scoreline = synthetic_scoreline()
    for case in expectations["cases"]:
        if case["id"] == "answer-001":
            expectation = case["proposed_expectation"]
            expectation["canonical_facts"][0].update(
                {"metric": "game_score", "value": scoreline, "scope": "archive"}
            )
            expectation["canonical_facts"].append(
                {
                    "metric": "margin",
                    "value": 54,
                    "scope": "archive",
                    "subject": "team:NYK",
                    "canonical_evidence_ids": ["game:0022500001"],
                }
            )
    dump(expectations_path, expectations)
    row = scored_game_row(103)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping(game_rows={103: row}))
    observations = baseline_observations(synthetic_questions())
    # No typed game_score claim is delivered: the scoreline is projected through the
    # margin claim's own verified game receipt and the scores the answer states.
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=54,
            claims=[claim(game=103, value=54, metric="margin", unit="points", sample_size=1)],
            text="Synthetic final score 120 66, margin 54.",
            evidence=[receipt_record(f"{RELEASE}:game:103", source_row=row)],
        ),
    )

    def score(scope: str) -> dict | None:
        edited = load(expectations_path)
        for case in edited["cases"]:
            if case["id"] == "answer-001":
                case["proposed_expectation"]["canonical_facts"][0]["scope"] = scope
        dump(expectations_path, edited)
        result, report = run_score(
            directory,
            questions=questions_path,
            expectations=expectations_path,
            mapping=mapping,
            observations=observations,
        )
        if result.returncode != 0 or report is None:
            problems.append(f"score failed: {result.stderr[-800:]}")
            return None
        return report

    archive = score("archive")
    if archive is not None:
        expect(
            failures(archive, "answer-001") == [],
            "a projected scoreline inside the release scope passes",
            problems,
        )
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=54,
            claims=[claim(game=103, value=54, metric="margin", unit="points", sample_size=1)],
            text="Synthetic margin 54.",
            evidence=[receipt_record(f"{RELEASE}:game:103", source_row=row)],
        ),
    )
    undisplayed = score("archive")
    if undisplayed is not None:
        expect(
            "claim_not_displayed" in failures(undisplayed, "answer-001"),
            "a projected scoreline must actually be displayed",
            problems,
        )
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=54,
            claims=[claim(game=103, value=54, metric="margin", unit="points", sample_size=1)],
            text="Synthetic final score 120 66, margin 54.",
            evidence=[receipt_record(f"{RELEASE}:game:103", source_row={**row, "home_score": 121})],
        ),
    )
    tampered = score("archive")
    if tampered is not None:
        expect(
            "scoreline_evidence_unverified" in failures(tampered, "answer-001"),
            "a changed source row cannot project an approved scoreline",
            problems,
        )
    changed_row = scored_game_row(103, home_score=121)
    dump(mapping, synthetic_mapping(game_rows={103: changed_row}))
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=55,
            claims=[claim(game=103, value=55, metric="margin", unit="points", sample_size=1)],
            text="Synthetic final score 121 66, margin 55.",
            evidence=[receipt_record(f"{RELEASE}:game:103", source_row=changed_row)],
        ),
    )
    contradictory = score("archive")
    if contradictory is not None:
        expect(
            any(
                item["code"] == "numeric_mismatch" and item.get("fact_index") == 0
                for case in contradictory["cases"]
                if case["id"] == "answer-001"
                for item in case["failures"]
            ),
            "a verified row contradicting the approved scoreline fails",
            problems,
        )
    dump(mapping, synthetic_mapping(game_rows={103: row}))
    observations[0] = observation(
        "answer-001",
        answer_response(
            game=103,
            value=54,
            claims=[claim(game=103, value=54, metric="margin", unit="points", sample_size=1)],
            text="Synthetic final score 120 66, margin 54.",
            evidence=[receipt_record(f"{RELEASE}:game:103", source_row=row)],
        ),
    )
    unexpressible = score("not a declared scope")
    if unexpressible is not None:
        expect(
            "scope_not_expressible" in failures(unexpressible, "answer-001"),
            "an unrecognised scope fails closed for a projected scoreline",
            problems,
        )
    wrong_month = score("december 2025")
    if wrong_month is not None:
        expect(
            "window_mismatch" in failures(wrong_month, "answer-001"),
            "a scoreline outside its stated window fails",
            problems,
        )
    return problems
