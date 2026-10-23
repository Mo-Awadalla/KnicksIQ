"""Analytics response contracts, narrative rendering and evidence validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.player_intelligence.tables import (
    _display,
)
from basketball_core.analytics import (
    STAT_REGISTRY,
    AnalyticsPlan,
)


@dataclass(frozen=True)
class AnalyticsAnswer:
    answer: str
    analytics: dict[str, Any]
    citations: list[dict[str, Any]]
    warnings: list[str]


def _aggregation_label(stat: str, mode: str) -> str:
    definition = STAT_REGISTRY[stat]
    if definition.kind in {"percentage", "ratio"} or stat.endswith("_percentage"):
        return ""
    return "total" if mode == "total" else "per appearance"


def _answer_text(result: dict[str, Any]) -> str:
    result_type = result["type"]
    if result_type == "aggregate":
        if result.get("availability"):
            return (
                f"{result['title']}: {result['appearances']} appearances across "
                f"{result['requested_team_games']} requested Knicks games."
            )
        mode = result.get("aggregation_mode", "average")
        if mode == "both":
            averages = ", ".join(
                (
                    f"{STAT_REGISTRY[key].label.lower()} {value} "
                    f"{_aggregation_label(key, 'average')}"
                ).strip()
                for key, value in result["per_appearance_display_values"].items()
            )
            totals = ", ".join(
                (
                    f"{STAT_REGISTRY[key].label.lower()} {value} {_aggregation_label(key, 'total')}"
                ).strip()
                for key, value in result["total_display_values"].items()
            )
            return (
                f"{result['title']}: {averages}; {totals} across "
                f"{result['sample_size']} appearances."
            )
        values = ", ".join(
            f"{STAT_REGISTRY[key].label.lower()} {value} {_aggregation_label(key, mode)}".strip()
            for key, value in result["display_values"].items()
        )
        return f"{result['title']}: {values} across {result['sample_size']} appearances."
    if result_type == "game_log":
        return f"Found {len(result['entries'])} appearances in {result['timeframe']['label']}."
    if result_type in {"player_comparison", "period_comparison", "split"}:
        groups = "; ".join(
            f"{group['label']}: "
            + ", ".join(group["display_values"].values())
            + f" ({group['sample_size']} appearances)"
            for group in result["groups"]
        )
        return f"{result['title']}. {groups}."
    if result_type == "leaderboard":
        if not result["entries"]:
            return "No eligible player leaderboard could be calculated for that window."
        leader = result["entries"][0]
        stat = result["stat"]
        mode = result.get("aggregation_mode", "average")
        if (
            result["stat"] == "plus_minus"
            and mode == "total"
            and result.get("player_scope") == "opponents"
        ):
            value = float(leader["raw_values"][stat] or 0)
            return (
                f"{leader['player_name']} gave the Knicks the hardest time on court, "
                f"with a cumulative plus-minus of {value:+.1f} across "
                f"{leader['sample_size']} appearances."
            )
        label = _aggregation_label(stat, mode)
        value_label = f"{leader['display_values'][stat]} {label}".strip()
        return (
            f"{leader['player_name']} led at {value_label} "
            f"across {leader['sample_size']} appearances."
        )
    if result_type == "streak":
        return f"The longest qualifying streak was {result['length']} appearances."
    if result_type == "trend":
        label = "material" if result["meaningful"] else "not large enough to call meaningful"
        return (
            "The recent-versus-prior change was "
            f"{_display(result['stat'], result['delta'])}; it is {label} under the v1 threshold."
        )
    if result_type == "outlier":
        return (
            f"Found {len(result['entries'])} robust outlier candidates from "
            f"{result['sample_size']} appearances."
        )
    if result_type == "outcome_association":
        record = result["qualifying"]
        return (
            f"When the threshold was met, the team went {record['wins']}-{record['losses']}. "
            "This is association, not causation."
        )
    facts = result.get("facts", [])
    return (
        facts[0]["statement"]
        if facts
        else "No material, nonredundant notable facts passed the v1 thresholds."
    )


def _canonical_evidence(analytics: dict[str, Any]) -> tuple[set[str], set[str]]:
    numbers: set[str] = set()
    strings: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                strings.add(str(key).lower())
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, (int, float)):
            raw = float(value)
            numbers.add(str(value))
            if raw.is_integer():
                numbers.add(str(int(raw)))
            numbers.add(f"{raw:.1f}")
            numbers.add(f"{raw:.2f}")
        else:
            string = str(value)
            strings.add(string.lower())
            numbers.update(re.findall(r"\b\d+(?:\.\d+)?\b", string))

    visit(analytics.get("results", []))
    visit(analytics.get("plan"))
    visit(analytics.get("coverage"))
    return numbers, strings


def validate_analytics_evidence(answer: str, analytics: dict[str, Any]) -> bool:
    """Validate claims against raw/display values, result metadata, and derived labels."""
    result_numbers, structured_strings = _canonical_evidence(analytics)
    answer_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", answer))
    if not answer_numbers.issubset(result_numbers):
        return False
    structured = " ".join(structured_strings)
    ignored = {"short answer", "this is", "no eligible", "all star"}
    entities = {
        match.group(0).lower() for match in re.finditer(r"\b[A-Z][a-z'-]+ [A-Z][a-z'-]+\b", answer)
    } - ignored
    return all(entity in structured for entity in entities)


def _consumer_plan(plan: AnalyticsPlan) -> dict[str, Any]:
    return {
        "players": [player.model_dump(mode="json") for player in plan.resolved_players],
        "timeframe": plan.timeframe.model_dump(mode="json"),
        "filters": plan.filters,
        "stats": plan.stats,
        "operations": [operation.value for operation in plan.operations],
        "output_type": plan.output_type.value,
        "aggregation_mode": plan.aggregation_mode,
        "retrieval_required": plan.retrieval_required,
    }


def _limited_answer(
    question: str, message: str, *, plan: AnalyticsPlan | None = None
) -> AnalyticsAnswer:
    analytics = {
        "status": "limited",
        "resolved_question": question,
        "plan": _consumer_plan(plan) if plan else None,
        "clarification": None,
        "results": [],
        "coverage": None,
    }
    return AnalyticsAnswer(
        answer=f"Short answer\n{message}", analytics=analytics, citations=[], warnings=[message]
    )
