#!/usr/bin/env python3
"""Measure the live reviewer's false-acceptance rate on gate-passing wrong answers.

The deterministic gate (`review_issues`) verifies numeric provenance: every number token
must equal a supplied claim value, receipt number or capability number. It does not check
subjects, metrics, units, filters, phases or causal claims. Each mutation in
`reviewer_false_acceptance_cases` keeps all numbers inside the trusted set, so the gate
returns no issues and the reviewer call is the only line of defence. Controls are the
recorded correct answers, unmutated.

Run the gate proof without spending provider calls:

    uv run --package knicksiq-api python tools/release/reviewer_false_acceptance.py \
      --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
      --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
      --gate-only

Live measurement (from the repo root, real provider):

    uv run --package knicksiq-api python tools/release/reviewer_false_acceptance.py \
      --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
      --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
      --trials 2 \
      --out docs/release-evidence/llm-primary-20261021/w3-revmeasure/false-acceptance.json \
      --markdown docs/release-evidence/llm-primary-20261021/w3-revmeasure/summary.md
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import analyst_review_replay as replay
from analyst_review_replay import head_review_once, load_models, load_units
from app.services.analyst_provider import reviewer_system_prompt
from app.services.analyst_review_checks import review_issues
from app.services.evidence_contracts import split_review_spans
from reviewer_false_acceptance_cases import CASES, CLASS_RANK, CLASSES, Case


def wilson(successes: int, observations: int, z: float = 1.96) -> list[float] | None:
    if observations == 0:
        return None
    p = successes / observations
    denominator = 1 + z * z / observations
    centre = (p + z * z / (2 * observations)) / denominator
    half = z * math.sqrt(p * (1 - p) / observations + z * z / (4 * observations**2)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def call_metadata(adapter: Any) -> dict[str, Any]:
    metadata = getattr(adapter, "last_metadata", {}) or {}
    usage = metadata.get("usage") or {}
    return {
        "provider": metadata.get("provider"),
        "model": metadata.get("model"),
        "cost_usd": usage.get("cost"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": metadata.get("finish_reason"),
    }


def mutate(attempt: dict[str, Any], case: Case) -> tuple[Any, dict[str, Any], list[str]]:
    answer, _claims, _evidence, _candidates = load_models(attempt)
    text = answer.text
    assert not (case.edits and case.append), f"{case.case_id}: edit and append are exclusive"
    for find, replace in case.edits:
        count = text.count(find)
        assert count == 1, f"{case.case_id}: expected one occurrence of {find!r}, found {count}"
        text = text.replace(find, replace, 1)
    text += case.append
    assert text != answer.text, f"{case.case_id}: mutation did not change the answer"
    mutated = answer.model_copy(update={"text": text})
    payload = copy.deepcopy(attempt["payload"])
    payload["proposed_answer"]["text"] = text
    payload["review_spans"] = split_review_spans(text)
    return mutated, payload, split_review_spans(text)


def gate_issues(
    answer: Any,
    spans: list[str],
    claims: dict[str, Any],
    evidence: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    return review_issues(
        answer,
        spans,
        claims,
        evidence,
        payload.get("capabilities"),
        payload.get("requested_question", ""),
    )


# The replay helper drops provider metadata and accepted review JSON. Both are captured by
# wrapping the two module globals the helper resolves at call time.
_adapters: list[Any] = []
_reviews: list[dict[str, Any] | None] = []
_calls_used: list[list[dict[str, Any]]] = []
_original_factory = replay.get_llm_adapter
_original_call_reviewer = replay.call_reviewer


def _recording_factory(*args: Any, **kwargs: Any) -> Any:
    adapter = _original_factory(*args, **kwargs)
    _adapters.append(adapter)
    return adapter


async def _recording_call_reviewer(
    system: str, payload: dict[str, Any], max_tokens: int = 1200
) -> Any:
    result = await _original_call_reviewer(system, payload, max_tokens)
    review = result.review.model_dump(mode="json") if result.review is not None else None
    _reviews.append(review)
    return result


def install_recorders() -> None:
    replay.get_llm_adapter = _recording_factory
    replay.call_reviewer = _recording_call_reviewer


async def run_trial(
    system: str,
    payload: dict[str, Any],
    answer: Any,
    claims: dict[str, Any],
    evidence: dict[str, Any],
    spans: list[str],
) -> dict[str, Any]:
    started = time.monotonic()
    adapter_start = len(_adapters)
    review_start = len(_reviews)
    outcome = await head_review_once(system, payload, answer, claims, evidence, spans)
    calls = [call_metadata(adapter) for adapter in _adapters[adapter_start:]]
    review = _reviews[review_start] if len(_reviews) > review_start else None
    if outcome["outcome"] == "malformed_review_json":
        retry_adapter_start = len(_adapters)
        retry_review_start = len(_reviews)
        retry = await head_review_once(system, payload, answer, claims, evidence, spans)
        calls += [call_metadata(adapter) for adapter in _adapters[retry_adapter_start:]]
        if len(_reviews) > retry_review_start:
            review = _reviews[retry_review_start]
        retry["retried"] = True
        retry["cost"] = (retry.get("cost") or 0) + (outcome.get("cost") or 0)
        outcome = retry
    _calls_used.append(calls)
    return {
        "outcome": outcome["outcome"],
        "accepted": outcome["outcome"] == "accepted",
        "causes": outcome.get("causes", []),
        "error": outcome.get("error"),
        "retried": outcome.get("retried", False),
        "cost_usd": outcome.get("cost"),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "calls": calls,
        "review": review,
    }


def control_row(
    record_id: str, attempt: dict[str, Any]
) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any], list[str], dict[str, Any]]:
    answer, claims, evidence, _candidates = load_models(attempt)
    payload = copy.deepcopy(attempt["payload"])
    spans = split_review_spans(answer.text)
    issues = gate_issues(answer, spans, claims, evidence, payload)
    assert issues == [], f"control {record_id} failed the gate: {issues}"
    row = {
        "case_id": f"control:{record_id}",
        "unit": record_id,
        "answer": answer.text,
        "gate_issues": issues,
        "observations": [],
    }
    return row, answer, claims, evidence, spans, payload


def mutation_row(
    case: Case, attempt: dict[str, Any]
) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any], list[str], dict[str, Any]]:
    answer, claims, evidence, _candidates = load_models(attempt)
    mutated, payload, spans = mutate(attempt, case)
    issues = gate_issues(mutated, spans, claims, evidence, payload)
    # The deterministic gate improves over time; a case it now rejects never reaches the
    # reviewer, so it is recorded as gate_rejected and excluded from the reviewer rate.
    row = {
        "case_id": case.case_id,
        "class": case.class_name,
        "unit": case.unit_id,
        "why_gate_passes": case.why_gate_passes,
        "gate_issues": issues,
        "original": answer.text,
        "mutated": mutated.text,
        "append": case.append,
        "edits": list(case.edits),
        "observations": [],
    }
    return row, mutated, claims, evidence, spans, payload


async def measure(units: list[tuple[str, str, dict[str, Any], str]], trials: int) -> dict[str, Any]:
    by_record: dict[str, dict[str, Any]] = {}
    for _unit_id, record_id, attempt, _label in units:
        assert record_id not in by_record, f"multiple review attempts for {record_id}"
        by_record[record_id] = attempt
    system = reviewer_system_prompt()
    controls = []
    for _unit_id, record_id, attempt, label in units:
        if label != "correct":
            continue
        row, answer, claims, evidence, spans, payload = control_row(record_id, attempt)
        for trial in range(trials):
            outcome = await run_trial(system, payload, answer, claims, evidence, spans)
            outcome["trial"] = trial
            row["observations"].append(outcome)
            print(
                json.dumps(
                    {
                        "case": row["case_id"],
                        "trial": trial,
                        "outcome": outcome["outcome"],
                        "provider": (outcome["calls"] or [{}])[-1].get("provider"),
                    }
                ),
                flush=True,
            )
        controls.append(row)
    mutations = []
    for case in CASES:
        if case.unit_id not in by_record:
            raise SystemExit(f"missing recorded unit {case.unit_id}")
        row, answer, claims, evidence, spans, payload = mutation_row(case, by_record[case.unit_id])
        if row["gate_issues"]:
            mutations.append(row)
            continue
        for trial in range(trials):
            outcome = await run_trial(system, payload, answer, claims, evidence, spans)
            outcome["trial"] = trial
            row["observations"].append(outcome)
            print(
                json.dumps(
                    {
                        "case": case.case_id,
                        "trial": trial,
                        "outcome": outcome["outcome"],
                        "provider": (outcome["calls"] or [{}])[-1].get("provider"),
                    }
                ),
                flush=True,
            )
        mutations.append(row)
    return {"controls": controls, "mutations": mutations}


def summarize_group(rows: list[dict[str, Any]], trials: int) -> dict[str, Any]:
    observations = [obs for row in rows for obs in row["observations"]]
    accepted = sum(1 for obs in observations if obs["accepted"])
    calls = [call for obs in observations for call in obs["calls"]]
    cost = sum(call.get("cost_usd") or 0 for call in calls)
    return {
        "cases": len(rows),
        "trials_per_case": trials,
        "observations": len(observations),
        "accepted": accepted,
        "accept_rate": round(accepted / len(observations), 4) if observations else None,
        "wilson_95": wilson(accepted, len(observations)),
        "cost_usd": round(cost, 6),
        "reviewer_calls": len(calls),
        "providers": dict(Counter(call.get("provider") for call in calls)),
        "models": dict(Counter(call.get("model") for call in calls)),
    }


def worst_accepted(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    examples = []
    for row in rows:
        for obs in row["observations"]:
            if not obs["accepted"]:
                continue
            assertions = [
                {
                    "text": item.get("text"),
                    "type": item.get("assertion_type"),
                    "verdict": item.get("verdict"),
                    "reason": item.get("reason"),
                }
                for item in (obs.get("review") or {}).get("assertions", [])
            ]
            examples.append(
                {
                    "case_id": row["case_id"],
                    "class": row["class"],
                    "unit": row["unit"],
                    "answer": row["mutated"],
                    "edit": row["edits"],
                    "append": row["append"],
                    "trial": obs["trial"],
                    "provider": (obs["calls"] or [{}])[-1].get("provider"),
                    "review_assertions": assertions,
                }
            )
            break
    examples.sort(key=lambda item: CLASS_RANK.get(item["class"], 99))
    return examples[:limit]


def build_summary(artifact: dict[str, Any]) -> str:
    controls = artifact["controls_summary"]
    lines = [
        "# Reviewer false acceptance, live",
        "",
        f"Measured {artifact['measured_at']} against the real provider, model "
        f"`{artifact['model']}`, {artifact['trials_per_case']} trials per case. "
        f"Reviewer calls: {artifact['reviewer_calls']}; cost: ${artifact['cost_usd']:.4f}.",
        "",
        "## Per class",
        "",
        "| class | cases | trials | accepted | accept rate | Wilson 95% | cost USD | providers |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for name, row in artifact["by_class"].items():
        low, high = row["wilson_95"]
        providers = ", ".join(f"{key}:{value}" for key, value in row["providers"].items())
        lines.append(
            f"| {name} | {row['cases']} | {row['observations']} | {row['accepted']} | "
            f"{row['accept_rate']:.3f} | [{low:.3f}, {high:.3f}] | "
            f"{row['cost_usd']:.4f} | {providers} |"
        )
    low, high = controls["wilson_95"]
    lines.extend(
        [
            "",
            f"Controls (unmutated correct answers): {controls['accepted']}/"
            f"{controls['observations']} accepted, rate {controls['accept_rate']:.3f}, "
            f"Wilson [{low:.3f}, {high:.3f}], cost ${controls['cost_usd']:.4f}.",
            "",
            "All cases passed the deterministic gate with zero issues; the recorded "
            "`gate_issues` arrays are empty.",
            "",
            "## Worst accepted examples",
            "",
        ]
    )
    if not artifact["worst_accepted"]:
        lines.append("None.")
    for item in artifact["worst_accepted"]:
        lines.append(
            f"- `{item['case_id']}` ({item['class']}, {item['provider']}): {item['answer']}"
        )
    lines.append("")
    return "\n".join(lines)


def dry_run(
    units: list[tuple[str, str, dict[str, Any], str]], args: argparse.Namespace
) -> dict[str, Any]:
    by_record = {record_id: attempt for _uid, record_id, attempt, _label in units}
    controls = []
    for _uid, record_id, attempt, label in units:
        if label != "correct":
            continue
        _row, answer, _claims, _evidence, _spans, _payload = control_row(record_id, attempt)
        controls.append(
            {
                "case_id": f"control:{record_id}",
                "unit": record_id,
                "answer": answer.text,
                "gate_issues": [],
            }
        )
    rows = []
    for case in CASES:
        row, _answer, _claims, _evidence, _spans, _payload = mutation_row(
            case, by_record[case.unit_id]
        )
        rows.append(
            {
                "case_id": case.case_id,
                "class": case.class_name,
                "unit": case.unit_id,
                "why_gate_passes": case.why_gate_passes,
                "original": row["original"],
                "mutated": row["mutated"],
                "edits": row["edits"],
                "append": row["append"],
                "gate_issues": row["gate_issues"],
            }
        )
    return {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "records": [str(path) for path in args.records],
        "labels": str(args.labels),
        "classes": CLASSES,
        "all_passed": all(not row["gate_issues"] for row in controls + rows),
        "controls": controls,
        "mutations": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", nargs="+", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--gate-only", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text())
    units = load_units(args.records, labels)
    if not units:
        raise SystemExit("No labeled review units")
    if args.gate_only:
        proof = dry_run(units, args)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(proof, indent=2) + "\n")
        print(json.dumps(proof, indent=2))
        return
    if args.out is None:
        raise SystemExit("--out is required outside --gate-only")
    trials = max(1, args.trials)
    install_recorders()
    measured = asyncio.run(measure(units, trials))
    by_class = {}
    for name in CLASSES:
        rows = [row for row in measured["mutations"] if row["class"] == name]
        by_class[name] = summarize_group(rows, trials)
    all_calls = [call for obs in _calls_used for call in obs]
    models = Counter(call.get("model") for call in all_calls)
    artifact: dict[str, Any] = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": models.most_common(1)[0][0] if models else None,
        "records": [str(path) for path in args.records],
        "labels": str(args.labels),
        "trials_per_case": trials,
        "classes": CLASSES,
        "gate_proof": {
            "all_passed": all(
                not row["gate_issues"] for row in measured["controls"] + measured["mutations"]
            ),
            "controls": [
                {"case_id": row["case_id"], "gate_issues": row["gate_issues"]}
                for row in measured["controls"]
            ],
            "mutations": [
                {"case_id": row["case_id"], "gate_issues": row["gate_issues"]}
                for row in measured["mutations"]
            ],
        },
        "controls_summary": summarize_group(measured["controls"], trials),
        "mutations_summary": summarize_group(measured["mutations"], trials),
        "by_class": by_class,
        "reviewer_calls": len(all_calls),
        "cost_usd": round(sum(call.get("cost_usd") or 0 for call in all_calls), 6),
        "providers": dict(Counter(call.get("provider") for call in all_calls)),
        "models": dict(models),
        "controls": measured["controls"],
        "mutations": measured["mutations"],
        "worst_accepted": worst_accepted(measured["mutations"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2) + "\n")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(build_summary(artifact) + "\n")
    print(
        json.dumps(
            {
                key: artifact[key]
                for key in (
                    "controls_summary",
                    "mutations_summary",
                    "by_class",
                    "reviewer_calls",
                    "cost_usd",
                    "providers",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
