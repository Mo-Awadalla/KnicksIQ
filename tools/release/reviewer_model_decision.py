#!/usr/bin/env python3
"""Combine the reviewer false-acceptance and replay artifacts into one model decision.

Both arms must be measured with identical inputs, switching only `ANALYST_REVIEW_MODEL`.
This tool reads, never calls a provider.

    uv run --package knicksiq-api python tools/release/reviewer_model_decision.py \
      --arm gpt-6-luna:false-acceptance-gpt-6-luna.json:replay-gpt-6-luna.json \
      --arm deepseek-v4.1-flash:false-acceptance-deepseek.json:replay-deepseek.json \
      --out docs/.../decision.json --markdown docs/.../summary.md
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def wilson(successes: int, observations: int, z: float = 1.96) -> list[float] | None:
    if observations == 0:
        return None
    p = successes / observations
    denominator = 1 + z * z / observations
    centre = (p + z * z / (2 * observations)) / denominator
    half = z * math.sqrt(p * (1 - p) / observations + z * z / (4 * observations**2)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def proportion(successes: int, observations: int) -> dict[str, Any]:
    return {
        "count": successes,
        "observations": observations,
        "rate": round(successes / observations, 4) if observations else None,
        "wilson_95": wilson(successes, observations),
    }


def malformed_calls(false_acceptance: dict[str, Any], replay: dict[str, Any]) -> int:
    """Provider replies that failed JSON validation, counting each retried first attempt."""
    final_malformed = false_acceptance["reviewer"]["outcomes"].get("malformed_review_json", 0)
    final_malformed += replay["reviewer"].get("malformed_reviews", 0)
    retried = false_acceptance["reviewer"].get("retried_trials", 0)
    retried += replay["reviewer"].get("retried_trials", 0)
    return final_malformed + retried


def build_arm(name: str, false_acceptance_path: Path, replay_path: Path) -> dict[str, Any]:
    fa = json.loads(false_acceptance_path.read_text())
    rp = json.loads(replay_path.read_text())
    wrong = fa["mutations_summary"]
    controls = fa["controls_summary"]
    correct_units = rp["rates"]["correct"]["head"]
    wrong_units = rp["rates"]["wrong"]["head"]
    calls = fa["reviewer"]["calls"] + rp["reviewer"]["provider_calls"]
    bad = malformed_calls(fa, rp)
    # "Wrong accepted" is every observation of a wrong answer the pipeline accepted:
    # mutated answers that beat the deterministic gate, plus recorded wrong writer answers.
    mutated_accepted = wrong["accepted"]
    recorded_accepted = wrong_units["observations"] - wrong_units["rejected"]
    total_accepted = mutated_accepted + recorded_accepted
    total_wrong = wrong["observations"] + wrong_units["observations"]
    return {
        "model": name,
        "false_acceptance": str(false_acceptance_path),
        "replay": str(replay_path),
        "reviewer_max_tokens": {
            "false_acceptance": fa["reviewer_max_tokens"],
            "replay": rp["reviewer_max_tokens"],
            "observed_false_acceptance": fa["reviewer"]["observed_max_tokens"],
            "observed_replay": rp["reviewer"]["observed_max_tokens"],
        },
        "models": {
            "requested_false_acceptance": fa["reviewer"]["requested_models"],
            "served_false_acceptance": fa["reviewer"]["served_models"],
            "requested_replay": rp["reviewer"]["requested_models"],
            "served_replay": rp["reviewer"]["served_models"],
            "protocols_false_acceptance": fa["reviewer"]["protocols"],
            "protocols_replay": rp["reviewer"]["protocols"],
        },
        "wrong_accepted": {
            **proportion(total_accepted, total_wrong),
            "mutated": proportion(mutated_accepted, wrong["observations"]),
            "recorded": proportion(recorded_accepted, wrong_units["observations"]),
        },
        "wrong_accepted_mutations": proportion(mutated_accepted, wrong["observations"]),
        "controls_accepted": proportion(controls["accepted"], controls["observations"]),
        "false_rejects": proportion(correct_units["rejected"], correct_units["observations"]),
        "true_rejects": proportion(wrong_units["rejected"], wrong_units["observations"]),
        "malformed_reviews": {
            **proportion(bad, calls),
            "provider_calls": calls,
        },
        "latency_ms": {
            # Review call only (HTTP + parse), from the mixed controls+mutations arm.
            "p50": fa["reviewer"]["call_latency_ms"]["p50"],
            "p95": fa["reviewer"]["call_latency_ms"]["p95"],
            "samples": fa["reviewer"]["call_latency_ms"]["samples"],
            "source": "false-acceptance provider calls",
        },
        "replay_latency_ms": rp["reviewer"]["latency_ms"],
        "cost_per_review": fa["reviewer"]["cost_per_call"],
        "replay_cost_per_review": rp["reviewer"]["cost_per_review"],
        "cost_usd": {
            "false_acceptance": fa["reviewer"]["cost_usd"],
            "replay": rp["reviewer"]["cost_usd"],
            "total": round(fa["reviewer"]["cost_usd"] + rp["reviewer"]["cost_usd"], 6),
        },
        "outcomes": {
            "false_acceptance": fa["reviewer"]["outcomes"],
            "replay": rp["reviewer"]["outcomes"],
        },
        "trials": {
            "false_acceptance_per_case": fa["trials_per_case"],
            "replay": rp["trials"],
        },
    }


def rank(arms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The agreed rule: fewest wrong acceptances, then fewest false rejects, then latency."""
    return sorted(
        arms,
        key=lambda arm: (
            arm["wrong_accepted"]["count"],
            arm["false_rejects"]["count"],
            arm["latency_ms"]["p50"] if arm["latency_ms"]["p50"] is not None else math.inf,
        ),
    )


def fmt(prop: dict[str, Any]) -> str:
    interval = prop["wilson_95"]
    bounds = f"[{interval[0]:.3f}, {interval[1]:.3f}]" if interval else "N/A"
    rate = f"{prop['rate']:.3f}" if prop["rate"] is not None else "N/A"
    return f"{prop['count']}/{prop['observations']} ({rate}) {bounds}"


def markdown(arms: list[dict[str, Any]], winner: dict[str, Any]) -> str:
    lines = [
        "# Reviewer model decision",
        "",
        "Both arms replayed the same 24 recorded answers (14 correct, 3 wrong with review "
        "payloads; 7 missed excluded) with only `ANALYST_REVIEW_MODEL` changed. Wrong-answer "
        "cases are 21 mutations, 18 of which pass the deterministic gate and reach the "
        "reviewer; controls are the 14 unmutated correct answers. Intervals are Wilson 95%.",
        "",
        "| model | wrong accepted (mutated + recorded) | controls accepted | "
        "false rejects (correct) | true rejects (wrong) | malformed reviews | "
        "p50 / p95 review latency | cost per review |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in arms:
        latency = arm["latency_ms"]
        wrong = arm["wrong_accepted"]
        mutated = wrong["mutated"]
        recorded = wrong["recorded"]
        lines.append(
            f"| {arm['model']} | {fmt(wrong)} "
            f"(mutated {mutated['count']}/{mutated['observations']}; "
            f"recorded {recorded['count']}/{recorded['observations']}) | "
            f"{fmt(arm['controls_accepted'])} | {fmt(arm['false_rejects'])} | "
            f"{fmt(arm['true_rejects'])} | {fmt(arm['malformed_reviews'])} | "
            f"{latency['p50']:.0f} / {latency['p95']:.0f} ms | "
            f"${arm['cost_per_review']:.6f} |"
            if latency["p50"] is not None
            else f"| {arm['model']} | N/A |"
        )
    lines.extend(
        [
            "",
            f"Recommendation by the rule (fewest wrong acceptances, then fewest false "
            f"rejects of correct answers, then latency): **{winner['model']}**.",
            "",
            "Wrong accepted counts every observation of a wrong answer that passed the "
            "pipeline: gate-passing mutations of correct answers plus recorded wrong writer "
            "answers replayed from `head-units.jsonl`. The rule applies to that total because "
            "the replay arm also measures wrong acceptances; the two sub-counts and their "
            "opposing directions are shown in the table. False rejects count trials where a "
            "correct recorded answer was rejected (reviewer, deterministic or structure). "
            "Malformed reviews count provider replies that failed JSON validation across both "
            "arms, including retried first attempts; the denominator is provider calls. "
            "Latency is the provider call from the false-acceptance arm; replay-arm latency "
            "and every call's model, protocol and token cap are in `decision.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_arm(value: str) -> tuple[str, Path, Path]:
    parts = value.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected label:false-acceptance.json:replay.json")
    return parts[0], Path(parts[1]), Path(parts[2])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", action="append", required=True, type=parse_arm)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    arms = [build_arm(*arm) for arm in args.arm]
    winner = rank(arms)[0]
    artifact = {
        "arms": arms,
        "recommended": winner["model"],
        "rule": "wrong acceptances, false rejects, latency",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown(arms, winner) + "\n")
    print(json.dumps({"recommended": winner["model"], "table": markdown(arms, winner)}))


if __name__ == "__main__":
    main()
