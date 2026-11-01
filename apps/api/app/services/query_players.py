"""Deterministic player identity resolution from the question text alone.

Curated aliases and full names are authoritative and consume their spans before any
ambiguous surname or fuzzy match, so a shared surname never silently picks a player.
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from app.models.player import Player
from app.services.query_operations import normalize_text

_CURATED_PLAYER_ALIASES = {
    "jb": "Jalen Brunson",
    "brunson": "Jalen Brunson",
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "og": "OG Anunoby",
}
_NAME_STOPWORDS = {
    "against",
    "average",
    "before",
    "compare",
    "game",
    "games",
    "home",
    "knicks",
    "last",
    "losses",
    "month",
    "points",
    "previous",
    "road",
    "season",
    "since",
    "the",
    "this",
    "wins",
}


def _player_aliases(player: Player) -> set[str]:
    normalized = normalize_text(player.full_name)
    parts = normalized.split()
    aliases = {normalized, parts[-1]}
    if len(parts) > 1:
        aliases.add(f"{parts[0][0]} {parts[-1]}")
    aliases.update(
        alias for alias, target in _CURATED_PLAYER_ALIASES.items() if target == player.full_name
    )
    return aliases


def name_candidates(question: str) -> list[str]:
    candidates: list[str] = []
    for raw in re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}(?:\s+[A-Za-z][A-Za-z'-]{2,})?\b", question):
        normalized = normalize_text(raw)
        words = normalized.split()
        if words and not all(word in _NAME_STOPWORDS for word in words):
            candidates.append(normalized)
            if len(words) == 2:
                candidates.extend(word for word in words if word not in _NAME_STOPWORDS)
    return list(dict.fromkeys(candidates))


def resolve_player_mentions(
    question: str,
    players: list[Player],
    *,
    typo_threshold: float,
    allow_fuzzy: bool = True,
) -> tuple[list[int], list[str]]:
    normalized_question = f" {normalize_text(question)} "
    aliases: dict[str, list[Player]] = defaultdict(list)
    first_names: set[str] = set()
    for player in players:
        first_name = normalize_text(player.full_name).split()[0]
        exact_aliases = _player_aliases(player)
        if len(first_name) > 1:
            first_names.add(first_name)
            exact_aliases.add(first_name)
        for alias in exact_aliases:
            aliases[alias].append(player)

    resolved: dict[int, Player] = {}
    ambiguous: dict[int, Player] = {}
    remaining = normalized_question
    # Full names and curated aliases are authoritative and consume their spans
    # before ambiguous surname matching.
    for player in sorted(players, key=lambda item: -len(normalize_text(item.full_name))):
        full_name = normalize_text(player.full_name)
        if re.search(rf"\b{re.escape(full_name)}\b", remaining):
            resolved[player.id] = player
            remaining = re.sub(rf"\b{re.escape(full_name)}\b", " ", remaining)
    for alias, target in sorted(
        _CURATED_PLAYER_ALIASES.items(),
        key=lambda item: -len(item[0]),
    ):
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            matches = [player for player in players if player.full_name == target]
            resolved.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    for alias in sorted(aliases, key=len, reverse=True):
        if alias in _CURATED_PLAYER_ALIASES:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            curated_target = _CURATED_PLAYER_ALIASES.get(alias)
            matches = (
                [player for player in aliases[alias] if player.full_name == curated_target]
                if curated_target
                else aliases[alias]
            )
            knicks_matches = [player for player in matches if player.team_id == "NYK"]
            if len(matches) > 1 and len(knicks_matches) == 1 and alias not in first_names:
                matches = knicks_matches
            if len(matches) == 1:
                resolved[matches[0].id] = matches[0]
            else:
                ambiguous.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    if allow_fuzzy and not resolved and not ambiguous:
        for candidate in name_candidates(question):
            scores = [
                (
                    max(
                        SequenceMatcher(None, candidate, alias).ratio()
                        for alias in _player_aliases(player)
                    ),
                    player,
                )
                for player in players
            ]
            scores.sort(key=lambda item: (-item[0], item[1].id))
            if not scores or scores[0][0] < typo_threshold:
                continue
            best_score = scores[0][0]
            close = [player for score, player in scores if best_score - score < 0.06]
            if len(close) == 1:
                resolved[close[0].id] = close[0]
            else:
                ambiguous.update({player.id: player for player in close})
            break
    return sorted(resolved), sorted(player.full_name for player in ambiguous.values())
