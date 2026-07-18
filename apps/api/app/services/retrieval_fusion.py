"""Deterministic weighted fusion, deduplication, and result diversity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FusionComponent:
    source: str
    rank: int
    weight: float
    contribution: float


@dataclass(frozen=True)
class FusionResult:
    key: str
    score: float
    components: tuple[FusionComponent, ...]


def weighted_reciprocal_rank_fusion(
    rankings: list[tuple[str, list[str], float]],
    *,
    k: int = 60,
    limit: int | None = None,
) -> list[FusionResult]:
    """Fuse rankings while capping repeated variants to one contribution per source."""
    best_by_source: dict[tuple[str, str], FusionComponent] = {}
    for source, ranking, weight in rankings:
        for rank, item_id in enumerate(dict.fromkeys(ranking), start=1):
            component = FusionComponent(
                source=source,
                rank=rank,
                weight=weight,
                contribution=weight / (k + rank),
            )
            source_key = (item_id, source)
            existing = best_by_source.get(source_key)
            if existing is None or component.contribution > existing.contribution:
                best_by_source[source_key] = component

    components_by_item: dict[str, list[FusionComponent]] = {}
    for (item_id, _source), component in best_by_source.items():
        components_by_item.setdefault(item_id, []).append(component)
    results = [
        FusionResult(
            key=item_id,
            score=sum(component.contribution for component in components),
            components=tuple(sorted(components, key=lambda item: (item.source, item.rank))),
        )
        for item_id, components in components_by_item.items()
    ]
    results.sort(key=lambda item: (-item.score, item.key))
    return results[:limit] if limit is not None else results


def diversify_by_game(
    ranked: list[Any],
    *,
    limit: int,
    max_per_game: int | None,
    game_id_getter: Any,
) -> list[Any]:
    """Preserve rank order while enforcing a configurable per-game cap."""
    if max_per_game is None:
        return ranked[:limit]
    counts: dict[Any, int] = {}
    selected: list[Any] = []
    for item in ranked:
        game_id = game_id_getter(item)
        if game_id is not None and counts.get(game_id, 0) >= max_per_game:
            continue
        selected.append(item)
        if game_id is not None:
            counts[game_id] = counts.get(game_id, 0) + 1
        if len(selected) == limit:
            break
    return selected
