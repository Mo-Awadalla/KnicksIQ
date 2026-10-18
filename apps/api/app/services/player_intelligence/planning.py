"""Deterministic player analytics plan and timeframe parsing."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from app.models.player import Player
from app.services.player_intelligence.identity import (
    _asks_opponent_plus_minus_leader,
    _asks_player_summary,
    _asks_starts,
    _game_selector,
)
from app.services.team_aliases import team_ids_in_text
from basketball_core.analytics import (
    AnalyticsOperation,
    AnalyticsPlan,
    OutputType,
    ResolvedPlayer,
    Timeframe,
)
from basketball_core.analytics.registry import stat_keys_in_text

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
    if re.search(r"\bregular[- ]season\b", q):
        return Timeframe(kind="regular_season", label="2025-26 regular season"), filters
    return Timeframe(kind="full_archive", label="full 2025-26 archive"), filters


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
    if (
        resolved
        and timeframe.kind == "last_n"
        and not re.search(r"\b(?:archive|team|knicks) games\b|\bknicks['’]? last\b", q)
    ):
        timeframe = timeframe.model_copy(
            update={"unit": "appearances", "label": f"last {timeframe.last_n} appearances"}
        )
    opponent_plus_minus_leader = _asks_opponent_plus_minus_leader(text)
    stats = stat_keys_in_text(text)
    if opponent_plus_minus_leader:
        stats = ["plus_minus"]
    elif "use true shooting percentage" in q:
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
    if "rebounding" in q and "rebounds" not in stats:
        stats.insert(0, "rebounds")
    has_explicit_stats = bool(stats)
    if not stats:
        stats = ["points", "rebounds", "assists"] if _asks_player_summary(q) else ["points"]
    game_selector = _game_selector(q)
    if game_selector:
        filters["game_selector"] = game_selector

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
    if opponent_plus_minus_leader:
        operation = AnalyticsOperation.LEADERBOARD
        output = OutputType.TABLE
    elif any(term in q for term in ("notable", "surprising", "interesting", "discover")):
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
    elif (
        len(resolved) == 1
        and "compare" in q
        and (
            ("before" in q and "after" in q and re.search(r"all[- ]star", q))
            or (_parse_last_count(q) and "season" in q)
        )
    ):
        operation = AnalyticsOperation.PERIOD_COMPARISON
        output = OutputType.COMPARISON
        filters["comparison_window"] = (
            "all_star" if re.search(r"all[- ]star", q) else "last_n_vs_season"
        )
        if filters["comparison_window"] == "all_star":
            timeframe = Timeframe(kind="full_archive", label="full 2025-26 archive")
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
    opponents = team_ids_in_text(text) - {"NYK"}
    if len(opponents) == 1:
        filters["opponent"] = next(iter(opponents))
    if opponent_plus_minus_leader:
        filters["player_scope"] = "opponents"

    asks_average = any(term in q for term in ("average", "averaged", "per game", "per appearance"))
    asks_total = bool(
        "total" in q
        or re.search(
            r"\bhow many\s+(?:points?|rebounds?|assists?|steals?|blocks?|double|triple)", q
        )
        or re.search(r"\bmost\s+(?:points?|rebounds?|assists?|steals?|blocks?)\b", q)
        or (operation == AnalyticsOperation.LEADERBOARD and not asks_average)
    )
    if opponent_plus_minus_leader:
        aggregation_mode = "total"
    elif asks_average and asks_total:
        aggregation_mode = "both"
    elif asks_total:
        aggregation_mode = "total"
    else:
        aggregation_mode = "average"

    if _asks_starts(text):
        stats = ["starts"]
        aggregation_mode = "total"

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
