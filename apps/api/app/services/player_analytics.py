"""Release-scoped, deterministic player intelligence orchestration."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Literal

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.generated_stat_fact import GeneratedStatFact
from app.models.player import Player
from app.services.analytics_planner import maybe_refine_analytics_plan
from basketball_core.analytics import (
    STAT_REGISTRY,
    AnalyticsOperation,
    AnalyticsPlan,
    FactCandidate,
    OutputType,
    ResolvedPlayer,
    Timeframe,
    aggregate_rows,
    fact_fingerprint,
    linear_slope,
    rank_fact_candidates,
    robust_outlier_scores,
    rolling_mean,
    score_fact_candidate,
)
from basketball_core.analytics.registry import stat_keys_in_text
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_STAT_COLUMNS = (
    "minutes",
    "points",
    "field_goals_made",
    "field_goals_attempted",
    "three_pointers_made",
    "three_pointers_attempted",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "personal_fouls",
    "plus_minus",
)
_ALIASES = {
    "kat": "Karl-Anthony Towns",
    "karl towns": "Karl-Anthony Towns",
    "jb": "Jalen Brunson",
    "og": "OG Anunoby",
}
_TEAM_ALIASES = {
    "76ers": "PHI",
    "bucks": "MIL",
    "cavaliers": "CLE",
    "cavs": "CLE",
    "cleveland": "CLE",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "heat": "MIA",
    "houston": "HOU",
    "indiana": "IND",
    "jazz": "UTA",
    "kings": "SAC",
    "lakers": "LAL",
    "magic": "ORL",
    "memphis": "MEM",
    "miami": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "nuggets": "DEN",
    "oklahoma city": "OKC",
    "orlando": "ORL",
    "pacers": "IND",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "pistons": "DET",
    "portland": "POR",
    "sacramento": "SAC",
    "san antonio": "SAS",
    "sixers": "PHI",
    "spurs": "SAS",
    "suns": "PHX",
    "thunder": "OKC",
    "timberwolves": "MIN",
    "trail blazers": "POR",
    "utah": "UTA",
    "washington": "WAS",
    "wizards": "WAS",
    "boston": "BOS",
    "celtics": "BOS",
    "toronto": "TOR",
    "raptors": "TOR",
    "atlanta": "ATL",
    "hawks": "ATL",
    "chicago": "CHI",
    "bulls": "CHI",
    "charlotte": "CHA",
    "hornets": "CHA",
    "brooklyn": "BKN",
    "nets": "BKN",
    "clippers": "LAC",
    "golden state": "GSW",
    "warriors": "GSW",
    "new orleans": "NOP",
    "pelicans": "NOP",
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
_WORD_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_MONTHS = {
    "october": 10,
    "november": 11,
    "december": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
}
_ALL_MONTH_NAMES = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}


@dataclass(frozen=True)
class AnalyticsAnswer:
    answer: str
    analytics: dict[str, Any]
    citations: list[dict[str, Any]]
    warnings: list[str]


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


async def _release_id(db: AsyncSession) -> int | None:
    active = (
        await db.execute(
            select(DatasetRelease.id)
            .where(
                DatasetRelease.status == "active",
                DatasetRelease.validation_passed.is_(True),
            )
            .order_by(DatasetRelease.activated_at.desc(), DatasetRelease.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None or not getattr(get_settings(), "test_mode", False):
        return active
    return (await db.execute(select(func.max(PlayerGameStat.release_id)))).scalar_one_or_none()


async def _archive_players(db: AsyncSession, release_id: int | None) -> list[Player]:
    if release_id is None:
        return list((await db.execute(select(Player).order_by(Player.full_name))).scalars())
    return list(
        (
            await db.execute(
                select(Player)
                .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                .where(PlayerGameStat.release_id == release_id)
                .distinct()
                .order_by(Player.full_name)
            )
        ).scalars()
    )


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
    return any(term in f" {q} " for term in (" opponent ", " against ", " opposing ")) or any(
        re.search(rf"\b{re.escape(alias)}\b", q) for alias in _TEAM_ALIASES
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


def _is_player_intelligence(question: str, resolved: list[Player]) -> bool:
    q = question.lower()
    if any(term in q for term in ("who beat the knicks", "beat the knicks by", "knicks loss")):
        return False
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
    return (
        (
            bool(resolved)
            and (
                canonical_stats
                or operation
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
    if re.search(r"\bbetter\b", q) and not any(
        term in full for term in ("use points", "true shooting", "points rebounds and assists")
    ):
        return "better"
    return None


def _parse_last_count(
    text: str,
) -> tuple[int, Literal["archive_games", "appearances"]] | None:
    q = text.lower().replace("−", "-")
    number_pattern = "|".join((*_WORD_NUMBERS, r"-?\d{1,4}"))
    match = re.search(
        rf"\blast\s+({number_pattern})(?:\s+(appearances?|games?))?\b",
        q,
    )
    if not match:
        return None
    raw = match.group(1)
    count = _WORD_NUMBERS[raw] if raw in _WORD_NUMBERS else int(raw)
    unit: Literal["archive_games", "appearances"] = (
        "appearances" if (match.group(2) or "").startswith("appearance") else "archive_games"
    )
    return count, unit


def _window_limitation(text: str) -> str | None:
    if re.search(rf"\blast\s+negative\s+(?:{'|'.join(_WORD_NUMBERS)}|\d+)\b", text.lower()):
        return "A last-N window must contain at least one game or appearance."
    parsed = _parse_last_count(text)
    if parsed is None:
        return None
    count, _ = parsed
    if count <= 0:
        return "A last-N window must contain at least one game or appearance."
    if count > 101:
        return "That window exceeds the 101-game active archive. Choose 101 or fewer."
    return None


def _timeframe(text: str) -> tuple[Timeframe, dict[str, str | int | bool]]:
    q = text.lower().replace("–", "-").replace("—", "-")
    filters: dict[str, str | int | bool] = {}
    parsed_last = _parse_last_count(text)
    if parsed_last:
        count, unit = parsed_last
        scope = "playoffs" if "playoff" in q else "regular" if "regular season" in q else "full"
        filters["season_scope"] = scope
        return Timeframe(
            kind="last_n",
            label=f"last {count} {'appearances' if unit == 'appearances' else 'archive games'}",
            last_n=count,
            unit=unit,
        ), filters
    if re.search(r"\bbefore\s+(?:the\s+)?all[- ]star\b", q):
        return Timeframe(
            kind="date_range",
            label="before the 2026 All-Star break (through February 11, 2026)",
            end_date="2026-02-11",
        ), filters
    if re.search(r"\bafter\s+(?:the\s+)?all[- ]star\b", q):
        return Timeframe(
            kind="date_range",
            label="after the 2026 All-Star break (from February 19, 2026)",
            start_date="2026-02-19",
        ), filters
    date_range = re.search(
        r"\b(202[5-6]-\d{2}-\d{2})\s+(?:through|to|until)\s+(202[5-6]-\d{2}-\d{2})\b",
        q,
    )
    if date_range:
        start_date, end_date = date_range.groups()
        return Timeframe(
            kind="date_range",
            label=f"{start_date} through {end_date}",
            start_date=start_date,
            end_date=end_date,
        ), filters
    for month_name, month_number in _MONTHS.items():
        if re.search(rf"\b{month_name}\b", q):
            year = 2025 if month_number >= 10 else 2026
            start_date = date(year, month_number, 1)
            if month_number == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month_number + 1, 1)
            end_date = date.fromordinal(next_month.toordinal() - 1)
            return Timeframe(
                kind="month",
                label=f"{month_name.title()} {year}",
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            ), filters
    if "full archive" in q or "entire archive" in q:
        return Timeframe(kind="full_archive", label="full 2025-26 archive"), filters
    if "playoff" in q or "postseason" in q:
        return Timeframe(kind="playoffs", label="2025-26 playoffs"), filters
    return Timeframe(kind="regular_season", label="2025-26 regular season"), filters


def _has_explicit_timeframe(text: str) -> bool:
    q = text.lower()
    return bool(
        _parse_last_count(text)
        or any(month in q for month in _MONTHS)
        or re.search(r"\b(?:before|after)\s+(?:the\s+)?all[- ]star\b", q)
        or re.search(r"\b202[5-6]-\d{2}-\d{2}\b", q)
        or any(term in q for term in ("regular season", "playoff", "postseason", "full archive"))
    )


def _parse_plan(text: str, resolved: list[Player]) -> AnalyticsPlan:
    q = text.lower()
    timeframe, filters = _timeframe(text)
    stats = stat_keys_in_text(text)
    if "use true shooting percentage" in q:
        stats = ["true_shooting_percentage"]
    elif "use effective field goal percentage" in q:
        stats = ["effective_field_goal_percentage"]
    elif "use field goal percentage" in q:
        stats = ["field_goal_percentage"]
    elif "use scoring standard deviation" in q:
        stats = ["points_standard_deviation"]
    elif "use lowest scoring game" in q:
        stats = ["points_floor"]
    elif "use points rebounds and assists" in q:
        stats = ["points", "rebounds", "assists"]
    elif "use points" in q:
        stats = ["points"]
    if "scoring" in q and "points" not in stats:
        stats.insert(0, "points")
    has_explicit_stats = bool(stats)
    if not stats:
        stats = ["points"]

    threshold = None
    threshold_match = re.search(
        r"(?:at least\s+)?(\d+(?:\.\d+)?)\s*(?:\+|plus)?\s*"
        r"(points?|rebounds?|assists?|steals?|blocks?)",
        q,
    )
    if threshold_match:
        threshold = float(threshold_match.group(1))
        key = threshold_match.group(2).rstrip("s")
        key = {
            "point": "points",
            "rebound": "rebounds",
            "assist": "assists",
            "steal": "steals",
            "block": "blocks",
        }[key]
        if key not in stats:
            stats.insert(0, key)

    # Select the operation before applying any conditioning filters. Words such as
    # "winning" and "correlated" describe a question; they do not select only wins.
    if any(term in q for term in ("notable", "surprising", "interesting", "discover")):
        operation = AnalyticsOperation.NOTABLE_FACTS
        output = OutputType.FACTS
        if not has_explicit_stats:
            stats = ["points", "rebounds", "assists"]
    elif any(
        term in q
        for term in ("when he", "when they", "record when", "outcome", "cause", "correlat")
    ):
        operation = AnalyticsOperation.OUTCOME_ASSOCIATION
        output = OutputType.COMPARISON
    elif (
        any(term in q for term in ("outlier", "unusual game", "best game", "worst game"))
        and resolved
    ):
        operation = AnalyticsOperation.OUTLIER
        output = OutputType.CHART
    elif any(term in q for term in ("trend", "trending", "improving", "declining")):
        operation = AnalyticsOperation.TREND
        output = OutputType.CHART
    elif "streak" in q or "consecutive" in q:
        operation = AnalyticsOperation.STREAK
        output = OutputType.TABLE
    elif any(
        term in q for term in ("win/loss", "wins vs losses", "home/away", "home vs away", "split")
    ):
        operation = AnalyticsOperation.SPLIT
        output = OutputType.COMPARISON
    elif len(resolved) >= 2 or "compare" in q or " versus " in q:
        operation = AnalyticsOperation.PLAYER_COMPARISON
        output = OutputType.COMPARISON
    elif (
        any(
            term in q
            for term in (
                "leader",
                "most ",
                "top ",
                "who had",
                "rank players",
                "who led",
                "which player led",
            )
        )
        and not resolved
    ):
        operation = AnalyticsOperation.LEADERBOARD
        output = OutputType.TABLE
    elif any(term in q for term in ("recent versus", "recent vs", "baseline")):
        operation = AnalyticsOperation.PERIOD_COMPARISON
        output = OutputType.COMPARISON
    elif any(
        term in q
        for term in (
            "game log",
            "game-by-game",
            "game by game",
            "show me his last",
            "show me their last",
        )
    ):
        operation = AnalyticsOperation.GAME_LOG
        output = OutputType.TABLE
    else:
        operation = AnalyticsOperation.AGGREGATE
        output = OutputType.TABLE

    split_question = operation == AnalyticsOperation.SPLIT
    if not split_question and re.search(r"\bin\s+(?:knicks\s+|nyk\s+)?wins?\b", q):
        filters["outcome"] = "win"
    if not split_question and re.search(r"\bin\s+(?:knicks\s+|nyk\s+)?loss(?:es)?\b", q):
        filters["outcome"] = "loss"
    if not split_question and re.search(r"\b(?:at home|in home games)\b", q):
        filters["location"] = "home"
    if not split_question and re.search(r"\b(?:on the road|in away games)\b", q):
        filters["location"] = "away"
    if re.search(r"\b(?:as a starter|in games (?:he|they) started)\b", q):
        filters["starter"] = True
    if re.search(r"\b(?:off the bench|as a reserve)\b", q):
        filters["starter"] = False
    for alias, team_id in _TEAM_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            filters["opponent"] = team_id
            break

    asks_average = any(term in q for term in ("average", "averaged", "per game", "per appearance"))
    asks_total = bool(
        "total" in q
        or re.search(
            r"\bhow many\s+(?:points?|rebounds?|assists?|steals?|blocks?|double|triple)", q
        )
        or re.search(r"\bmost\s+(?:points?|rebounds?|assists?|steals?|blocks?)\b", q)
    )
    aggregation_mode = (
        "both" if asks_average and asks_total else "total" if asks_total else "average"
    )

    return AnalyticsPlan(
        resolved_players=[
            ResolvedPlayer(
                player_id=player.id,
                nba_person_id=player.nba_player_id,
                full_name=player.full_name,
            )
            for player in resolved
        ],
        timeframe=timeframe,
        filters=filters,
        stats=stats[:8],
        operations=[operation],
        output_type=output,
        aggregation_mode=aggregation_mode,
        retrieval_required=False,
        threshold=threshold,
    )


def _row_dict(stat: PlayerGameStat, player: Player, game: Game) -> dict[str, Any]:
    home = game.home_team_id == stat.team_id
    own_score = game.home_score if home else game.away_score
    opponent_score = game.away_score if home else game.home_score
    row = {
        "game_id": game.id,
        "date": game.game_date.isoformat(),
        "season_type": game.season_type,
        "player_id": player.id,
        "nba_person_id": player.nba_player_id,
        "player_name": player.full_name,
        "team_id": stat.team_id,
        "opponent": game.away_team_id if home else game.home_team_id,
        "home": home,
        "win": own_score > opponent_score,
        "knicks_win": (
            game.home_score > game.away_score
            if game.home_team_id == "NYK"
            else game.away_score > game.home_score
        ),
        "starter": bool(stat.starter),
        "appeared": float(stat.minutes or 0) > 0,
        "score": {
            stat.team_id: own_score,
            game.away_team_id if home else game.home_team_id: opponent_score,
        },
    }
    row.update({column: getattr(stat, column) for column in _STAT_COLUMNS})
    return row


async def _games_and_rows(
    db: AsyncSession, release_id: int | None, season: str
) -> tuple[list[Game], list[dict[str, Any]]]:
    game_stmt = (
        select(Game)
        .where(
            Game.season == season,
            or_(Game.home_team_id == "NYK", Game.away_team_id == "NYK"),
            Game.status == "final",
        )
        .order_by(Game.game_date, Game.nba_game_id)
    )
    if release_id is not None:
        game_stmt = game_stmt.where(Game.release_id == release_id)
    games = list((await db.execute(game_stmt)).scalars())
    if release_id is None:
        return games, []
    rows = (
        await db.execute(
            select(PlayerGameStat, Player, Game)
            .join(Player, Player.id == PlayerGameStat.player_id)
            .join(Game, Game.id == PlayerGameStat.game_id)
            .where(
                PlayerGameStat.release_id == release_id,
                Game.release_id == release_id,
                Game.season == season,
                or_(Game.home_team_id == "NYK", Game.away_team_id == "NYK"),
            )
            .order_by(Game.game_date, Game.nba_game_id, Player.nba_player_id)
        )
    ).all()
    return games, [_row_dict(stat, player, game) for stat, player, game in rows]


def _select_window(
    games: list[Game], rows: list[dict[str, Any]], plan: AnalyticsPlan
) -> tuple[list[Game], list[dict[str, Any]]]:
    timeframe = plan.timeframe
    scoped_games = games
    if timeframe.kind == "regular_season":
        scoped_games = [game for game in games if game.season_type == "regular"]
    elif timeframe.kind == "playoffs":
        scoped_games = [game for game in games if game.season_type in {"play_in", "playoffs"}]
    elif timeframe.kind == "last_n":
        scope = plan.filters.get("season_scope")
        if scope == "regular":
            scoped_games = [game for game in games if game.season_type == "regular"]
        elif scope == "playoffs":
            scoped_games = [game for game in games if game.season_type in {"play_in", "playoffs"}]
        if timeframe.unit == "archive_games":
            scoped_games = scoped_games[-int(timeframe.last_n or 1) :]
    elif timeframe.kind in {"date_range", "month"}:
        start_date = date.fromisoformat(timeframe.start_date) if timeframe.start_date else None
        end_date = date.fromisoformat(timeframe.end_date) if timeframe.end_date else None
        scoped_games = [
            game
            for game in games
            if (start_date is None or game.game_date >= start_date)
            and (end_date is None or game.game_date <= end_date)
        ]
    game_ids = {game.id for game in scoped_games}
    selected = [row for row in rows if row["game_id"] in game_ids]
    player_ids = {player.player_id for player in plan.resolved_players}
    if player_ids:
        selected = [row for row in selected if row["player_id"] in player_ids]
    if timeframe.kind == "last_n" and timeframe.unit == "appearances" and player_ids:
        by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in selected:
            if row["appeared"]:
                by_player[row["player_id"]].append(row)
        keep = {
            row["game_id"]
            for player_rows in by_player.values()
            for row in player_rows[-int(timeframe.last_n or 1) :]
        }
        selected = [row for row in selected if row["game_id"] in keep]
        scoped_games = [game for game in scoped_games if game.id in keep]
    for key, value in plan.filters.items():
        if key == "outcome":
            selected = [row for row in selected if row["win"] is (value == "win")]
        elif key == "location":
            selected = [row for row in selected if row["home"] is (value == "home")]
        elif key == "starter":
            selected = [row for row in selected if row["starter"] is bool(value)]
        elif key == "opponent":
            selected = [row for row in selected if row["opponent"] == value]
    if plan.filters.get("outcome"):
        want_win = plan.filters["outcome"] == "win"
        scoped_games = [
            game
            for game in scoped_games
            if (
                (game.home_score > game.away_score)
                if game.home_team_id == "NYK"
                else (game.away_score > game.home_score)
            )
            is want_win
        ]
    if plan.filters.get("location"):
        want_home = plan.filters["location"] == "home"
        scoped_games = [game for game in scoped_games if (game.home_team_id == "NYK") is want_home]
    if plan.filters.get("opponent"):
        opponent = plan.filters["opponent"]
        scoped_games = [
            game for game in scoped_games if opponent in {game.home_team_id, game.away_team_id}
        ]
    return scoped_games, selected


def _display(stat: str, value: float | None) -> str:
    if value is None:
        return "—"
    definition = STAT_REGISTRY[stat]
    if definition.kind == "percentage" or stat.endswith("_percentage"):
        return f"{value:.1f}%"
    return f"{value:.{definition.decimals}f}"


def _aggregate_value_sets(
    plan: AnalyticsPlan, rows: list[dict[str, Any]]
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    averages = aggregate_rows(rows, plan.stats)
    totals: dict[str, float | None] = {}
    for key in plan.stats:
        definition = STAT_REGISTRY[key]
        if definition.kind in {"count", "minutes"}:
            totals[key] = sum(float(row.get(definition.columns[0], 0) or 0) for row in rows)
        else:
            # Rates remain weighted across the complete sample; per-36 uses total minutes.
            totals[key] = averages[key]
    return averages, totals


def _mode_values(
    plan: AnalyticsPlan, rows: list[dict[str, Any]]
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    averages, totals = _aggregate_value_sets(plan, rows)
    primary = totals if plan.aggregation_mode == "total" else averages
    return primary, averages, totals


def _common_result(
    result_type: str,
    title: str,
    plan: AnalyticsPlan,
    source_rows: list[dict[str, Any]],
    *,
    result_id: str = "result-1",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    source_ids = sorted({int(row["game_id"]) for row in source_rows})
    return {
        "id": result_id,
        "type": result_type,
        "title": title,
        "raw_values": {},
        "display_values": {},
        "sample_size": sum(bool(row["appeared"]) for row in source_rows),
        "timeframe": plan.timeframe.model_dump(mode="json"),
        "warnings": warnings or [],
        "source_game_ids": source_ids,
    }


def _aggregate_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    appearances = [row for row in rows if row["appeared"]]
    name = plan.resolved_players[0].full_name if plan.resolved_players else "Selected players"
    result = _common_result("aggregate", f"{name} — {plan.timeframe.label}", plan, rows)
    values, averages, totals = _mode_values(plan, appearances)
    result["raw_values"] = values
    result["display_values"] = {key: _display(key, value) for key, value in values.items()}
    result["aggregation_mode"] = plan.aggregation_mode
    result["per_appearance_values"] = averages
    result["per_appearance_display_values"] = {
        key: _display(key, value) for key, value in averages.items()
    }
    result["totals"] = totals
    result["total_display_values"] = {key: _display(key, value) for key, value in totals.items()}
    for stat in plan.stats:
        attempts_column = None
        minimum = 0
        if stat in {
            "field_goal_percentage",
            "true_shooting_percentage",
            "effective_field_goal_percentage",
        }:
            attempts_column, minimum = "field_goals_attempted", 5
        elif stat == "three_point_percentage":
            attempts_column, minimum = "three_pointers_attempted", 2
        elif stat == "free_throw_percentage":
            attempts_column, minimum = "free_throws_attempted", 2
        if attempts_column and appearances:
            attempts = sum(float(row[attempts_column]) for row in appearances) / len(appearances)
            if attempts < minimum:
                result["warnings"].append(
                    f"Named-player result is below the {minimum} attempts-per-appearance "
                    "ranking threshold."
                )
    return result


def _game_log_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    appearances = [row for row in rows if row["appeared"]]
    name = plan.resolved_players[0].full_name if plan.resolved_players else "Player"
    result = _common_result("game_log", f"{name} game log", plan, rows)
    result["entries"] = [
        {
            "game_id": row["game_id"],
            "date": row["date"],
            "opponent": row["opponent"],
            "result": "W" if row["win"] else "L",
            "raw_values": {key: aggregate_rows([row], [key])[key] for key in plan.stats},
            "display_values": {
                key: _display(key, aggregate_rows([row], [key])[key]) for key in plan.stats
            },
        }
        for row in reversed(appearances)
    ]
    return result


def _comparison_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["appeared"]:
            groups[row["player_id"]].append(row)
    result = _common_result("player_comparison", "Player comparison", plan, rows)
    result["groups"] = []
    for player in plan.resolved_players:
        values, averages, totals = _mode_values(plan, groups[player.player_id])
        result["groups"].append(
            {
                "key": str(player.nba_person_id),
                "label": player.full_name,
                "sample_size": len(groups[player.player_id]),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in groups[player.player_id]}),
            }
        )
        if len(groups[player.player_id]) < 4:
            result["warnings"].append(
                f"{player.full_name} has fewer than four appearances in the comparison."
            )
    return result


def _period_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    appearances = [row for row in rows if row["appeared"]]
    size = plan.timeframe.last_n or min(5, max(1, len(appearances) // 2))
    recent = appearances[-size:]
    prior = appearances[:-size]
    result = _common_result(
        "period_comparison", "Recent appearances versus prior baseline", plan, rows
    )
    result["groups"] = []
    for label, group in (("Recent", recent), ("Prior baseline", prior)):
        values, averages, totals = _mode_values(plan, group)
        result["groups"].append(
            {
                "key": label.lower().replace(" ", "_"),
                "label": label,
                "sample_size": len(group),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in group}),
            }
        )
    if len(recent) < 4 or len(prior) < 4:
        result["warnings"].append("Period comparisons need at least four appearances per side.")
    return result


def _split_result(plan: AnalyticsPlan, rows: list[dict[str, Any]], text: str) -> dict[str, Any]:
    if "home" in text.lower() or "away" in text.lower():
        keys = (("Home", lambda row: row["home"]), ("Away", lambda row: not row["home"]))
    elif "starter" in text.lower() or "bench" in text.lower():
        keys = (("Starter", lambda row: row["starter"]), ("Bench", lambda row: not row["starter"]))
    else:
        keys = (("Wins", lambda row: row["win"]), ("Losses", lambda row: not row["win"]))
    result = _common_result("split", "Player split", plan, rows)
    result["groups"] = []
    for label, predicate in keys:
        group = [row for row in rows if row["appeared"] and predicate(row)]
        values, averages, totals = _mode_values(plan, group)
        result["groups"].append(
            {
                "key": label.lower(),
                "label": label,
                "sample_size": len(group),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in group}),
            }
        )
        if len(group) < 4:
            result["warnings"].append(f"{label} has fewer than four appearances.")
    return result


def _leaderboard_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    knicks = [row for row in rows if row["team_id"] == "NYK" and row["appeared"]]
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in knicks:
        groups[row["player_id"]].append(row)
    stat = plan.stats[0]
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for player_rows in groups.values():
        values, averages, totals = _mode_values(plan, player_rows)
        eligible = True
        attempts = 0.0
        if stat in {
            "field_goal_percentage",
            "true_shooting_percentage",
            "effective_field_goal_percentage",
        }:
            attempts = sum(row["field_goals_attempted"] for row in player_rows) / len(player_rows)
            eligible = attempts >= 5
        elif stat == "three_point_percentage":
            attempts = sum(row["three_pointers_attempted"] for row in player_rows) / len(
                player_rows
            )
            eligible = attempts >= 2
        elif stat == "free_throw_percentage":
            attempts = sum(row["free_throws_attempted"] for row in player_rows) / len(player_rows)
            eligible = attempts >= 2
        if not eligible or values[stat] is None:
            continue
        entries.append(
            {
                "player_id": player_rows[0]["nba_person_id"],
                "player_name": player_rows[0]["player_name"],
                "sample_size": len(player_rows),
                "raw_values": values,
                "display_values": {key: _display(key, value) for key, value in values.items()},
                "aggregation_mode": plan.aggregation_mode,
                "per_appearance_values": averages,
                "total_values": totals,
                "source_game_ids": sorted({row["game_id"] for row in player_rows}),
                "eligibility_attempts_per_appearance": attempts or None,
            }
        )
    entries.sort(key=lambda item: (-(item["raw_values"][stat] or 0), item["player_name"]))
    if not entries:
        warnings.append("No players met the requested ranking eligibility in this window.")
    result = _common_result(
        "leaderboard",
        f"Knicks {STAT_REGISTRY[stat].label} leaders",
        plan,
        knicks,
        warnings=warnings,
    )
    result["stat"] = stat
    result["aggregation_mode"] = plan.aggregation_mode
    result["entries"] = entries[:10]
    return result


def _streak_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    threshold = plan.threshold if plan.threshold is not None else STAT_REGISTRY[stat].materiality
    appearances = [row for row in rows if row["appeared"]]
    streaks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in appearances:
        value = aggregate_rows([row], [stat])[stat]
        if value is not None and value >= threshold:
            current.append(row)
        elif current:
            streaks.append(current)
            current = []
    if current:
        streaks.append(current)
    best = max(streaks, key=lambda group: (len(group), group[-1]["date"]), default=[])
    result = _common_result(
        "streak",
        f"Games with at least {_display(stat, threshold)} {STAT_REGISTRY[stat].label.lower()}",
        plan,
        best,
    )
    result["stat"] = stat
    result["threshold"] = threshold
    result["length"] = len(best)
    result["start_date"] = best[0]["date"] if best else None
    result["end_date"] = best[-1]["date"] if best else None
    return result


def _trend_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    appearances = [row for row in rows if row["appeared"]]
    values = [float(aggregate_rows([row], [stat])[stat] or 0) for row in appearances]
    recent = appearances[-5:]
    prior = appearances[:-5]
    recent_value = aggregate_rows(recent, [stat])[stat]
    prior_value = aggregate_rows(prior, [stat])[stat]
    delta = (
        recent_value - prior_value if recent_value is not None and prior_value is not None else None
    )
    warnings = []
    if len(appearances) < 8:
        warnings.append("Trend interpretation needs at least eight appearances.")
    meaningful = bool(
        delta is not None
        and abs(delta) >= STAT_REGISTRY[stat].materiality
        and len(appearances) >= 8
    )
    result = _common_result(
        "trend", f"{STAT_REGISTRY[stat].label} trend", plan, appearances, warnings=warnings
    )
    result.update(
        {
            "stat": stat,
            "series": [
                {
                    "game_id": row["game_id"],
                    "date": row["date"],
                    "value": value,
                    "rolling_mean": mean,
                }
                for row, value, mean in zip(appearances, values, rolling_mean(values), strict=True)
            ],
            "slope": linear_slope(values),
            "recent_value": recent_value,
            "prior_value": prior_value,
            "delta": delta,
            "meaningful": meaningful,
        }
    )
    return result


def _outlier_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    appearances = [row for row in rows if row["appeared"]]
    values = [float(aggregate_rows([row], [stat])[stat] or 0) for row in appearances]
    scores = robust_outlier_scores(values)
    ranked = sorted(
        zip(appearances, values, scores, strict=True), key=lambda item: (-abs(item[2]), -item[1])
    )
    selected = ranked[:3]
    warnings = []
    if len(appearances) < 10:
        warnings.append("Outlier detection needs a baseline of at least ten appearances.")
    result = _common_result(
        "outlier",
        f"{STAT_REGISTRY[stat].label} outliers",
        plan,
        appearances,
        warnings=warnings,
    )
    result["sample_size"] = len(appearances)
    result["candidate_count"] = len(selected)
    result["stat"] = stat
    result["entries"] = [
        {
            "game_id": row["game_id"],
            "date": row["date"],
            "opponent": row["opponent"],
            "value": value,
            "display_value": _display(stat, value),
            "robust_score": score,
        }
        for row, value, score in selected
    ]
    return result


def _outcome_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    stat = plan.stats[0]
    threshold = plan.threshold if plan.threshold is not None else 20.0
    appearances = [row for row in rows if row["appeared"]]
    qualifying = [
        row for row in appearances if float(aggregate_rows([row], [stat])[stat] or 0) >= threshold
    ]
    other = [row for row in appearances if row not in qualifying]
    warnings = ["This describes association, not causation or statistical significance."]
    if len(appearances) < 12:
        warnings.append("Outcome association needs at least twelve appearances.")

    def record(group: list[dict[str, Any]]) -> dict[str, int]:
        wins = sum(row["win"] for row in group)
        return {"wins": wins, "losses": len(group) - wins, "games": len(group)}

    result = _common_result(
        "outcome_association",
        f"Team record by {STAT_REGISTRY[stat].label.lower()} threshold",
        plan,
        appearances,
        warnings=warnings,
    )
    result.update(
        {
            "stat": stat,
            "threshold": threshold,
            "qualifying": record(qualifying),
            "other": record(other),
        }
    )
    return result


def _facts_result(plan: AnalyticsPlan, rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_player: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["appeared"] and row["team_id"] == "NYK":
            by_player[row["player_id"]].append(row)
    candidates: list[FactCandidate] = []
    for player_rows in by_player.values():
        if len(player_rows) < 8:
            continue
        recent = player_rows[-5:]
        prior = player_rows[:-5]
        for stat in plan.stats or ["points", "rebounds", "assists"]:
            recent_value = aggregate_rows(recent, [stat])[stat]
            prior_value = aggregate_rows(prior, [stat])[stat]
            if recent_value is None or prior_value is None:
                continue
            delta = recent_value - prior_value
            materiality = max(STAT_REGISTRY[stat].materiality, 0.1)
            if abs(delta) < materiality:
                continue
            name = player_rows[0]["player_name"]
            direction = "more" if delta > 0 else "fewer"
            statement = (
                f"{name} averaged {abs(delta):.1f} {direction} "
                f"{STAT_REGISTRY[stat].label.lower()} over his latest five "
                "appearances than before that window."
            )
            candidates.append(
                FactCandidate(
                    fact_type="recent_vs_baseline",
                    player_ids=(player_rows[0]["nba_person_id"],),
                    stat_keys=(stat,),
                    timeframe=plan.timeframe.model_dump(mode="json"),
                    statement=statement,
                    result={"recent": recent_value, "prior": prior_value, "delta": delta},
                    source_game_ids=tuple(row["game_id"] for row in player_rows),
                    sample_size=len(player_rows),
                    components={
                        "magnitude": min(1.0, abs(delta) / (2 * materiality)),
                        "rarity": 0.5,
                        "sample_quality": min(1.0, len(player_rows) / 20),
                        "recency": 1.0,
                        "coverage": 1.0,
                        "basketball_relevance": 0.8,
                        "novelty": 0.8,
                        "interpretability": 1.0,
                    },
                    penalties={"small_sample": 0.1 if len(prior) < 4 else 0},
                )
            )
    selected = rank_fact_candidates(candidates)
    source_rows = [
        row
        for row in rows
        if row["game_id"]
        in {game_id for candidate in selected for game_id in candidate.source_game_ids}
    ]
    result = _common_result(
        "notable_facts",
        "Exploratory notable facts",
        plan,
        source_rows,
        warnings=["Discovery is exploratory and bounded to the resolved archive window."],
    )
    result["facts"] = []
    for candidate in selected:
        score, components = score_fact_candidate(candidate)
        result["facts"].append(
            {
                "fingerprint": fact_fingerprint(candidate),
                "statement": candidate.statement,
                "fact_type": candidate.fact_type,
                "player_ids": list(candidate.player_ids),
                "stat_keys": list(candidate.stat_keys),
                "result": candidate.result,
                "sample_size": candidate.sample_size,
                "score": score,
                "score_components": components,
                "source_game_ids": list(candidate.source_game_ids),
            }
        )
    return result


async def _precomputed_facts_result(
    db: AsyncSession,
    release_id: int | None,
    plan: AnalyticsPlan,
    games: list[Game],
) -> dict[str, Any] | None:
    if release_id is None:
        return None
    timeframe = plan.timeframe
    is_catalog_window = timeframe.kind in {"regular_season", "playoffs", "full_archive"} or (
        timeframe.kind == "last_n" and timeframe.last_n == 10
    )
    if not is_catalog_window:
        return None
    facts = list(
        (
            await db.execute(
                select(GeneratedStatFact)
                .where(GeneratedStatFact.release_id == release_id)
                .order_by(GeneratedStatFact.total_score.desc(), GeneratedStatFact.fingerprint)
                .limit(200)
            )
        ).scalars()
    )
    requested_players = {player.nba_person_id for player in plan.resolved_players}
    selected: list[tuple[GeneratedStatFact, dict[str, Any], list[int], list[str]]] = []
    seen: set[tuple[tuple[int, ...], tuple[str, ...], str]] = set()
    for fact in facts:
        fact_timeframe = json.loads(fact.timeframe_json)
        if timeframe.kind == "last_n":
            if fact_timeframe.get("kind") != "last_n" or fact_timeframe.get("last_n") != 10:
                continue
            if fact_timeframe.get("unit") != timeframe.unit:
                continue
        elif fact_timeframe.get("kind") != timeframe.kind:
            continue
        player_ids = [int(value) for value in json.loads(fact.player_ids_json)]
        if requested_players and not requested_players.intersection(player_ids):
            continue
        stat_keys = [str(value) for value in json.loads(fact.stat_keys_json)]
        if plan.stats and not set(plan.stats).intersection(stat_keys):
            continue
        key = (tuple(sorted(player_ids)), tuple(sorted(stat_keys)), fact.fact_type)
        if key in seen:
            continue
        selected.append((fact, fact_timeframe, player_ids, stat_keys))
        seen.add(key)
        if len(selected) == 3:
            break
    if not selected:
        return None
    game_ids_by_source = {str(game.nba_game_id): game.id for game in games}
    source_rows: list[dict[str, Any]] = []
    result = _common_result(
        "notable_facts",
        "Exploratory notable facts",
        plan,
        source_rows,
        warnings=["Discovery is exploratory and bounded to the resolved archive window."],
    )
    result["facts"] = []
    all_source_ids: set[int] = set()
    for fact, fact_timeframe, player_ids, stat_keys in selected:
        source_ids = [
            game_ids_by_source[str(value)]
            for value in json.loads(fact.source_game_ids_json)
            if str(value) in game_ids_by_source
        ]
        all_source_ids.update(source_ids)
        result["facts"].append(
            {
                "fingerprint": fact.fingerprint,
                "statement": fact.statement,
                "fact_type": fact.fact_type,
                "player_ids": player_ids,
                "stat_keys": stat_keys,
                "timeframe": fact_timeframe,
                "result": json.loads(fact.result_json),
                "sample_size": fact.sample_size,
                "score": fact.total_score,
                "score_components": json.loads(fact.score_components_json),
                "source_game_ids": source_ids,
            }
        )
    result["source_game_ids"] = sorted(all_source_ids)
    result["sample_size"] = max(fact.sample_size for fact, *_ in selected)
    return result


def _execute(plan: AnalyticsPlan, rows: list[dict[str, Any]], text: str) -> dict[str, Any]:
    operation = plan.operations[0]
    if operation == AnalyticsOperation.GAME_LOG:
        return _game_log_result(plan, rows)
    if operation == AnalyticsOperation.PLAYER_COMPARISON:
        return _comparison_result(plan, rows)
    if operation == AnalyticsOperation.PERIOD_COMPARISON:
        return _period_result(plan, rows)
    if operation == AnalyticsOperation.SPLIT:
        return _split_result(plan, rows, text)
    if operation == AnalyticsOperation.LEADERBOARD:
        return _leaderboard_result(plan, rows)
    if operation == AnalyticsOperation.STREAK:
        return _streak_result(plan, rows)
    if operation == AnalyticsOperation.TREND:
        return _trend_result(plan, rows)
    if operation == AnalyticsOperation.OUTLIER:
        return _outlier_result(plan, rows)
    if operation == AnalyticsOperation.OUTCOME_ASSOCIATION:
        return _outcome_result(plan, rows)
    if operation == AnalyticsOperation.NOTABLE_FACTS:
        return _facts_result(plan, rows)
    return _aggregate_result(plan, rows)


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
                f"{STAT_REGISTRY[key].label.lower()} {value} per appearance"
                for key, value in result["per_appearance_display_values"].items()
            )
            totals = ", ".join(
                f"{STAT_REGISTRY[key].label.lower()} {value} total"
                for key, value in result["total_display_values"].items()
            )
            return (
                f"{result['title']}: {averages}; {totals} across "
                f"{result['sample_size']} appearances."
            )
        suffix = "total" if mode == "total" else "per appearance"
        values = ", ".join(
            f"{STAT_REGISTRY[key].label.lower()} {value} {suffix}"
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
        label = "total" if mode == "total" else "per appearance"
        return (
            f"{leader['player_name']} led at {leader['display_values'][stat]} {label} "
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


def _coverage(games: list[Game], rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {game.id for game in games}
    covered = {row["game_id"] for row in rows}
    missing = sorted(expected - covered)
    return {
        "expected_game_count": len(expected),
        "covered_game_count": len(expected & covered),
        "missing_game_ids": missing,
        "completeness": 1.0 if not expected else round(len(expected & covered) / len(expected), 4),
        "data_through": max((game.game_date.isoformat() for game in games), default=None),
    }


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


def _validate_requested_window(
    plan: AnalyticsPlan, games: list[Game], all_rows: list[dict[str, Any]]
) -> str | None:
    timeframe = plan.timeframe
    if timeframe.kind == "last_n":
        scoped_games = games
        scope = plan.filters.get("season_scope")
        if scope == "regular":
            scoped_games = [game for game in games if game.season_type == "regular"]
        elif scope == "playoffs":
            scoped_games = [game for game in games if game.season_type in {"play_in", "playoffs"}]
        requested = int(timeframe.last_n or 0)
        if timeframe.unit == "archive_games" and requested > len(scoped_games):
            return (
                f"That window requests {requested} games, but only {len(scoped_games)} "
                "matching archive games are available."
            )
        if timeframe.unit == "appearances" and plan.resolved_players:
            scoped_ids = {game.id for game in scoped_games}
            available = []
            for player in plan.resolved_players:
                available.append(
                    sum(
                        bool(row["appeared"])
                        for row in all_rows
                        if row["game_id"] in scoped_ids and row["player_id"] == player.player_id
                    )
                )
            if any(requested > count for count in available):
                return (
                    f"That window requests {requested} appearances, but the smallest resolved "
                    f"player sample contains {min(available, default=0)}."
                )
    if timeframe.kind in {"date_range", "month"}:
        start = date.fromisoformat(timeframe.start_date) if timeframe.start_date else date.min
        end = date.fromisoformat(timeframe.end_date) if timeframe.end_date else date.max
        if start > end:
            return "The requested date range ends before it starts."
        if not any(start <= game.game_date <= end for game in games):
            return "No active-release Knicks games fall inside that requested date window."
    return None


async def answer_player_question(
    db: AsyncSession,
    *,
    question: str,
    season: str,
    context: list[dict[str, str]] | None = None,
) -> AnalyticsAnswer | None:
    """Return typed analytics when the question is in the player-intelligence domain."""
    release_id = await _release_id(db)
    players = await _archive_players(db, release_id)
    context = context or []
    combined, substantive_question = _fold_question(question, context)
    resolved, ambiguous_players = _resolve_players(combined, players)
    if not _is_player_intelligence(combined, resolved):
        return None
    invalid_window = _window_limitation(combined)
    if invalid_window:
        return _limited_answer(combined, invalid_window)
    q = combined.lower()
    season_mentions = set(re.findall(r"\b20\d{2}-\d{2}\b", q))
    explicit_years = {int(value) for value in re.findall(r"\b(20\d{2})\b", q)}
    if (season_mentions and season_mentions != {"2025-26"}) or any(
        year not in {2025, 2026} for year in explicit_years
    ):
        return _limited_answer(
            combined,
            "That timeframe is outside the active 2025-26 archive.",
        )
    unsupported_months = {
        month for month in _ALL_MONTH_NAMES - set(_MONTHS) if re.search(rf"\b{month}\b", q)
    }
    if unsupported_months:
        return _limited_answer(
            combined,
            "That month is outside the active 2025-26 archive window.",
        )
    if any(concept in combined.lower() for concept in _UNSUPPORTED_CONCEPTS):
        return _limited_answer(
            combined,
            "That concept is not available from the release-scoped box-score archive.",
        )
    if re.search(r"\b(?:why|reason)\b.*\bdnp\b|\bdnp\b.*\b(?:why|reason)\b", combined.lower()):
        return _limited_answer(
            combined,
            "The archive can report observed appearances, but not exact inactive or DNP reasons.",
        )
    if ambiguous_players:
        clarification = _clarification("player", ambiguous_players)
        analytics = {
            "status": "clarification_required",
            "resolved_question": combined,
            "plan": None,
            "clarification": clarification,
            "results": [],
            "coverage": None,
        }
        return AnalyticsAnswer(clarification["prompt"], analytics, [], [])
    ambiguity = _ambiguity(substantive_question, combined)
    if ambiguity:
        clarification = _clarification(ambiguity)
        analytics = {
            "status": "clarification_required",
            "resolved_question": combined,
            "plan": None,
            "clarification": clarification,
            "results": [],
            "coverage": None,
        }
        return AnalyticsAnswer(clarification["prompt"], analytics, [], [])
    if (
        not resolved
        and _name_like_slots(combined)
        and not any(
            term in combined.lower()
            for term in (*_DISCOVERY_TERMS, "rank players", "who led", "most ")
        )
    ):
        return _limited_answer(
            combined,
            "I could not resolve that player unambiguously in the active-release archive.",
        )
    clarification_selection = _is_clarification_selection(question, context)
    planning_text = combined if clarification_selection else question
    deterministic_plan = _parse_plan(planning_text, resolved)
    if (
        combined != question
        and not clarification_selection
        and not _has_explicit_timeframe(question)
    ):
        inherited_timeframe, inherited_filters = _timeframe(combined)
        filters = dict(deterministic_plan.filters)
        if "season_scope" in inherited_filters:
            filters["season_scope"] = inherited_filters["season_scope"]
        deterministic_plan = deterministic_plan.model_copy(
            update={"timeframe": inherited_timeframe, "filters": filters}
        )
    plan = await maybe_refine_analytics_plan(planning_text, deterministic_plan)
    games, all_rows = await _games_and_rows(db, release_id, season)
    window_limitation = _validate_requested_window(plan, games, all_rows)
    if window_limitation:
        return _limited_answer(combined, window_limitation, plan=plan)
    selected_games, rows = _select_window(games, all_rows, plan)
    knicks_premise = bool(
        re.search(
            r"\b(?:knicks player|as a knick|for the knicks|with the knicks)\b",
            combined.lower(),
        )
    )
    if knicks_premise and plan.resolved_players:
        selected_player_ids = {player.player_id for player in plan.resolved_players}
        knicks_player_ids = {row["player_id"] for row in all_rows if row["team_id"] == "NYK"}
        contradicted = selected_player_ids - knicks_player_ids
        if contradicted:
            names = ", ".join(
                player.full_name
                for player in plan.resolved_players
                if player.player_id in contradicted
            )
            return _limited_answer(
                combined,
                f"The archive rows do not support the premise that {names} played for the Knicks.",
            )
    if plan.resolved_players and not rows:
        return _limited_answer(
            combined,
            "The resolved player has no eligible appearances in that exact archive window.",
        )
    result = None
    if plan.operations[0] == AnalyticsOperation.NOTABLE_FACTS:
        result = await _precomputed_facts_result(db, release_id, plan, selected_games)
    result = result or _execute(plan, rows, combined)
    selected_game_ids = {game.id for game in selected_games}
    coverage_rows = [row for row in all_rows if row["game_id"] in selected_game_ids]
    coverage = _coverage(selected_games, coverage_rows)
    if _asks_availability(combined) and plan.resolved_players:
        appearances = sum(bool(row["appeared"]) for row in rows)
        result["availability"] = True
        result["appearances"] = appearances
        result["requested_team_games"] = len(selected_games)
        result["source_game_ids"] = sorted(selected_game_ids)
        result["sample_size"] = appearances
        result["warnings"].append(
            "Appearances are observed from box scores; exact inactive and DNP reasons are "
            "unavailable."
        )
        resolved_ids = {player.player_id for player in plan.resolved_players}
        observed_teams = {row["team_id"] for row in all_rows if row["player_id"] in resolved_ids}
        if observed_teams - {"NYK"} or len({row["game_id"] for row in rows}) < len(selected_games):
            result["warnings"].append(
                "Roster eligibility is unavailable, so this is an observed-tenure count rather "
                "than an exact games-missed total."
            )
    warnings = list(result.get("warnings", []))
    if not all_rows:
        warnings.append("Player box-score facts are unavailable for the active release.")
    if coverage["missing_game_ids"]:
        warnings.append("The requested window has partial player-stat coverage.")
    insufficient = any("needs" in warning or "fewer than" in warning for warning in warnings)
    status = (
        "complete"
        if all_rows and not coverage["missing_game_ids"] and not insufficient
        else "limited"
    )
    answer = _answer_text(result)
    if not all_rows and plan.operations[0] == AnalyticsOperation.LEADERBOARD:
        answer = (
            f"No complete player {STAT_REGISTRY[plan.stats[0]].label.lower()} facts are "
            "available for this archive window."
        )
    analytics = {
        "status": status,
        "resolved_question": combined,
        "plan": _consumer_plan(plan),
        "clarification": None,
        "results": [result],
        "coverage": coverage,
    }
    if not validate_analytics_evidence(answer, analytics):
        warnings.append("Narrative generation was withheld because it failed evidence validation.")
        answer = f"{result['title']}. The grounded result is shown with its supporting games."
    games_by_id = {game.id: game for game in selected_games}
    citations = []
    for game_id in result["source_game_ids"][:5]:
        game = games_by_id.get(game_id)
        if game is None:
            continue
        citations.append(
            {
                "claim": answer,
                "type": "game",
                "title": f"{game.game_date} {game.away_team_id} @ {game.home_team_id}",
                "game_id": game.id,
                "source_name": game.source_name,
                "source_url": game.source_url,
                "metadata": {"result_id": result["id"], "source_game_id": game.source_game_id},
            }
        )
    return AnalyticsAnswer(
        answer=f"Short answer\n{answer}",
        analytics=analytics,
        citations=citations,
        warnings=warnings,
    )
