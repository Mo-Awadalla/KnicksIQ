"""Player-name aliases and deterministic mention resolution."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from app.models.player import Player
from app.services.query_text import normalize

CURATED_PLAYER_ALIASES = {
    "jb": "Jalen Brunson",
    "brunson": "Jalen Brunson",
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "og": "OG Anunoby",
    "deuce": "Miles McBride",
    "mitch": "Mitchell Robinson",
}
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
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


def name_parts(full_name: str) -> tuple[list[str], str, str]:
    """Return normalized name parts, the given name and the surname.

    Generational suffixes are not surnames. A one-token hyphenated archive record such as
    "Robinson-Earl" is a compound surname, not a given name "Robinson".
    """
    raw = full_name.strip()
    parts = normalize(raw).split()
    if not parts:
        return [], "", ""
    if " " not in raw and "-" in raw:
        return parts, "", " ".join(parts)
    surname_index = len(parts) - 1
    if len(parts) > 1 and parts[-1] in _NAME_SUFFIXES:
        surname_index -= 1
    return parts, " ".join(parts[:surname_index]), parts[surname_index]


def player_aliases(player: Player, unique_givens: set[str] | None = None) -> set[str]:
    parts, given, surname = name_parts(player.full_name)
    if not parts:
        return set()
    aliases = {normalize(player.full_name), surname}
    if len(parts) > 1:
        aliases.add(f"{parts[0][0]} {surname}")
    if unique_givens and given in unique_givens:
        aliases.add(given)
    aliases.update(
        alias for alias, target in CURATED_PLAYER_ALIASES.items() if target == player.full_name
    )
    return aliases


def unique_given_names(players: list[Player]) -> set[str]:
    """Only first names that identify exactly one release player become aliases."""
    counts: dict[str, int] = defaultdict(int)
    for player in players:
        _, given, _ = name_parts(player.full_name)
        if len(given.replace(" ", "")) >= 3:
            counts[given] += 1
    return {given for given, count in counts.items() if count == 1}


def _name_candidates(question: str) -> list[str]:
    candidates: list[str] = []
    for raw in re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}(?:\s+[A-Za-z][A-Za-z'-]{2,})?\b", question):
        normalized = normalize(raw)
        words = normalized.split()
        if words and not all(word in _NAME_STOPWORDS for word in words):
            candidates.append(normalized)
            if len(words) == 2:
                candidates.extend(word for word in words if word not in _NAME_STOPWORDS)
    return list(dict.fromkeys(candidates))


def _typo_alias_allowed(candidate: str, alias: str) -> bool:
    """A typo corrupts a name, rather than truncating or inflecting it."""
    candidate_key = candidate.replace(" ", "")
    alias_key = alias.replace(" ", "")
    if len(candidate_key) < 4 or not alias_key or candidate[0] != alias[0]:
        return False
    if alias.startswith(candidate):
        return False
    if len(alias.split()) == 2 and len(alias.split()[0]) == 1:
        return False
    return abs(len(candidate_key) - len(alias_key)) <= 2


def _longer_name_typo(
    candidate: str,
    alias: str,
    aliases: dict[str, list[Player]],
    typo_threshold: float,
) -> bool:
    """Do not let an exact first token preempt a near-match compound surname."""
    words = candidate.split()
    if len(words) != 2 or words[0] != alias:
        return False
    for longer_alias in aliases:
        if not longer_alias.startswith(f"{alias} ") or len(longer_alias.split()) != len(words):
            continue
        if (
            _typo_alias_allowed(candidate, longer_alias)
            and SequenceMatcher(None, candidate, longer_alias).ratio() >= typo_threshold
        ):
            return True
    return False


def resolve_player_mentions(
    question: str,
    players: list[Player],
    *,
    typo_threshold: float,
    unique_givens: set[str] | None = None,
    allow_fuzzy: bool = True,
) -> tuple[list[int], list[str]]:
    normalized_question = f" {normalize(question)} "
    name_candidates = _name_candidates(question)
    aliases: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        for alias in player_aliases(player, unique_givens):
            aliases[alias].append(player)

    resolved: dict[int, Player] = {}
    ambiguous: dict[int, Player] = {}
    remaining = normalized_question
    # Full names and curated aliases consume their spans before surname matching. A
    # one-token full name must remain subject to the same ambiguity check as a surname.
    for player in sorted(players, key=lambda item: -len(normalize(item.full_name))):
        full_name = normalize(player.full_name)
        if " " not in full_name:
            continue
        if re.search(rf"\b{re.escape(full_name)}\b", remaining):
            resolved[player.id] = player
            remaining = re.sub(rf"\b{re.escape(full_name)}\b", " ", remaining)
    for alias, target in sorted(CURATED_PLAYER_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            matches = [player for player in players if player.full_name == target]
            resolved.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    for alias in sorted(aliases, key=len, reverse=True):
        if alias in CURATED_PLAYER_ALIASES:
            continue
        if " " not in alias and any(
            _longer_name_typo(candidate, alias, aliases, typo_threshold)
            for candidate in name_candidates
        ):
            continue
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            matches = aliases[alias]
            knicks_matches = [player for player in matches if player.team_id == "NYK"]
            if len(matches) > 1 and len(knicks_matches) == 1:
                matches = knicks_matches
            if len(matches) == 1:
                resolved[matches[0].id] = matches[0]
            else:
                ambiguous.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    exact_resolved = dict(resolved)
    exact_ambiguous = dict(ambiguous)
    if allow_fuzzy and not resolved and not ambiguous:
        for candidate in name_candidates:
            scores: list[tuple[float, Player]] = []
            for player in players:
                given = name_parts(player.full_name)[1]
                best = 0.0
                for alias in player_aliases(player, unique_givens):
                    if alias != given and _typo_alias_allowed(candidate, alias):
                        best = max(best, SequenceMatcher(None, candidate, alias).ratio())
                scores.append((best, player))
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

    # A bare token that names one player's surname and another's given name is ambiguous.
    bare_token = normalized_question.strip()
    if " " not in bare_token:
        given_holders = {
            player.id: player for player in players if name_parts(player.full_name)[1] == bare_token
        }
        holders = {**exact_resolved, **exact_ambiguous, **given_holders}
        if len(holders) > 1:
            ambiguous = holders
            resolved.clear()

    return sorted(resolved), sorted(player.full_name for player in ambiguous.values())
