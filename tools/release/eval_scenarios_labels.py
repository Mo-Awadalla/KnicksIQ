"""Label artifact scenarios: malformed, unverifiable and the real dataset."""

from __future__ import annotations

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
from eval_scenario_records import baseline_observations, write_observations
from eval_scenario_support import (
    ANSWER_CASES,
    CLARIFY_CASES,
    REAL_EXPECTATIONS,
    REAL_MAPPING,
    REAL_QUESTIONS,
    REFUSE_CASES,
    expect,
    run_cli,
)


def scenario_malformed_labels_digest(directory: Path) -> list[str]:
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    expectations["labels_sha256"] = "not-a-digest"
    dump(expectations_path, expectations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    result, report = run_score(
        directory,
        questions=questions_path,
        expectations=expectations_path,
        mapping=mapping,
        observations=observations,
    )
    expect(result.returncode != 0, "malformed label digest must be rejected", problems)
    return problems


def scenario_unverifiable_labels_digest(directory: Path) -> list[str]:
    """A recorded digest that matches no available artifact blocks; it never passes silently."""
    problems: list[str] = []
    questions_path, expectations_path = write_dataset(directory)
    expectations = load(expectations_path)
    expectations["labels_sha256"] = "e" * 64
    dump(expectations_path, expectations)
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
    if report is None:
        return problems + ["no report written"]
    expect(
        report["dataset"]["labels_digest_status"] == "unverified",
        "unverifiable digest must be recorded as unverified",
        problems,
    )
    expect(
        "labels_digest_unverified" in {item["code"] for item in report["blockers"]},
        "unverifiable digest must block explicitly",
        problems,
    )
    return problems


def scenario_real_dataset(directory: Path) -> list[str]:
    problems: list[str] = []
    output = directory / "real-report.json"
    result = run_cli(
        [
            "labels",
            "--questions",
            str(REAL_QUESTIONS),
            "--expectations",
            str(REAL_EXPECTATIONS),
            "--mapping",
            str(REAL_MAPPING),
            "--output",
            str(output),
        ],
        cwd=directory,
    )
    expect(result.returncode == 0, f"labels command failed: {result.stderr[-1200:]}", problems)
    if not output.exists():
        return problems + ["no label report written"]
    report = load(output)
    expect(report["dataset"]["case_count"] == 120, "real dataset has 120 cases", problems)
    expect(
        report["dataset"]["semantic_case_count"] == 50,
        "real dataset has 50 semantic cases",
        problems,
    )
    expect(
        report["dataset"]["dispositions_expected"]
        == {"answer": ANSWER_CASES, "clarify": CLARIFY_CASES, "refuse": REFUSE_CASES},
        "real dispositions preserved as proposed",
        problems,
    )
    expect(report["dataset"]["owner_approved"] == 0, "no owner approval exists", problems)
    expect(
        report["dataset"]["labels_digest_status"] == "verified",
        "the recorded labels digest is reproduced by the reviewed labels artifact",
        problems,
    )
    expect(
        str(report["dataset"]["labels_digest_source"] or "").endswith(
            "evaluation-label-review-20260907/labels.jsonl"
        ),
        "the digest is bound to the reviewed labels artifact path",
        problems,
    )
    expect(
        "labels_digest_unverified" not in {item["code"] for item in report["blockers"]},
        "a reproduced digest is not a blocker",
        problems,
    )
    expect(
        report["semantic"]["policy"] == "route_aware_behavior"
        and len(report["semantic"]["case_ids"]) == 50,
        "all fifty original semantic cases remain in the route-aware cohort",
        problems,
    )
    expect(report["release_blocked"] is True, "real labels block release", problems)
    expect(
        report["mapping"]["unmapped_canonical_references"] == 0,
        "every canonical label reference maps locally",
        problems,
    )
    return problems


def scenario_fabricated_approval_blocks(directory: Path) -> list[str]:
    """A boolean or note never counts as an approval or freeze."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory, owner_approved=True)
    payload = load(expectations)
    payload["owner_approval"] = {"approved": True, "by": "scenario"}
    payload["frozen"] = True
    payload.pop("freeze")
    dump(expectations, payload)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    codes = {item["code"] for item in report["blockers"]}
    expect(report["dataset"]["owner_approved"] == 0, "case booleans are not approval", problems)
    expect(report["dataset"]["frozen"] is False, "a boolean is not a freeze", problems)
    expect("labels_not_frozen" in codes, "the freeze blocker remains", problems)
    expect("labels_approval_unverified" in codes, "the approval blocker remains", problems)
    return problems


def scenario_freeze_mismatch_blocks(directory: Path) -> list[str]:
    """Changing a covered expectation invalidates the freeze."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory, owner_approved=True)
    payload = load(expectations)
    payload["cases"][0]["proposed_expectation"]["canonical_facts"][0]["value"] = 999
    dump(expectations, payload)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
    )
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(report["dataset"]["frozen"] is False, "a stale freeze is not frozen", problems)
    expect(
        "labels_freeze_unverified" in {item["code"] for item in report["blockers"]},
        "the stale freeze blocks explicitly",
        problems,
    )
    return problems


def scenario_changed_question_text_rejected(directory: Path) -> list[str]:
    """An expectation cannot change the immutable question text."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    payload = load(expectations)
    payload["cases"][0]["question"] = "A different question?"
    dump(expectations, payload)
    result, _ = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=dump(directory / "runtime-mapping.json", synthetic_mapping()),
        observations=baseline_observations(synthetic_questions()),
    )
    expect(result.returncode != 0, "a changed question is rejected", problems)
    expect("immutable question" in result.stderr, "the error names the question file", problems)
    return problems


def scenario_semantic_membership_changed(directory: Path) -> list[str]:
    """The frozen semantic membership cannot be reduced or replaced."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory, owner_approved=True)
    payload = load(expectations)
    payload["cases"][0]["original_semantic_member"] = False
    payload["semantic_case_count"] = 49
    dump(expectations, payload)
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=dump(directory / "runtime-mapping.json", synthetic_mapping()),
        observations=baseline_observations(synthetic_questions()),
    )
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        "labels_freeze_unverified" in {item["code"] for item in report["blockers"]},
        "changed membership invalidates the freeze",
        problems,
    )
    expect(
        report["semantic"]["cases"] == 49,
        "the changed membership is recorded, never assumed to match the original",
        problems,
    )
    return problems


def scenario_stale_identity_review_rejected(directory: Path) -> list[str]:
    """An expectation change invalidates reviews bound to the old identity."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    observations = baseline_observations(synthetic_questions())
    write_observations(directory / "responses.jsonl", observations)
    reviews = dump(
        directory / "review-decisions.json",
        review_payload(
            observations,
            questions_path=questions,
            expectations_path=expectations,
            mapping_path=mapping,
        ),
    )
    payload = load(expectations)
    payload["cases"][0]["proposed_expectation"]["notes"] = ["a later change"]
    dump(expectations, payload)
    result, _ = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=observations,
        reviews=reviews,
    )
    expect(result.returncode != 0, "reviews bound to other expectations are rejected", problems)
    expect("identity" in result.stderr, "the error names the evaluation identity", problems)
    return problems


def scenario_labels_digest_not_inferred(directory: Path) -> list[str]:
    """Zero unmapped references never substitutes for a verified labels digest."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory, owner_approved=True)
    payload = load(expectations)
    payload["labels_sha256"] = "e" * 64
    dump(expectations, payload)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    result, report = run_score(
        directory,
        questions=questions,
        expectations=expectations,
        mapping=mapping,
        observations=baseline_observations(synthetic_questions()),
    )
    if report is None:
        return problems + [f"no report written: {result.stderr[-500:]}"]
    expect(
        report["dataset"]["labels_digest_status"] == "unverified",
        "the digest is unverified",
        problems,
    )
    expect(
        "labels_digest_unverified" in {item["code"] for item in report["blockers"]},
        "the digest blocks regardless of mapping coverage",
        problems,
    )
    return problems
