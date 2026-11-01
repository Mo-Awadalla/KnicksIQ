"""Failed and incomplete answers must remain valid, measurable review records.

Failure modes are rejection of an honest wrong-disposition verdict, rejection of
an omitted-fact verdict, and credit for a reviewed answer missing required facts.
The scenarios drive the real scoring CLI against isolated synthetic artifacts.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval_scenario_fixtures import (
    dump,
    load,
    review_payload,
    run_score,
    synthetic_mapping,
    synthetic_questions,
    write_dataset,
)
from eval_scenario_records import baseline_observations, disposition_response, observation
from eval_scenario_support import digest, expect, metric


def scenario_wrong_disposition_review_is_measured(directory: Path) -> list[str]:
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    rows[0] = observation("answer-001", disposition_response("refuse"))
    payload = review_payload(
        rows,
        questions_path=questions,
        expectations_path=expectations,
        mapping_path=mapping,
    )
    first = next(item for item in payload["cases"] if item["case_id"] == "answer-001")
    first.update(disposition="refuse", assertions=[], paraphrase="unsupported")
    reviews = dump(directory / "reviews.json", payload)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=rows,
        reviews=reviews,
    )
    expect(
        result.returncode == 0,
        "an honest wrong-disposition review must load instead of becoming unreviewed",
        problems,
    )
    if report is not None:
        scored = metric(report, "disposition_accuracy")
        expect(scored["status"] == "measured", "wrong disposition stays measurable", problems)
        expect(scored["numerator"] == 119, "wrong disposition receives no credit", problems)
        expect(scored["denominator"] == 120, "the failed case stays in the denominator", problems)
    return problems


def scenario_omitted_fact_review_is_measured(directory: Path) -> list[str]:
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    payload = load(expectations)
    first_case = next(case for case in payload["cases"] if case["id"] == "answer-001")
    first_case["proposed_expectation"]["canonical_facts"].append(
        {
            "metric": "losses",
            "value": 40,
            "scope": "archive",
            "subject": "team:NYK",
            "canonical_evidence_ids": ["game:0022500001"],
        }
    )
    dump(expectations, payload)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    reviews_payload = review_payload(
        rows,
        questions_path=questions,
        expectations_path=expectations,
        mapping_path=mapping,
    )
    first = next(item for item in reviews_payload["cases"] if item["case_id"] == "answer-001")
    first["assertions"] = first["assertions"][:1]
    first["paraphrase"] = "unsupported"
    reviews = dump(directory / "reviews.json", reviews_payload)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=rows,
        reviews=reviews,
    )
    expect(
        result.returncode == 0,
        "an omitted-fact review must load without inventing an assertion for the omission",
        problems,
    )
    if report is not None:
        quality = metric(report, "answer_quality")
        expect(quality["status"] == "measured", "incomplete answer stays measurable", problems)
        expect(
            quality["numerator"] == 57,
            "missing required facts deny answer-quality credit",
            problems,
        )
        expect(
            quality["denominator"] == 58,
            "incomplete answer stays in the answer denominator",
            problems,
        )
    return problems


def scenario_legacy_semantic_behavior_is_not_recall(directory: Path) -> list[str]:
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = baseline_observations(synthetic_questions())
    for row in rows:
        row["response"]["tool_calls"] = []
        row["response_sha256"] = digest(row["response"])
    reviews = dump(
        directory / "reviews.json",
        review_payload(
            rows,
            questions_path=questions,
            expectations_path=expectations,
            mapping_path=mapping,
        ),
    )
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=rows,
        reviews=reviews,
    )
    expect(result.returncode == 0, "route-aware diagnostic must be scoreable", problems)
    if report is None:
        return problems + ["route-aware diagnostic report missing"]
    behavior = report["metrics"].get("legacy_semantic_behavior_accuracy")
    expect(behavior is not None, "the original semantic cohort needs behavior scoring", problems)
    if behavior is not None:
        expect(behavior["denominator"] == 50, "all original fifty cases remain", problems)
        expect(
            behavior["numerator"] == 50,
            "valid structured/clarification behavior earns credit",
            problems,
        )
    narrative = report["metrics"].get("narrative_recall_at_5")
    expect(narrative is not None, "a separate narrative retrieval gate is required", problems)
    if narrative is not None:
        expect(
            narrative["status"] == "blocked", "absent narrative evidence stays blocked", problems
        )
        expect(narrative["numerator"] == 0, "SQL and clarification cannot invent recall", problems)
    return problems


def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="kiq-failed-review-") as temporary:
        for name, scenario in (
            ("wrong_disposition", scenario_wrong_disposition_review_is_measured),
            ("omitted_fact", scenario_omitted_fact_review_is_measured),
            ("route_aware", scenario_legacy_semantic_behavior_is_not_recall),
        ):
            directory = Path(temporary) / name
            directory.mkdir()
            checks[name] = scenario(directory)
    print(json.dumps(checks, indent=2))
    return int(any(checks.values()))


if __name__ == "__main__":
    raise SystemExit(main())
