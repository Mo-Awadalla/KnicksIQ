"""Player names, query intent, clarification and conversational context."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from app.models.player import Player
from app.services.team_aliases import TEAM_ALIASES as _TEAM_ALIASES
from app.services.team_aliases import team_ids_in_text
from basketball_core.analytics.registry import stat_keys_in_text

_ALIASES = {
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "jb": "Jalen Brunson",
    "og": "OG Anunoby",
    "mikal": "Mikal Bridges",
}


_ANALYTICS_TERMS = (
    "average",
    "game log",
    "per game",
    "last ",
    "compare",
    "split",
    "leader",
    "most ",
    "streak",
    "trend",
    "outlier",
    "notable",
    "surprising",
    "when he",
    "when they",
    "double-double",
    "triple-double",
    "lately",
    "efficient",
    "consistent",
    "better",
    "rank players",
    "who led",
    "which player led",
    "how many",
    "total",
    "appeared",
    "appearances",
    "games played",
    "dnp",
    "available",
    "availability",
    "starts",
    "games started",
)


_DISCOVERY_TERMS = ("notable", "surprising", "interesting", "discover")


_UNSUPPORTED_CONCEPTS = (
    "usage rate",
    "player efficiency rating",
    "defensive rating",
    "offensive rating",
    "on/off",
    "on off",
    "tracking data",
    "matchup minutes",
)


_NAME_SLOT_STOPWORDS = {
    "a",
    "after",
    "all",
    "and",
    "are",
    "as",
    "at",
    "average",
    "before",
    "best",
    "better",
    "compare",
    "did",
    "do",
    "does",
    "during",
    "for",
    "from",
    "game",
    "games",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "in",
    "is",
    "it",
    "knicks",
    "last",
    "led",
    "most",
    "of",
    "on",
    "or",
    "player",
    "players",
    "rank",
    "season",
    "the",
    "their",
    "they",
    "this",
    "to",
    "use",
    "versus",
    "was",
    "what",
    "when",
    "which",
    "who",
    "with",
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _asks_opponent_plus_minus_leader(question: str) -> bool:
    """Recognize opponent impact phrasing as a cumulative plus/minus leaderboard."""
    q = question.lower()
    normalized = _normalize(question)
    natural_impact = (
        "gave the knicks" in normalized
        and any(term in normalized for term in ("hardest time", "toughest time"))
        and any(term in normalized for term in ("on the court", "on court", "on the floor"))
    )
    explicit_plus_minus = bool(
        re.search(r"(?:\+/-|plus[- ]?minus)", q)
        and any(term in normalized for term in ("opponent", "opposing", "against the knicks"))
        and any(term in normalized for term in ("most", "highest", "leader", "which player"))
    )
    return natural_impact or explicit_plus_minus


def _player_aliases(player: Player) -> set[str]:
    name = _normalize(player.full_name)
    parts = name.split()
    aliases = {name, parts[-1]}
    aliases.update(alias for alias, target in _ALIASES.items() if target == player.full_name)
    return aliases


def _name_like_slots(question: str) -> list[str]:
    """Extract only spans that could plausibly be names; never fuzz arbitrary query words."""
    slots: list[str] = []
    for match in re.finditer(r"\b(?:[A-Z][A-Za-z'-]*)(?:\s+[A-Z][A-Za-z'-]*){0,3}\b", question):
        words = _normalize(match.group()).split()
        while words and words[0] in _NAME_SLOT_STOPWORDS:
            words.pop(0)
        normalized_slot = " ".join(words)
        if (
            words
            and not all(word in _NAME_SLOT_STOPWORDS for word in words)
            and normalized_slot not in _TEAM_ALIASES
        ):
            slots.extend(" ".join(words[index:]) for index in range(len(words)))
    for match in re.finditer(r"\b([A-Za-z][A-Za-z'-]{2,})['’]s\b", question):
        value = _normalize(match.group(1))
        if value not in _NAME_SLOT_STOPWORDS:
            slots.append(value)
    return list(dict.fromkeys(slots))


def _has_opponent_context(question: str) -> bool:
    q = _normalize(question)
    return (
        _asks_opponent_plus_minus_leader(question)
        or any(term in f" {q} " for term in (" opponent ", " against ", " opposing "))
        or bool(team_ids_in_text(question) - {"NYK"})
    )


def _asks_availability(question: str) -> bool:
    q = question.lower()
    return bool(
        any(term in q for term in ("availability", "available", "games missed", "dnp"))
        or re.search(r"\bhow many games\b.*\b(?:play|played|appear|appeared|miss|missed)\b", q)
        or re.search(r"\b(?:games played|appearance count|total appearances)\b", q)
    )


def _resolve_players(question: str, players: list[Player]) -> tuple[list[Player], list[Player]]:
    normalized = _normalize(question)
    remaining = f" {normalized} "
    exact: list[Player] = []

    # Full names and curated aliases are authoritative and consume their spans before surnames.
    for player in sorted(players, key=lambda item: -len(_normalize(item.full_name))):
        full_name = _normalize(player.full_name)
        if re.search(rf"\b{re.escape(full_name)}\b", remaining):
            exact.append(player)
            remaining = re.sub(rf"\b{re.escape(full_name)}\b", " ", remaining)
    for alias, target in _ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            matches = [player for player in players if player.full_name == target]
            exact.extend(matches)
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    opponent_context = _has_opponent_context(question)
    surname_groups: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        if player.team_id == "NYK" or opponent_context:
            surname_groups[_normalize(player.full_name).split()[-1]].append(player)
    ambiguous: list[Player] = []
    for surname, matches in surname_groups.items():
        if re.search(rf"\b{re.escape(surname)}\b", remaining):
            if len(matches) == 1:
                exact.extend(matches)
            else:
                ambiguous.extend(matches)

    exact_by_person = {player.nba_player_id: player for player in exact}
    slots = [slot for slot in _name_like_slots(question) if slot not in _NAME_SLOT_STOPWORDS]
    for slot in slots:
        if any(slot in _player_aliases(player) for player in exact_by_person.values()):
            continue
        candidates: list[tuple[float, Player]] = []
        for player in players:
            if player.team_id != "NYK" and not opponent_context:
                continue
            aliases = {_normalize(player.full_name), _normalize(player.full_name).split()[-1]}
            score = max(SequenceMatcher(None, slot, alias).ratio() for alias in aliases)
            if score >= 0.84:
                candidates.append((score, player))
        candidates.sort(key=lambda item: (-item[0], item[1].full_name))
        if not candidates:
            continue
        best_score, best_player = candidates[0]
        runner_up = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score - runner_up >= 0.08:
            exact_by_person[best_player.nba_player_id] = best_player
        else:
            ambiguous.extend(player for score, player in candidates if best_score - score < 0.08)

    ambiguous = list({player.nba_player_id: player for player in ambiguous}.values())
    if ambiguous:
        return list(exact_by_person.values()), ambiguous
    return list(exact_by_person.values()), []


def _asks_starts(question: str) -> bool:
    return bool(
        re.search(
            r"\bhow many games\b.*\bstart(?:ed)?\b|\b(?:total |game )?starts\b", question.lower()
        )
    )


def _asks_player_summary(question: str) -> bool:
    q = question.lower()
    return bool(
        re.search(r"\btell me about\b|\bhow did\b.*\b(?:play|look)\b", q)
        or re.search(r"\b(?:did|does)\b.*\bplay(?:ed)? well\b", q)
        or re.search(r"\bwhat did\b.*\bdo\b", q)
    )


def _game_selector(question: str) -> str | None:
    if re.search(r"\b(?:biggest|largest) win\b", question.lower()):
        return "largest_win_margin"
    return None


def _is_player_intelligence(question: str, resolved: list[Player]) -> bool:
    q = question.lower()
    if (
        resolved
        and _asks_player_summary(q)
        and (_has_opponent_context(question) or _game_selector(q))
    ):
        return True
    if any(term in q for term in ("who beat the knicks", "beat the knicks by", "knicks loss")):
        return False
    if _asks_opponent_plus_minus_leader(question):
        return True
    canonical_stats = bool(stat_keys_in_text(question)) or any(
        term in q for term in ("scoring", "shooting", "stat line")
    )
    operation = any(term in q for term in _ANALYTICS_TERMS) or any(
        term in q
        for term in (
            "rank players",
            "which player",
            "who led",
            "how has",
            "record when",
            "correlat",
            "cause",
        )
    )
    availability = _asks_availability(question)
    discovery = any(term in q for term in _DISCOVERY_TERMS)
    ranking = any(
        term in q for term in ("rank players", "who led", "which player led", "most ", "top ")
    )
    if any(term in q for term in ("lineup", "possession", "clutch", "defense", "dominated")):
        return bool(resolved) and canonical_stats and operation
    unresolved_name_slot = (
        bool(_name_like_slots(question))
        and canonical_stats
        and bool(
            "player" in q
            or re.search(
                r"\b(?:did|does|has|have|compare)\s+[A-Z][A-Za-z'-]+",
                question,
            )
            or re.search(r"\b[A-Za-z][A-Za-z'-]+['’]s\b", question)
        )
    )
    explicit_operation = operation and any(
        term in q
        for term in (
            "average",
            "compare",
            "split",
            "leader",
            "most ",
            "streak",
            "trend",
            "outlier",
            "notable",
            "surprising",
            "how many",
            "total",
            "rank",
            "per game",
            "lately",
            "better",
        )
    )
    return (
        (
            bool(resolved)
            and (
                canonical_stats
                or explicit_operation
                or availability
                or any(concept in q for concept in _UNSUPPORTED_CONCEPTS)
            )
        )
        or ((ranking or discovery) and (canonical_stats or "player" in q or discovery))
        or unresolved_name_slot
    )


def _clarification(kind: str, players: list[Player] | None = None) -> dict[str, Any]:
    choices: list[dict[str, str]]
    prompts = {
        "player": "Which player did you mean?",
        "lately": "What should ‘lately’ mean for this question?",
        "efficient": "Which efficiency definition should I use?",
        "consistent": "How should I define consistency?",
        "better": "Which measure should decide who was better?",
    }
    if kind == "player":
        choices = [
            {"id": f"player-{item.nba_player_id}", "label": item.full_name, "value": item.full_name}
            for item in players or []
        ]
    elif kind == "lately":
        choices = [
            {"id": "last-5", "label": "Last 5 appearances", "value": "Use last 5 appearances"},
            {"id": "last-10", "label": "Last 10 appearances", "value": "Use last 10 appearances"},
        ]
    elif kind == "efficient":
        choices = [
            {
                "id": "true-shooting",
                "label": "True shooting",
                "value": "Use true shooting percentage",
            },
            {
                "id": "effective-fg",
                "label": "Effective FG%",
                "value": "Use effective field goal percentage",
            },
            {"id": "field-goal", "label": "Field goal %", "value": "Use field goal percentage"},
        ]
    elif kind == "consistent":
        choices = [
            {
                "id": "scoring-variance",
                "label": "Scoring variance",
                "value": "Use scoring standard deviation",
            },
            {"id": "scoring-floor", "label": "Scoring floor", "value": "Use lowest scoring game"},
        ]
    else:
        choices = [
            {"id": "points", "label": "Scoring", "value": "Use points"},
            {"id": "true-shooting", "label": "Efficiency", "value": "Use true shooting percentage"},
            {
                "id": "all-around",
                "label": "All-around line",
                "value": "Use points rebounds and assists",
            },
        ]
    return {"prompt": prompts[kind], "choices": choices}


def _ambiguity(question: str, context_text: str) -> str | None:
    q = question.lower()
    full = context_text.lower()
    if "lately" in q and not re.search(r"last\s+(?:5|10)\s+appearances", full):
        return "lately"
    if "efficient" in q and not any(
        term in full for term in ("true shooting", "effective field goal", "field goal percentage")
    ):
        return "efficient"
    if "consistent" in q and not any(
        term in full for term in ("standard deviation", "lowest scoring")
    ):
        return "consistent"
    if (
        re.search(r"\bbetter\b", q)
        and not stat_keys_in_text(full)
        and not any(term in full for term in ("scoring", "rebounding", "shooting"))
    ):
        return "better"
    return None


def _is_clarification_selection(value: str, context: list[dict[str, str]]) -> bool:
    normalized = value.strip().lower()
    if normalized.startswith("use "):
        return True
    assistant_prompt = " ".join(
        item.get("content", "").lower() for item in context if item.get("role") == "assistant"
    )
    return len(value.split()) <= 4 and any(
        prompt in assistant_prompt
        for prompt in ("which player", "what should", "which efficiency", "how should")
    )


def _fold_question(question: str, context: list[dict[str, str]]) -> tuple[str, str]:
    """Fold four messages while keeping clarifications and excluding unrelated questions."""
    prior_users = [
        item.get("content", "").strip()
        for item in context
        if item.get("role") == "user" and item.get("content", "").strip()
    ]
    if not prior_users:
        return question, question
    if _is_clarification_selection(question, context):
        base = next(
            (value for value in prior_users if not _is_clarification_selection(value, context)),
            prior_users[0],
        )
        selections = [value for value in prior_users if value != base]
        return "\n".join([base, *selections, question]), base
    elliptical = bool(
        re.search(r"\b(?:he|him|his|she|her|they|them|their)\b", question.lower())
        or re.match(r"\s*(?:what about|and|how about)\b", question.lower())
    )
    if elliptical:
        base = next(
            (
                value
                for value in reversed(prior_users)
                if not _is_clarification_selection(value, context)
            ),
            prior_users[-1],
        )
        return "\n".join([base, question]), question
    return question, question
