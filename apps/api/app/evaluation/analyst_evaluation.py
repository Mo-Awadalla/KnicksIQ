"""Repeated real-provider conversations and explicit, human-reviewed release gates.

Run against a private development API with the evidence loop enabled. No model is
substituted. Fixtures are test prompts, not production conversation logging.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.evaluation.analyst_probe import probe
from app.services.evidence_contracts import CONTRACT_VERSION

SIX_TURNS = [
    "Give me an interesting stat.",
    "Why is that interesting?",
    "Another one, but about a different player.",
    "Now only playoff games.",
    "Does that prove he was playing better?",
    "Is he injured today, and how did he perform in the archived playoffs?",
]


def percentile(values: list[float], percentile: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * percentile) - 1)] if values else None


def release_gates(metrics: dict[str, Any]) -> dict[str, bool]:
    """Missing labels or measurements fail closed; fallback is never an LLM success."""
    return {
        "provider_capability": metrics.get("provider_capability_passed") is True,
        "unsupported_claims": metrics.get("reviewed_answers", 0) > 0
        and metrics.get("unsupported_claims") == 0,
        "calculation_entity_scope_citation": metrics.get("all_structured_checks_passed") is True,
        "search_recall_at_5": metrics.get("applicable_search_tasks", 0) > 0
        and metrics.get("search_recall_at_5", 0) >= 0.95,
        "answerable_completion": metrics.get("answerable_completion", 0) >= 0.95,
        "normal_llm_completion": metrics.get("normal_llm_completion", 0) >= 0.95,
        "boundaries_and_mixed": metrics.get("boundary_and_mixed_passed") is True,
        "delivery_rubric": metrics.get("human_delivery_pass_rate", 0) >= 0.90,
        "latency": metrics.get("warm_ordinary_p95_ms", float("inf")) <= 15000
        and metrics.get("max_processing_ms", float("inf")) <= 30000,
        "request_errors": metrics.get("request_error_rate", 1) < 0.01,
        "heldout_reviewer": metrics.get("human_labelled_challenges", 0) > 0
        and metrics.get("unsupported_challenges_accepted") == 0,
        "reviewed_promotion": metrics.get("release_approval_recorded") is True,
    }


async def evaluate(base_url: str, repetitions: int) -> dict[str, Any]:
    capabilities = await probe()
    report: dict[str, Any] = {
        "model": get_settings().ai_chat_model,
        "contract_version": CONTRACT_VERSION,
        "provider_probe": capabilities,
        "repetitions": repetitions,
        "conversations": [],
        "metrics": {},
        "promotion_allowed": False,
        "human_review_status": "pending",
    }
    passed = len(capabilities["results"]) == 3 and all(r["passed"] for r in capabilities["results"])
    report["metrics"]["provider_capability_passed"] = passed
    if not passed:
        report["blocked_reason"] = "Configured provider did not pass schema capability probes."
        report["gates"] = release_gates(report["metrics"])
        return report
    async with httpx.AsyncClient(base_url=base_url, timeout=35) as client:
        for trial in range(repetitions):
            context, token, revision = [], None, 0
            turns = []
            for question in SIX_TURNS:
                turn_id = uuid.uuid4().hex
                request = dict(
                    question=question,
                    context=context[-10:],
                    session_token=token,
                    expected_revision=revision,
                    turn_id=turn_id,
                )
                started = time.monotonic()
                try:
                    response = await client.post("/analysis/query", json=request)
                    response.raise_for_status()
                    body = response.json()
                    token, revision = body.get("session_token"), body.get("revision", 0)
                    context.extend(
                        [
                            {"role": "user", "content": question},
                            {"role": "assistant", "content": body["answer"]},
                        ]
                    )
                    turns.append(
                        {
                            "question": question,
                            "response": body,
                            "latency_ms": round((time.monotonic() - started) * 1000),
                            "human_review": None,
                        }
                    )
                    replay = await client.post("/analysis/query", json=request)
                    turns[-1]["replay_equal"] = replay.json() == body
                except (httpx.HTTPError, ValueError) as exc:
                    turns.append({"question": question, "error": type(exc).__name__})
                    break
            report["conversations"].append({"trial": trial, "turns": turns})
    turns = [turn for trial in report["conversations"] for turn in trial["turns"]]
    report["metrics"].update(
        normal_llm_completion=sum(t.get("response", {}).get("llm_validated", False) for t in turns)
        / max(1, repetitions * len(SIX_TURNS)),
        request_error_rate=sum("error" in t for t in turns) / max(1, len(turns)),
    )
    # Do not combine multi-round/repair/cold and ordinary latency into a misleading p95.
    report["latency_samples_ms"] = [t["latency_ms"] for t in turns if "latency_ms" in t]
    report["gates"] = release_gates(report["metrics"])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 5:
        parser.error("Release evaluation requires at least five repetitions.")
    result = asyncio.run(evaluate(args.base_url, args.repetitions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({"promotion_allowed": result["promotion_allowed"], "gates": result["gates"]}))
