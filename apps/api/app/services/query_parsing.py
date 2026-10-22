"""Canonical parsing for player mentions, dates, periods, and metric names."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from typing import Literal

from app.models.game import Game
from app.models.player import Player

_CURATED_PLAYER_ALIASES = {
    "jb": "Jalen Brunson",
    "brunson": "Jalen Brunson",
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "og": "OG Anunoby",
}
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_METRICS = {
    "point": "points",
    "points": "points",
    "scoring": "points",
    "scorer": "points",
    "scorers": "points",
    "rebound": "rebounds",
    "rebounds": "rebounds",
    "rebounding": "rebounds",
    "assist": "assists",
    "assists": "assists",
    "assisting": "assists",
    "double double": "double_doubles",
    "double doubles": "double_doubles",
    "steal": "steals",
    "steals": "steals",
    "block": "blocks",
    "blocks": "blocks",
    "turnover": "turnovers",
    "turnovers": "turnovers",
    "plus minus": "plus_minus",
    "three": "three_pointers_made",
    "threes": "three_pointers_made",
    "three point percentage": "three_point_percentage",
}
_METRIC_PHRASE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in sorted(_METRICS, key=len, reverse=True)) + r")\b"
)
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


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def _calendar_year(month: int, games: list[Game]) -> int | None:
    years = {game.game_date.year for game in games if game.game_date.month == month}
    if not years:
        seasons = {game.season for game in games}
        if len(seasons) == 1:
            season = re.fullmatch(r"(20\d{2})-(\d{2})", next(iter(seasons)))
            if season and (int(season[1]) + 1) % 100 == int(season[2]):
                years.add(int(season[1]) + (month < 7))
    return next(iter(years)) if len(years) == 1 else None


def _explicit_dates(question: str, games: list[Game]) -> tuple[list[date], str | None]:
    """Parse dates, resolving omitted years only from the active archive calendar."""
    matches: list[tuple[int, tuple[int, int, int]]] = []
    for match in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", question):
        year, month, day = match.groups()
        matches.append((match.start(), (int(year), int(month), int(day))))
    months = "|".join(_MONTHS)
    for match in re.finditer(
        rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d{{2}})\b)?",
        question.lower(),
    ):
        month, day, year = match.groups()
        if year is None:
            resolved_year = _calendar_year(_MONTHS[month], games)
            if resolved_year is None:
                return [], "missing_date_year"
            year = str(resolved_year)
        matches.append((match.start(), (int(year), _MONTHS[month], int(day))))
    for match in re.finditer(r"\bchristmas\s+day(?:,?\s+(20\d{2}))?\b", question, re.I):
        year = int(match[1]) if match[1] else _calendar_year(12, games)
        if year is None:
            return [], "missing_date_year"
        matches.append((match.start(), (year, 12, 25)))
    try:
        return [date(*parts) for _, parts in sorted(matches)], None
    except ValueError:
        return [], "invalid_date"


def _player_aliases(player: Player) -> set[str]:
    normalized = _normalize(player.full_name)
    parts = normalized.split()
    aliases = {normalized, parts[-1]}
    if len(parts) > 1:
        aliases.add(f"{parts[0][0]} {parts[-1]}")
    aliases.update(
        alias for alias, target in _CURATED_PLAYER_ALIASES.items() if target == player.full_name
    )
    return aliases


def _name_candidates(question: str) -> list[str]:
    candidates: list[str] = []
    for raw in re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}(?:\s+[A-Za-z][A-Za-z'-]{2,})?\b", question):
        normalized = _normalize(raw)
        words = normalized.split()
        if words and not all(word in _NAME_STOPWORDS for word in words):
            candidates.append(normalized)
            if len(words) == 2:
                candidates.extend(word for word in words if word not in _NAME_STOPWORDS)
    return list(dict.fromkeys(candidates))


def _resolve_player_mentions(
    question: str,
    players: list[Player],
    *,
    typo_threshold: float,
    allow_fuzzy: bool = True,
) -> tuple[list[int], list[str]]:
    normalized_question = f" {_normalize(question)} "
    aliases: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        for alias in _player_aliases(player):
            aliases[alias].append(player)

    resolved: dict[int, Player] = {}
    ambiguous: dict[int, Player] = {}
    remaining = normalized_question
    for player in sorted(players, key=lambda item: -len(_normalize(item.full_name))):
        full_name = _normalize(player.full_name)
        if full_name not in remaining:
            continue
        if re.search(rf"\b{re.escape(full_name)}\b", remaining):
            resolved[player.id] = player
            remaining = re.sub(rf"\b{re.escape(full_name)}\b", " ", remaining)
    for alias, target in sorted(_CURATED_PLAYER_ALIASES.items(), key=lambda item: -len(item[0])):
        if alias not in remaining:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            matches = [player for player in players if player.full_name == target]
            resolved.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    for alias in sorted(aliases, key=len, reverse=True):
        if alias in _CURATED_PLAYER_ALIASES:
            continue
        if alias not in remaining:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", remaining):
            curated_target = _CURATED_PLAYER_ALIASES.get(alias)
            matches = (
                [player for player in aliases[alias] if player.full_name == curated_target]
                if curated_target
                else aliases[alias]
            )
            knicks_matches = [player for player in matches if player.team_id == "NYK"]
            if len(matches) > 1 and len(knicks_matches) == 1:
                matches = knicks_matches
            if len(matches) == 1:
                resolved[matches[0].id] = matches[0]
            else:
                ambiguous.update({player.id: player for player in matches})
            remaining = re.sub(rf"\b{re.escape(alias)}\b", " ", remaining)

    first_names: dict[str, list[Player]] = defaultdict(list)
    for player in players:
        if player.team_id == "NYK":
            first_names[_normalize(player.full_name).split()[0]].append(player)
    for first_name, matches in first_names.items():
        if (
            len(matches) == 1
            and first_name in remaining
            and re.search(rf"\b{re.escape(first_name)}\b", remaining)
        ):
            resolved[matches[0].id] = matches[0]
            remaining = re.sub(rf"\b{re.escape(first_name)}\b", " ", remaining)

    if allow_fuzzy and not resolved and not ambiguous:
        for candidate in _name_candidates(question):
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


def _periods(question: str) -> list[int]:
    q = _normalize(question)
    values = {int(value) for value in re.findall(r"\bq([1-9])\b", q)}
    values.update(int(value) for value in re.findall(r"\b([1-9])(?:st|nd|rd|th) quarter\b", q))
    for period, ordinal in enumerate(("first", "second", "third", "fourth"), start=1):
        if re.search(rf"\b{ordinal} quarter\b", q):
            values.add(period)
    if "first half" in q:
        values.update({1, 2})
    if "second half" in q:
        values.update({3, 4})
    if "late fourth" in q or "late 4th" in q:
        values.add(4)
    return sorted(values)


def requested_metrics(question: str) -> set[str]:
    q = _normalize(question)
    if re.search(r"\b(?:games?|times)\b.*\bstart(?:ed)?\b", q):
        return {"starts"}
    return {_METRICS[match[0]] for match in _METRIC_PHRASE.finditer(q)}


def requested_aggregations(question: str) -> set[Literal["average", "total"]]:
    values: set[Literal["average", "total"]] = set()
    if re.search(
        r"\b(?:average|averaged|averaging|avg|per[ -](?:game|appearance)|ppg)\b", question, re.I
    ):
        values.add("average")
    if re.search(r"\b(?:total|sum)\b", question, re.I):
        values.add("total")
    return values


def _metric(question: str) -> str | None:
    metrics = requested_metrics(question)
    return next(iter(metrics)) if len(metrics) == 1 else None


def is_record_request(question: str) -> bool:
    """Detect outcome checks that must retain both wins and losses."""
    q = _normalize(question.replace("–", "-").replace("—", "-"))
    if re.search(r"\b(?:only|in)\s+(?:(?:home|road|away)\s+)?(?:wins?|loss(?:es)?)\b", q):
        return False
    all_games_outcome = bool(
        re.search(r"\b(?:all|each)\s+(?:of\s+)?(?:those|these|the)\s+games\b", q)
        and re.search(r"\b(?:win|wins|won|lose|loses|lost|losses)\b", q)
    )
    return bool(
        re.search(r"\brecord\b", q)
        or all_games_outcome
        or (re.search(r"\bwins?\b", q) and re.search(r"\bloss(?:es)?\b", q))
        or (
            re.search(r"^how (?:did|have|has)\b.*\b(?:perform|do|done|fare)\b", q)
            and not requested_metrics(question)
            and not re.search(r"\b(?:scores?|margin|rating|run)\b", q)
        )
    )


def is_game_score_request(question: str) -> bool:
    """Detect a single game's score, not per-game player rates."""
    q = _normalize(question)
    return bool(
        not re.search(r"\bper\s+game\b", q)
        and re.search(r"\b(?:the|final) score\b|\bscore (?:against|on|of)\b", q)
    )


def is_live_only_score_request(question: str) -> bool:
    """A current score request with no separate archived target to answer."""
    q = _normalize(question)
    if not re.search(r"\bscore\b", q) or not re.search(
        r"\b(?:live|current|tonight|today|now)\b", q
    ):
        return False
    archival_target = re.search(
        r"\b(?:archive|historical|previous|last season|average|rebounds|assists)\b",
        q,
    ) or re.search(r"\b20\d{2} \d{2} \d{2}\b", q)
    dated_target = re.search(
        rf"\b(?:{'|'.join(_MONTHS)})\s+\d{{1,2}}(?:st|nd|rd|th)?\b",
        question.lower(),
    )
    return not (archival_target or dated_target)
