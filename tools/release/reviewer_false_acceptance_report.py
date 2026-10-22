"""Summaries and the Markdown report for reviewer_false_acceptance.py."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from reviewer_false_acceptance_cases import CLASS_RANK


def wilson(successes: int, observations: int, z: float = 1.96) -> list[float] | None:
    if observations == 0:
        return None
    p = successes / observations
    denominator = 1 + z * z / observations
    centre = (p + z * z / (2 * observations)) / denominator
    half = z * math.sqrt(p * (1 - p) / observations + z * z / (4 * observations**2)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def summarize_group(rows: list[dict[str, Any]], trials: int) -> dict[str, Any]:
    observations = [obs for row in rows for obs in row["observations"]]
    accepted = sum(1 for obs in observations if obs["accepted"])
    calls = [call for obs in observations for call in obs["calls"]]
    cost = sum(call.get("cost_usd") or 0 for call in calls)
    return {
        "cases": len(rows),
        "gate_rejected": sum(1 for row in rows if row.get("gate_issues")),
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
        providers = ", ".join(f"{key}:{value}" for key, value in row["providers"].items())
        if not row["observations"]:
            # Every case of this class is rejected by the gate before the reviewer.
            lines.append(
                f"| {name} | {row['cases']} | 0 | N/A | N/A (gate-blocked) | N/A | "
                f"{row['cost_usd']:.4f} | {providers or 'none'} |"
            )
            continue
        low, high = row["wilson_95"]
        lines.append(
            f"| {name} | {row['cases']} | {row['observations']} | {row['accepted']} | "
            f"{row['accept_rate']:.3f} | [{low:.3f}, {high:.3f}] | "
            f"{row['cost_usd']:.4f} | {providers} |"
        )
    if controls["observations"]:
        low, high = controls["wilson_95"]
        control_line = (
            f"Controls (unmutated correct answers): {controls['accepted']}/"
            f"{controls['observations']} accepted, rate {controls['accept_rate']:.3f}, "
            f"Wilson [{low:.3f}, {high:.3f}], cost ${controls['cost_usd']:.4f}."
        )
    else:
        control_line = "Controls: no observations."
    mutations = artifact["mutations_summary"]
    lines.extend(
        [
            "",
            control_line,
            "",
            f"Deterministic gate: {mutations['gate_rejected']} of {mutations['cases']} "
            "wrong-answer cases were rejected before the reviewer and are excluded from the "
            f"rates; {controls['gate_rejected']} of {controls['cases']} controls were rejected. "
            f"Reviewer output cap: {artifact['reviewer_max_tokens']} tokens.",
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
