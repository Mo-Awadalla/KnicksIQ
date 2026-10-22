#!/usr/bin/env python3
"""Replay recorded reviewer calls offline from the writer, on base and fixed reviewer code.

Base mode reproduces the contract that shipped on codex/llmp-integration: the recorded system
prompt, the recorded user payload, and a frozen copy of the old validation rules. Head mode runs
the deterministic checks and the current reviewer against the same recorded answer and claims.
No writer call is made, so differences are attributable to the reviewer path.

    uv run --package knicksiq-api python tools/release/analyst_review_replay.py \
      --records docs/release-evidence/llm-primary-20261021/reviewer/base-*.jsonl \
      --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
      --trials 3 --out docs/release-evidence/llm-primary-20261021/reviewer/replay.json
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from analyst_review_base import (
    BASE_REVIEWER_PROMPT,
    failure_kind,
    frozen_base_validate_review,
    frozen_base_validate_structure,
    load_models,
    reject_causes,
)
from app.core.config import get_settings
from app.services.analyst_provider import (
    configure_reviewer,
    encoded,
    get_llm_adapter,
    reviewer_system_prompt,
)
from app.services.analyst_review_checks import number_tokens, review_issues, trusted_numbers
from app.services.evidence_contracts import (
    AnswerReview,
    Evidence,
    ProposedAnswer,
    VerifiedClaim,
    claim_value_issues,
    split_review_spans,
    validate_review,
    validate_structure,
)
from pydantic import ValidationError
from review_measurement_stats import reviewer_stats


@dataclass
class CallResult:
    review: AnswerReview | None
    raw: str | None
    error: str | None
    cost: float | None
    metadata: dict[str, Any] | None = None
    latency_ms: float | None = None
    requested_model: str | None = None


async def call_reviewer(
    system: str, payload: dict[str, Any], max_tokens: int | None = None
) -> CallResult:
    adapter = get_llm_adapter()
    # Measure the deployed reviewer: its model and cap, unless a cap is given explicitly.
    configure_reviewer(adapter, get_settings())
    if max_tokens:
        adapter.max_tokens = max_tokens
    adapter.timeout_seconds = 30
    if hasattr(adapter, "response_schema"):
        adapter.response_schema = None
    # The adapter starts with a random x-opencode-session id (report_llm), which Go requires.
    requested_model = getattr(adapter, "model", None)
    # Do not let a failed call expose the previous call's metadata.
    adapter.last_metadata = {}
    started = time.monotonic()

    def elapsed() -> float:
        return round((time.monotonic() - started) * 1000, 1)

    def metadata() -> dict[str, Any]:
        return dict(getattr(adapter, "last_metadata", {}) or {})

    try:
        raw = await asyncio.wait_for(
            adapter.generate(system=system, user=encoded(payload)), timeout=30
        )
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        return CallResult(None, None, text, None, metadata(), elapsed(), requested_model)
    observed = metadata()
    cost = (observed.get("usage") or {}).get("cost")
    try:
        return CallResult(
            AnswerReview.model_validate_json(raw),
            raw,
            None,
            cost,
            observed,
            elapsed(),
            requested_model,
        )
    except ValidationError as exc:
        return CallResult(
            None, raw, f"ValidationError: {exc}", cost, observed, elapsed(), requested_model
        )


async def base_trial(attempt: dict[str, Any]) -> dict[str, Any]:
    answer, claims, evidence, candidates = load_models(attempt)
    release = next(iter(claims.values())).release_id if claims else ""
    if not frozen_base_validate_structure(answer, claims, evidence, candidates, release):
        return {"outcome": "structure_rejected", "causes": ["structure"], "cost": None}
    payload = attempt.get("payload")
    if not payload:
        return {"outcome": "no_recorded_review", "causes": [], "cost": None}
    result = await call_reviewer(BASE_REVIEWER_PROMPT, payload)
    if result.review is None:
        kind = failure_kind(result.error)
        return {"outcome": kind, "causes": [], "cost": result.cost, "error": result.error}
    if frozen_base_validate_review(result.review, answer, claims, evidence):
        return {"outcome": "accepted", "causes": [], "cost": result.cost}
    causes = reject_causes(result.review, answer, claims, evidence, [], spans_are_positional=False)
    return {
        "outcome": "verdict_rejected",
        "causes": causes,
        "cost": result.cost,
        "review": result.review.model_dump(mode="json"),
    }


async def head_review_once(
    system: str,
    payload: dict[str, Any],
    answer: ProposedAnswer,
    claims: dict[str, VerifiedClaim],
    evidence: dict[str, Evidence],
    spans: list[str],
) -> dict[str, Any]:
    result = await call_reviewer(system, payload)
    observed = {
        "metadata": result.metadata,
        "latency_ms": result.latency_ms,
        "requested_model": result.requested_model,
    }
    if result.review is None:
        kind = failure_kind(result.error)
        return {
            "outcome": kind,
            "causes": [],
            "cost": result.cost,
            "error": result.error,
            **observed,
        }
    if validate_review(result.review, answer, claims, evidence, spans=spans):
        return {"outcome": "accepted", "causes": [], "cost": result.cost, **observed}
    causes = reject_causes(
        result.review, answer, claims, evidence, spans, spans_are_positional=True
    )
    return {
        "outcome": "verdict_rejected",
        "causes": causes,
        "cost": result.cost,
        "review": result.review.model_dump(mode="json"),
        **observed,
    }


async def head_trial(attempt: dict[str, Any]) -> dict[str, Any]:
    answer, claims, evidence, candidates = load_models(attempt)
    release = next(iter(claims.values())).release_id if claims else ""
    if not validate_structure(answer, claims, evidence, candidates, release):
        return {
            "outcome": "structure_rejected",
            "causes": claim_value_issues(answer, claims) or ["structure"],
            "cost": None,
        }
    spans = split_review_spans(answer.text)
    payload = attempt.get("payload") or {}
    capabilities = payload.get("capabilities") or attempt.get("capabilities")
    question = payload.get("requested_question") or attempt.get("question", "")
    issues = review_issues(
        answer,
        spans,
        claims,
        evidence,
        capabilities,
        question,
    )
    if issues:
        return {"outcome": "deterministic_rejected", "causes": issues, "cost": None}
    if not payload:
        return {"outcome": "no_recorded_review", "causes": [], "cost": None}
    system = reviewer_system_prompt()
    outcome = await head_review_once(system, payload, answer, claims, evidence, spans)
    if outcome["outcome"] == "malformed_review_json":
        retry = await head_review_once(system, payload, answer, claims, evidence, spans)
        retry["retried"] = True
        retry["first_attempt"] = {
            key: outcome.get(key) for key in ("outcome", "metadata", "latency_ms")
        }
        retry["cost"] = (retry.get("cost") or 0) + (outcome.get("cost") or 0)
        retry["latency_ms"] = round(
            (retry.get("latency_ms") or 0) + (outcome.get("latency_ms") or 0), 1
        )
        return retry
    return outcome


def mutation_candidates(attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    reserved = trusted_numbers(claims, evidence, (attempt.get("payload") or {}).get("capabilities"))
    claim_values = [
        Decimal(str(claim.value))
        for claim in claims.values()
        if isinstance(claim.value, (int, float)) and not isinstance(claim.value, bool)
    ]
    mutated: list[dict[str, Any]] = []
    for token in number_tokens(answer.text):
        if token.value not in claim_values and not any(
            abs(token.value - value) <= token.tolerance for value in claim_values
        ):
            continue
        if token.value < 3:
            continue
        unit = Decimal(1).scaleb(-token.decimals)
        for multiplier in (1, 2, 3, 7, 13):
            replacement = token.value + unit * multiplier
            if any(abs(replacement - value) <= token.tolerance for value in reserved):
                continue
            if any(abs(replacement - value) <= token.tolerance for value in claim_values):
                continue
            raw = f"{replacement:.{token.decimals}f}"
            new_text = answer.text.replace(token.raw, raw, 1)
            if new_text == answer.text:
                continue
            new_answer = answer.model_copy(update={"text": new_text})
            spans = split_review_spans(new_text)
            if not review_issues(
                new_answer,
                spans,
                claims,
                evidence,
                (attempt.get("payload") or {}).get("capabilities"),
                (attempt.get("payload") or {}).get("requested_question", ""),
            ):
                continue
            payload = copy.deepcopy(attempt["payload"])
            payload["proposed_answer"]["text"] = new_text
            payload["review_spans"] = spans
            mutated.append(
                {
                    "kind": "text_number_swap",
                    "original": token.raw,
                    "replacement": raw,
                    "answer": new_answer.model_dump(mode="json"),
                    "payload": payload,
                    "spans": spans,
                }
            )
            break
        if mutated:
            break
    declared = {use.claim_id for use in answer.claims}
    numeric = [
        claim
        for claim_id, claim in claims.items()
        if claim_id in declared
        and isinstance(claim.value, (int, float))
        and not isinstance(claim.value, bool)
    ]
    if numeric:
        first = numeric[0]
        wrong = copy.deepcopy(claims)
        changed = wrong[first.claim_id].model_copy(
            update={"value": first.value + 3, "statement": first.statement}
        )
        wrong[first.claim_id] = changed
        payload = copy.deepcopy(attempt["payload"])
        for view in payload.get("claims", []):
            if view["claim_id"] == first.claim_id:
                view["value"] = changed.value
        mutated.append(
            {
                "kind": "claim_value_mismatch",
                "original": first.value,
                "replacement": changed.value,
                "answer": answer.model_dump(mode="json"),
                "payload": payload,
                "spans": split_review_spans(answer.text),
                "claims": {key: value.model_dump(mode="json") for key, value in wrong.items()},
            }
        )
    return mutated


async def run_trials(
    units: list[tuple[str, str, dict[str, Any], str]], trials: int, modes: set[str]
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    total_cost = 0.0
    for unit_id, record_id, attempt, _label in units:
        entry: dict[str, Any] = {"base": [], "head": []}
        for mode in ("base", "head"):
            if mode not in modes:
                continue
            for trial in range(trials):
                outcome = await (base_trial if mode == "base" else head_trial)(attempt)
                entry[mode].append(outcome)
                total_cost += outcome.get("cost") or 0
                print(
                    json.dumps(
                        {
                            "unit": unit_id,
                            "id": record_id,
                            "mode": mode,
                            "trial": trial,
                            "outcome": outcome["outcome"],
                        }
                    ),
                    flush=True,
                )
        results[unit_id] = entry
    return {"results": results, "cost_usd": round(total_cost, 6)}


def summarize(
    units: list[tuple[str, str, dict[str, Any], str]],
    replay: dict[str, Any],
    trials: int,
) -> dict[str, Any]:
    def rate(mode: str, verdict: str) -> dict[str, Any]:
        ids = [unit_id for unit_id, _rid, _attempt, label in units if label == verdict]
        outcomes = Counter(
            outcome["outcome"] for unit_id in ids for outcome in replay["results"][unit_id][mode]
        )
        rejected = sum(
            1
            for unit_id in ids
            for outcome in replay["results"][unit_id][mode]
            if outcome["outcome"] not in {"accepted", "no_recorded_review"}
        )
        return {
            "answers": len(ids),
            "trials": trials,
            "rejected": rejected,
            "observations": len(ids) * trials,
            "reject_rate": round(rejected / (len(ids) * trials), 3) if ids and trials else None,
            "outcomes": dict(outcomes),
            "per_answer": {
                unit_id: [outcome["outcome"] for outcome in replay["results"][unit_id][mode]]
                for unit_id in ids
            },
        }

    causes = Counter()
    for entry in replay["results"].values():
        for mode in ("base", "head"):
            for outcome in entry[mode]:
                for cause in outcome.get("causes", []):
                    causes[f"{mode}:{cause}"] += 1
    return {
        "correct": {"base": rate("base", "correct"), "head": rate("head", "correct")},
        "wrong": {"base": rate("base", "wrong"), "head": rate("head", "wrong")},
        "causes": dict(causes),
    }


async def run_mutations(
    units: list[tuple[str, str, dict[str, Any], str]], trials: int
) -> dict[str, Any]:
    rows = []
    for unit_id, record_id, attempt, _label in units:
        for mutation in mutation_candidates(attempt):
            row: dict[str, Any] = {
                "unit": unit_id,
                "id": record_id,
                "kind": mutation["kind"],
                "original": mutation["original"],
                "replacement": mutation["replacement"],
                "base": [],
                "head": [],
            }
            requires_claims = mutation.get("claims")
            for _trial in range(trials):
                mutated_attempt = copy.deepcopy(attempt)
                mutated_attempt["answer"] = mutation["answer"]
                mutated_attempt["payload"] = mutation["payload"]
                if requires_claims:
                    mutated_attempt["claims"] = requires_claims
                head = await head_trial(mutated_attempt)
                base = await base_trial(mutated_attempt)
                row["head"].append(head["outcome"])
                row["base"].append(base["outcome"])
            rows.append(row)
            print(
                json.dumps(
                    {
                        "mutation": record_id,
                        "kind": mutation["kind"],
                        "head": row["head"],
                        "base": row["base"],
                    }
                ),
                flush=True,
            )
    wrong_kinds = {"text_number_swap", "claim_value_mismatch"}
    accepted = Counter()
    observations = Counter()
    for row in rows:
        if row["kind"] not in wrong_kinds:
            continue
        for mode in ("base", "head"):
            observations[mode] += len(row[mode])
            accepted[mode] += sum(1 for outcome in row[mode] if outcome == "accepted")
    return {
        "rows": rows,
        "wrong_number_observations": dict(observations),
        "wrong_number_acceptances": dict(accepted),
        "zero_head_acceptances": accepted.get("head", 0) == 0,
    }


def load_units(
    paths: list[Path], labels: dict[str, Any]
) -> list[tuple[str, str, dict[str, Any], str]]:
    units: list[tuple[str, str, dict[str, Any], str]] = []
    for path in paths:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            label = labels.get(record["id"])
            if not label:
                continue
            index = 0
            for attempt in record["attempts"]:
                if attempt["kind"] != "review":
                    continue
                verdicts = label.get("attempt_verdicts") or []
                verdict = verdicts[index] if index < len(verdicts) else label.get("verdict")
                index += 1
                if not attempt.get("payload") or verdict not in {"correct", "wrong"}:
                    continue
                units.append((f"{record['id']}#{index - 1}", record["id"], attempt, verdict))
    return units


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", nargs="+", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--modes", default="base,head")
    parser.add_argument("--mutations", action="store_true")
    parser.add_argument("--mutations-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text())
    units = load_units(args.records, labels)
    if not units:
        raise SystemExit("No labeled review units")
    modes = {item.strip() for item in args.modes.split(",") if item.strip()}
    if args.mutations_only:
        artifact = {
            "units": len(units),
            "trials": max(1, min(args.trials, 2)),
            "mutations": asyncio.run(run_mutations(units, max(1, min(args.trials, 2)))),
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(artifact, indent=2))
        print(json.dumps(artifact["mutations"], indent=2))
        return
    replay = asyncio.run(run_trials(units, args.trials, modes))
    stats = reviewer_stats(replay, get_settings())
    artifact: dict[str, Any] = {
        "units": len(units),
        "trials": args.trials,
        "modes": sorted(modes),
        "reviewer_model": stats["reviewer_model_requested"],
        "reviewer_max_tokens": stats["reviewer_max_tokens"],
        "reviewer": stats,
        "replay": replay,
        "rates": summarize(units, replay, args.trials),
    }
    if args.mutations:
        artifact["mutations"] = asyncio.run(run_mutations(units, max(1, min(args.trials, 2))))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2))
    print(json.dumps({key: value for key, value in artifact.items() if key != "replay"}, indent=2))


if __name__ == "__main__":
    main()
