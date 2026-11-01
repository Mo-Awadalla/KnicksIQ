"""Original-conversation-context scenarios: bound, sent, scored, never dropped.

The immutable question file carries a ``context`` for the follow-up cases. Three
things can go wrong silently, and each one is driven here through the real CLI:

- the loader could ignore that context or let an expectation restate it, so the
  run would score an answer to a different question than the one labelled;
- the collector could send a request without the turns it is scored against;
- the scorer could credit a response whose recorded request dropped, changed or
  invented a turn, because the answer, the numbers and the response digest are
  untouched.

Every dataset keeps the production denominators (58 answer, 53 clarify, 9
refuse, 50 semantic) and content-bound freeze, approval and review artifacts, so
a scenario cannot pass by disabling a gate. Nothing here contacts a provider,
Redis, Qdrant or PostgreSQL, and nothing approves a label.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from eval_scenario_fixtures import (
    approval_artifact,
    dump,
    freeze_artifact,
    load,
    review_payload,
    run_score,
    synthetic_expectations,
    synthetic_mapping,
    synthetic_questions,
)
from eval_scenario_records import baseline_observations, write_observations
from eval_scenario_support import (
    SEMANTIC_CASES,
    canonical,
    expect,
    failures,
    metric,
)

ORIGINAL_CONTEXT = (
    {"role": "user", "content": "How did the Knicks lose the lead against Boston?"},
    {
        "role": "assistant",
        "content": "Boston took control during a decisive second-half scoring run.",
    },
)
CONTEXT_CASE_IDS = ("answer-001", "answer-002", "clarify-001")
CONTEXT_FAILURES = ("request_context_missing", "request_context_mismatch")


def context_questions() -> list[dict[str, Any]]:
    """The synthetic 120 questions, with original turns on the context cases only."""
    rows = synthetic_questions()
    for row in rows:
        if row["id"] in CONTEXT_CASE_IDS:
            row["context"] = [dict(turn) for turn in ORIGINAL_CONTEXT]
    return rows


def _write_context_dataset(directory: Path) -> tuple[Path, Path]:
    """Freeze and approve artifacts whose digests cover the questions' context."""
    questions_path = directory / "questions.jsonl"
    questions_path.write_text(
        "\n".join(canonical(row) for row in context_questions()) + "\n", encoding="utf-8"
    )
    expectations = synthetic_expectations(owner_approved=True)
    expectations["labels_sha256"] = hashlib.sha256(questions_path.read_bytes()).hexdigest()
    freeze = freeze_artifact(questions_path, expectations)
    expectations["freeze"] = freeze
    expectations["frozen"] = True
    expectations["owner_approval"] = approval_artifact(freeze, expectations)
    return questions_path, dump(directory / "expectation-review.json", expectations)


def context_observations() -> list[dict[str, Any]]:
    """Baseline responses whose recorded requests carry the original turns verbatim."""
    original = {row["id"]: row.get("context") or [] for row in context_questions()}
    rows = baseline_observations(synthetic_questions())
    for row in rows:
        row["request"] = dict(row["request"])
        row["request"]["context"] = [dict(turn) for turn in original[row["case_id"]]]
    return rows


def _score(
    directory: Path, questions: Path, expectations: Path, observations: list[dict[str, Any]]
) -> tuple[Any, dict[str, Any] | None]:
    """Score with a review bound to the exact artifacts and the same 120 responses."""
    responses = write_observations(directory / "responses.jsonl", observations)
    mapping = dump(directory / "runtime-mapping.json", synthetic_mapping())
    rows = [json.loads(line) for line in responses.read_text(encoding="utf-8").splitlines() if line]
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
        observations=observations,
        reviews=reviews,
    )


def _report_case(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in report["cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"case {case_id} missing from report")


def _mutated(
    directory: Path,
    case_id: str,
    change: Callable[[dict[str, Any]], None],
) -> tuple[Any, dict[str, Any] | None]:
    """One request is altered; its response, numbers and digest are untouched."""
    questions, expectations = _write_context_dataset(directory)
    observations = context_observations()
    for row in observations:
        if row["case_id"] == case_id:
            change(row["request"])
    return _score(directory, questions, expectations, observations)


def _assert_no_credit(report: dict[str, Any], case_id: str, code: str, problems: list[str]) -> None:
    """The altered request is unverified, earns no credit and reports no answer error."""
    case = _report_case(report, case_id)
    codes = set(failures(report, case_id))
    expect(code in codes, f"{case_id} reports {code}, got {sorted(codes)}", problems)
    expect(
        not {"numeric_mismatch", "response_hash_mismatch"} & codes,
        f"{case_id} answer and digest are untouched: {sorted(codes)}",
        problems,
    )
    expect(case["verified"] is False, f"{case_id} is not verified", problems)
    expect(case["status"] == "fail", f"{case_id} fails", problems)
    expect(case["checks"]["numeric"] is False, f"{case_id} earns no numeric credit", problems)
    expect(
        metric(report, "canonical_numeric_correctness")["numerator"] == 57,
        "57/58 numeric: the unverified case is withheld",
        problems,
    )
    disposition = metric(report, "disposition_accuracy")
    expect(disposition["numerator"] == 119, "119/120 credited", problems)
    expect(case_id in disposition["failing_cases"], f"{case_id} is named as failing", problems)
    for name in ("paraphrase_quality", "answer_quality"):
        expect(
            metric(report, name)["numerator"] == 57,
            f"{name} withholds the unverified response",
            problems,
        )


def scenario_context_clean(directory: Path) -> list[str]:
    """The immutable turns are bound, sent and scored exactly as the questions file has them."""
    problems: list[str] = []
    questions, expectations = _write_context_dataset(directory)
    result, report = _score(directory, questions, expectations, context_observations())
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(report["dataset"]["case_count"] == 120, "120 cases stay in the dataset", problems)
    expect(
        report["dataset"]["semantic_case_count"] == SEMANTIC_CASES,
        "50 semantic cases stay in the dataset",
        problems,
    )
    expect(
        report["dataset"]["owner_approved"] == 120,
        "the content-bound approval covers all 120 cases",
        problems,
    )
    expect(
        report["dataset"]["frozen"] is True,
        "the freeze covers the context-bearing questions",
        problems,
    )
    offenders = [
        case["id"]
        for case in report["cases"]
        if set(CONTEXT_FAILURES) & {item["code"] for item in case["failures"]}
    ]
    expect(offenders == [], f"no case reports a context failure: {offenders[:5]}", problems)
    expect(
        all(case["verified"] for case in report["cases"]),
        "every recorded request verified",
        problems,
    )
    expect(
        all(case["reviewed"] for case in report["cases"]),
        "every one of the 120 responses carries a bound review",
        problems,
    )
    expect(
        metric(report, "disposition_accuracy")["numerator"] == 120,
        "120/120 credited",
        problems,
    )
    expect(
        metric(report, "canonical_numeric_correctness")["value"] == 1.0,
        "numeric must be measured and passing",
        problems,
    )
    return problems


def scenario_context_omitted_rejected(directory: Path) -> list[str]:
    """A request that omits the original turns is unverified, whatever the answer says."""
    problems: list[str] = []
    result, report = _mutated(directory, "answer-001", lambda request: request.pop("context"))
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    _assert_no_credit(report, "answer-001", "request_context_missing", problems)
    return problems


def scenario_context_dropped_rejected(directory: Path) -> list[str]:
    """Silently discarding the turns (an empty list) is a mismatch, not a neutral request."""
    problems: list[str] = []
    result, report = _mutated(
        directory, "answer-002", lambda request: request.__setitem__("context", [])
    )
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    _assert_no_credit(report, "answer-002", "request_context_mismatch", problems)
    return problems


def scenario_context_changed_rejected(directory: Path) -> list[str]:
    """Rewriting one turn's content fails the case even though every number still matches."""
    problems: list[str] = []

    def rewrite(request: dict[str, Any]) -> None:
        request["context"] = [
            dict(request["context"][0]),
            {"role": "assistant", "content": "Boston led from start to finish."},
        ]

    result, report = _mutated(directory, "answer-001", rewrite)
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    _assert_no_credit(report, "answer-001", "request_context_mismatch", problems)
    return problems


def scenario_context_substituted_rejected(directory: Path) -> list[str]:
    """An invented transcript on a case that had none, or swapped roles, is substituted input."""
    problems: list[str] = []
    questions, expectations = _write_context_dataset(directory)
    invented = context_observations()
    for row in invented:
        if row["case_id"] == "answer-003":
            row["request"] = dict(row["request"])
            row["request"]["context"] = [dict(turn) for turn in ORIGINAL_CONTEXT]
    result, report = _score(directory, questions, expectations, invented)
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    _assert_no_credit(report, "answer-003", "request_context_mismatch", problems)

    def swap(request: dict[str, Any]) -> None:
        request["context"] = [
            {"role": "assistant", "content": ORIGINAL_CONTEXT[0]["content"]},
            {"role": "user", "content": ORIGINAL_CONTEXT[1]["content"]},
        ]

    result, report = _mutated(directory, "answer-001", swap)
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is not None:
        _assert_no_credit(report, "answer-001", "request_context_mismatch", problems)
    return problems


def scenario_context_proposal_override_rejected(directory: Path) -> list[str]:
    """An expectation may not restate the immutable turns; only the questions file may."""
    problems: list[str] = []
    for field in ("context", "proposed_expectation"):
        questions, expectations = _write_context_dataset(directory)
        payload = load(expectations)
        case = next(item for item in payload["cases"] if item["id"] == "answer-001")
        target = case if field == "context" else case["proposed_expectation"]
        target["context"] = [{"role": "user", "content": "What did Brunson score?"}]
        dump(expectations, payload)
        result, _ = _score(directory, questions, expectations, context_observations())
        expect(
            result.returncode != 0,
            f"a proposed {field} context must be refused",
            problems,
        )
    return problems


def scenario_context_frozen_identity(directory: Path) -> list[str]:
    """The context is inside the frozen identity: editing it after the freeze breaks the freeze."""
    problems: list[str] = []
    questions, expectations = _write_context_dataset(directory)
    rows = context_questions()
    for row in rows:
        if row["id"] == "answer-001":
            row["context"] = [
                dict(ORIGINAL_CONTEXT[0]),
                {"role": "assistant", "content": "Boston led from start to finish."},
            ]
    questions.write_text("\n".join(canonical(row) for row in rows) + "\n", encoding="utf-8")
    result, report = _score(directory, questions, expectations, context_observations())
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    expect(
        report["dataset"]["frozen"] is False,
        "a post-freeze context edit is not frozen",
        problems,
    )
    codes = {item["code"] for item in report["blockers"]}
    expect("labels_freeze_unverified" in codes, "the stale freeze blocks explicitly", problems)
    expect(
        report["dataset"]["owner_approved"] == 0,
        "the approval no longer covers the altered questions",
        problems,
    )
    return problems


def scenario_context_whitespace_rejected(directory: Path) -> list[str]:
    problems: list[str] = []
    questions, expectations = _write_context_dataset(directory)
    rows = [json.loads(line) for line in questions.read_text().splitlines() if line.strip()]
    rows[0]["context"][0]["content"] = "\t" + ORIGINAL_CONTEXT[0]["content"] + "\n"
    questions.write_text("\n".join(canonical(row) for row in rows) + "\n", encoding="utf-8")
    payload = load(expectations)
    payload["labels_sha256"] = hashlib.sha256(questions.read_bytes()).hexdigest()
    freeze = freeze_artifact(questions, payload)
    payload["freeze"] = freeze
    payload["owner_approval"] = approval_artifact(freeze, payload)
    dump(expectations, payload)
    result, report = _score(directory, questions, expectations, context_observations())
    expect(result.returncode == 0, f"cli failed: {result.stderr[-1200:]}", problems)
    if report is None:
        return problems + ["no report written"]
    _assert_no_credit(report, "answer-001", "request_context_mismatch", problems)
    return problems
