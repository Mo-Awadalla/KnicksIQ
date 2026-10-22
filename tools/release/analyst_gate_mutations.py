"""Offline mutation check of the deterministic reviewer number gate. No model calls.

The live replay (`analyst_review_replay.py --mutations`) skips a candidate the gate already
accepts, so it measures the model reviewer behind the gate, never the gate's own escapes.
This script keeps every candidate and reports the ones the gate accepts:

- control_answer: the recorded correct answer, unmodified. A false rejection here is a
  regression of the gate itself.
- text_number_swap: a stated number moved by 1, 2, 3, 7 and 13 display units, skipping
  replacements that equal another trusted value.
- percent_of_ratio: a sibling ratio claim (0.10) added per unit, then a sentence stating a
  wrong percentage of it (+1, +5, +40 points) and, as a control, the right percentage.
- coincidence_swap: a number written next to a unit word replaced by another trusted value
  whose metric has a different unit ("15 archived games" becomes "1,652 archived games").
- percent_count: a sentence stating a percentage equal to a trusted count of another unit
  ("That rate was 15%." when 15 is a wins, losses or games count).

The recorded units contain no ratio claims, hence the added one. The tool locates tokens
itself so it runs against both the base gate and a unit-aware head gate.

    uv run --package knicksiq-api python tools/release/analyst_gate_mutations.py \
      --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
      --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
      --out docs/release-evidence/llm-primary-20261021/reviewer/gate-mutations.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyst_review_base import load_models  # noqa: E402
from analyst_review_replay import load_units  # noqa: E402
from app.services.analyst_review_checks import (  # noqa: E402
    number_tokens,
    review_issues,
    trusted_numbers,
)
from app.services.evidence_contracts import Evidence, split_review_spans  # noqa: E402

RATIO = Decimal("0.10")
UNIT_WORDS = {
    "point": "points",
    "points": "points",
    "game": "games",
    "games": "games",
    "win": "wins",
    "wins": "wins",
    "loss": "losses",
    "losses": "losses",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "assist": "assists",
    "assists": "assists",
}
UNIT_BRIDGES = (
    "active",
    "archived",
    "home",
    "playoff",
    "playoffs",
    "regular",
    r"regular\-season",
    "road",
    "season",
    "total",
)
UNIT_AFTER = re.compile(
    r"^\s*(?:-\s*)?(?:(?:" + "|".join(UNIT_BRIDGES) + r")\s+)?([A-Za-z]+)",
    re.IGNORECASE,
)
UNIT_BEFORE = re.compile(r"\b([A-Za-z]+)\s*[:=]\s*$", re.IGNORECASE)
PER = re.compile(r"\bper\s+$", re.IGNORECASE)
WORDS = re.compile(r"[a-z]+")


def gate_accepts(answer, claims, evidence, payload) -> bool:
    spans = split_review_spans(answer.text)
    return not review_issues(
        answer,
        spans,
        claims,
        evidence,
        payload.get("capabilities"),
        payload.get("requested_question", ""),
    )


def family(unit: str | None) -> str | None:
    if not unit:
        return None
    words = WORDS.findall(unit.lower())
    if not words:
        return None
    head = words[0]
    if head in UNIT_WORDS:
        return UNIT_WORDS[head]
    if head in {"margin", "net", "score"}:
        return "points"
    if head in {"appearance", "appearances"}:
        return "games"
    if "margin" in words or "net" in words or "score" in words:
        return "points"
    if "game" in words or "games" in words:
        return "games"
    return None


def compatible(unit: str, source_unit: str | None) -> bool:
    other = family(source_unit)
    if other is None:
        return False
    return other == unit or (unit == "games" and other in {"wins", "losses"})


def spans_with_units(text: str) -> list[tuple[Any, str | None, int, int]]:
    """(token, unit, start, end) for each number token, in text order."""
    located = []
    cursor = 0
    for token in number_tokens(text):
        start = text.find(token.raw, cursor)
        if start < 0:
            start = text.find(token.raw)
        if start < 0:
            continue
        end = start + len(token.raw)
        cursor = end
        located.append((token, unit_at(text, start, end), start, end))
    return located


def unit_at(text: str, start: int, end: int) -> str | None:
    if start and text[start - 1] == "-":
        return None
    after = UNIT_AFTER.match(text[end:])
    if after:
        unit = UNIT_WORDS.get(after.group(1).lower())
        if unit:
            return unit
    before = UNIT_BEFORE.search(text[:start])
    if before:
        unit = UNIT_WORDS.get(before.group(1).lower())
        if unit and not PER.search(text[: before.start(1)]):
            return unit
    return None


def format_value(value: Decimal, decimals: int) -> str:
    exponent = value.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) else 0
    return f"{value:.{max(decimals, places)}f}"


def key_family(key: str) -> str | None:
    words = WORDS.findall(key.lower())
    for word in words:
        if word in UNIT_WORDS:
            return UNIT_WORDS[word]
    if "margin" in words or "net" in words or "score" in words:
        return "points"
    return None


def typed_sources(answer, claims, evidence, payload) -> list[tuple[Decimal, str | None, str, bool]]:
    """(value, unit family, source label, is_percent) for every trusted number."""
    found: list[tuple[Decimal, str | None, str, bool]] = []

    def add(value: Any, unit: str | None, label: str, percent: bool = False) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        number = Decimal(str(value))
        found.append((number, unit, label, percent))

    for claim in claims.values():
        if isinstance(claim.value, (int, float)) and not isinstance(claim.value, bool):
            number = Decimal(str(claim.value))
            add(claim.value, family(claim.unit), "claim")
            if 0 < abs(number) < 1:
                found.append((number * 100, family(claim.unit), "claim:ratio", True))
            if claim.unit and ("percent" in claim.unit.lower() or "pct" in claim.unit.lower()):
                found.append((number, family(claim.unit), "claim:percent", True))
        for text in (claim.statement, claim.population, claim.season, claim.season_type):
            for token, unit, _, _ in spans_with_units(text or ""):
                found.append((token.value, unit, "claim:text", token.percent))
        add(claim.sample_size, "games", "claim:sample")
        add(claim.denominator, "games", "claim:denominator")
    for item in evidence.values():
        if not isinstance(item, Evidence):
            continue
        for token, unit, _, _ in spans_with_units(item.text):
            found.append((token.value, unit, "receipt:text", token.percent))
        for key, value in item.metadata.items():
            if key.endswith(("_id", "_ids")) or key == "release_id":
                continue
            add(value, key_family(key), f"receipt:{key}")
    capabilities = payload.get("capabilities") or {}
    scope = capabilities.get("scope") or {}
    add(scope.get("relative_game_count") if isinstance(scope, dict) else None, "games", "scope")
    add(capabilities.get("games"), "games", "capability")
    add(capabilities.get("box_score_rows"), "games", "capability")
    return found


def swaps(unit_id: str, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    trusted = trusted_numbers(claims, evidence, payload.get("capabilities"))
    rows = []
    for token, _, start, end in spans_with_units(answer.text):
        if token.value < 3:
            continue
        unit = Decimal(1).scaleb(-token.decimals)
        for step in (1, 2, 3, 7, 13):
            replacement = token.value + unit * step
            if any(abs(replacement - value) <= token.tolerance for value in trusted):
                continue
            text = (
                answer.text[:start] + format_value(replacement, token.decimals) + answer.text[end:]
            )
            mutated = answer.model_copy(update={"text": text})
            rows.append(
                {
                    "unit": unit_id,
                    "kind": "text_number_swap",
                    "original": token.raw,
                    "replacement": format_value(replacement, token.decimals),
                    "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
                }
            )
    return rows


def coincidence(unit_id: str, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    found = typed_sources(answer, claims, evidence, payload)
    question_numbers = {
        token.value for token in number_tokens(payload.get("requested_question", ""))
    }
    rows = []
    for token, unit, start, end in spans_with_units(answer.text):
        if token.value < 3 or unit is None:
            continue
        same_unit = [
            value
            for value, source_unit, _, percent in found
            if not percent
            and source_unit is not None
            and compatible(unit, source_unit)
            and abs(value - token.value) <= token.tolerance
        ]
        candidates = {
            value: (label, source_unit)
            for value, source_unit, label, percent in found
            if not percent
            and source_unit is not None
            and value >= 3
            and value not in question_numbers
            and abs(value - token.value) > token.tolerance
            and not compatible(unit, source_unit)
            and not any(abs(value - other) <= token.tolerance for other in same_unit)
        }
        if not candidates:
            continue
        replacement = sorted(
            candidates, key=lambda value: (not candidates[value][0].startswith("claim"),)
        )[0]
        label, source_unit = candidates[replacement]
        text = answer.text[:start] + format_value(replacement, token.decimals) + answer.text[end:]
        mutated = answer.model_copy(update={"text": text})
        rows.append(
            {
                "unit": unit_id,
                "kind": "coincidence_swap",
                "original": token.raw,
                "replacement": format_value(replacement, token.decimals),
                "unit_word": unit,
                "replacement_source": label,
                "replacement_unit": source_unit,
                "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
            }
        )
    return rows


def percents(unit_id: str, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    used = [use.claim_id for use in answer.claims if use.claim_id in claims]
    if not used:
        return []
    # A sibling ratio claim, so the numbers the answer already states stay explained.
    ratio_id = used[0] + ":ratio"
    claims = dict(claims)
    claims[ratio_id] = claims[used[0]].model_copy(
        update={"claim_id": ratio_id, "value": float(RATIO)}
    )
    rows = []
    for label, shown in (
        ("control", RATIO * 100),
        *((f"+{k}", RATIO * 100 + k) for k in (1, 5, 40)),
    ):
        text = f"{answer.text} That rate was {shown:.0f}%."
        mutated = answer.model_copy(update={"text": text})
        rows.append(
            {
                "unit": unit_id,
                "kind": "percent_of_ratio",
                "case": label,
                "ratio": str(RATIO),
                "stated": f"{shown:.0f}%",
                "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
            }
        )
    return rows


def percent_counts(unit_id: str, attempt: dict[str, Any]) -> list[dict[str, Any]]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    found = typed_sources(answer, claims, evidence, payload)
    answered = {token.value for token, _, _, _ in spans_with_units(answer.text)}
    percent_values = {value for value, _, _, percent in found if percent}
    counts: dict[Decimal, int] = {}
    for value, unit, _, percent in found:
        if percent or unit is None or 1 > value or value > 100:
            continue
        if value in percent_values:
            continue
        counts[value] = counts.get(value, 0) + 1
    # A percentage in 1..100 equal to a trusted count. Prefer a value the answer already
    # states, then the count trusted by most sources, then the larger one (the reported
    # escape was 15% against a 15-game window, not 1%).
    candidates = sorted(counts, key=lambda value: (value not in answered, -counts[value], -value))
    if not candidates:
        return []
    value = candidates[0]
    text = f"{answer.text} That rate was {format_value(value, 0)}%."
    mutated = answer.model_copy(update={"text": text})
    return [
        {
            "unit": unit_id,
            "kind": "percent_count",
            "stated": f"{format_value(value, 0)}%",
            "trusted_sources": counts[value],
            "gate_accepts": gate_accepts(mutated, claims, evidence, payload),
        }
    ]


def control(unit_id: str, attempt: dict[str, Any]) -> dict[str, Any]:
    answer, claims, evidence, _ = load_models(attempt)
    payload = attempt.get("payload") or {}
    return {
        "unit": unit_id,
        "kind": "control_answer",
        "gate_accepts": gate_accepts(answer, claims, evidence, payload),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text())
    rows: list[dict[str, Any]] = []
    for unit_id, _, attempt, verdict in load_units([args.records], labels):
        if verdict != "correct":
            continue
        rows.append(control(unit_id, attempt))
        rows += swaps(unit_id, attempt)
        rows += coincidence(unit_id, attempt)
        rows += percents(unit_id, attempt)
        rows += percent_counts(unit_id, attempt)
    wrong = [r for r in rows if r.get("case") != "control" and r["kind"] != "control_answer"]
    controls = [r for r in rows if r["kind"] == "control_answer"]
    ratio_controls = [r for r in rows if r.get("case") == "control"]
    summary = {
        "correct_units": len(controls),
        "correct_units_accepted": sum(r["gate_accepts"] for r in controls),
        "wrong_total": len(wrong),
        "wrong_accepted": sum(r["gate_accepts"] for r in wrong),
        "wrong_accepted_by_kind": {
            kind: sum(r["gate_accepts"] for r in wrong if r["kind"] == kind)
            for kind in (
                "text_number_swap",
                "coincidence_swap",
                "percent_of_ratio",
                "percent_count",
            )
        },
        "percent_ratio_controls": len(ratio_controls),
        "percent_ratio_controls_accepted": sum(r["gate_accepts"] for r in ratio_controls),
    }
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
