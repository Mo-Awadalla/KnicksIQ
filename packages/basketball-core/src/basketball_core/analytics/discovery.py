"""Deterministic notable-fact scoring and deduplication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

DETECTOR_VERSION = "player-intelligence-v1"
WEIGHTS = {
    "magnitude": 0.30,
    "rarity": 0.15,
    "sample_quality": 0.15,
    "recency": 0.10,
    "coverage": 0.10,
    "basketball_relevance": 0.10,
    "novelty": 0.05,
    "interpretability": 0.05,
}


@dataclass(frozen=True)
class FactCandidate:
    fact_type: str
    player_ids: tuple[int, ...]
    stat_keys: tuple[str, ...]
    timeframe: dict[str, Any]
    statement: str
    result: dict[str, Any]
    source_game_ids: tuple[int | str, ...]
    sample_size: int
    components: dict[str, float]
    penalties: dict[str, float] = field(default_factory=dict)


def score_fact_candidate(candidate: FactCandidate) -> tuple[float, dict[str, float]]:
    components = {
        name: max(0.0, min(1.0, float(candidate.components.get(name, 0)))) for name in WEIGHTS
    }
    weighted = {name: round(components[name] * weight, 6) for name, weight in WEIGHTS.items()}
    penalty = sum(max(0.0, float(value)) for value in candidate.penalties.values())
    weighted.update(
        {
            f"penalty_{name}": round(max(0.0, float(value)), 6)
            for name, value in sorted(candidate.penalties.items())
        }
    )
    weighted["penalty"] = round(penalty, 6)
    return round(max(0.0, sum(weighted[name] for name in WEIGHTS) - penalty), 6), weighted


def fact_fingerprint(candidate: FactCandidate, detector_version: str = DETECTOR_VERSION) -> str:
    identity = {
        "detector_version": detector_version,
        "fact_type": candidate.fact_type,
        "player_ids": sorted(candidate.player_ids),
        "stat_keys": sorted(candidate.stat_keys),
        "timeframe": candidate.timeframe,
        "result": candidate.result,
        "source_game_ids": sorted(str(value) for value in candidate.source_game_ids),
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def rank_fact_candidates(candidates: list[FactCandidate], limit: int = 3) -> list[FactCandidate]:
    ranked = sorted(
        candidates, key=lambda item: (-score_fact_candidate(item)[0], fact_fingerprint(item))
    )
    selected: list[FactCandidate] = []
    seen: set[tuple[tuple[int, ...], tuple[str, ...], str]] = set()
    for candidate in ranked:
        key = (
            tuple(sorted(candidate.player_ids)),
            tuple(sorted(candidate.stat_keys)),
            candidate.fact_type,
        )
        if key in seen:
            continue
        selected.append(candidate)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected
