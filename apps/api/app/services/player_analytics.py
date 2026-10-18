"""Release-scoped, deterministic player intelligence orchestration."""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.services.analytics_planner import maybe_refine_analytics_plan
from app.services.pattern_facts import generate_pattern_facts
from app.services.player_intelligence.archive import (
    _archive_players,
    _coverage,
    _games_and_rows,
    _release_id,
    _select_window,
    _validate_requested_window,
)
from app.services.player_intelligence.discovery import (
    _facts_result,
    _outcome_result,
    _outlier_result,
    _precomputed_facts_result,
    _streak_result,
    _trend_result,
)
from app.services.player_intelligence.identity import (
    _DISCOVERY_TERMS,
    _UNSUPPORTED_CONCEPTS,
    _ambiguity,
    _asks_availability,
    _clarification,
    _fold_question,
    _is_clarification_selection,
    _is_player_intelligence,
    _name_like_slots,
    _resolve_players,
)
from app.services.player_intelligence.planning import (
    _ALL_MONTH_NAMES,
    _MONTHS,
    _has_explicit_timeframe,
    _parse_plan,
    _timeframe,
    _window_limitation,
)
from app.services.player_intelligence.presentation import (
    AnalyticsAnswer,
    _answer_text,
    _consumer_plan,
    _limited_answer,
    validate_analytics_evidence,
)
from app.services.player_intelligence.tables import (
    _aggregate_result,
    _comparison_result,
    _game_log_result,
    _leaderboard_result,
    _period_result,
    _split_result,
)
from basketball_core.analytics import (
    STAT_REGISTRY,
    AnalyticsOperation,
    AnalyticsPlan,
    Timeframe,
)
from sqlalchemy.ext.asyncio import AsyncSession


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


async def answer_player_question(
    db: AsyncSession,
    *,
    question: str,
    season: str,
    context: list[dict[str, str]] | None = None,
    resolved_player_ids: list[int] | None = None,
    resolved_game_ids: list[int] | None = None,
) -> AnalyticsAnswer | None:
    """Return typed analytics when the question is in the player-intelligence domain."""
    release_id = await _release_id(db)
    players = await _archive_players(db, release_id)
    context = context or []
    combined, substantive_question = _fold_question(question, context)
    # Normalize a known connective typo before resolving an opponent; player names
    # remain subject to the existing exact/curated/ambiguity-aware resolver.
    combined = re.sub(r"\baginst\b", "against", combined, flags=re.IGNORECASE)
    substantive_question = re.sub(
        r"\baginst\b", "against", substantive_question, flags=re.IGNORECASE
    )
    resolved, ambiguous_players = _resolve_players(combined, players)
    if not resolved and resolved_player_ids:
        resolved = [player for player in players if player.id in set(resolved_player_ids)]
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
    planning_text = (
        combined
        if clarification_selection
        else re.sub(r"\baginst\b", "against", question, flags=re.IGNORECASE)
    )
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
    if plan.filters.get("game_selector") and len(selected_games) > 1:
        return _limited_answer(
            combined,
            "Several archive games tie for that winning margin. Specify a game date.",
            plan=plan,
        )
    if plan.filters.get("game_selector") and len(selected_games) == 1:
        game = selected_games[0]
        own = game.home_score if game.home_team_id == "NYK" else game.away_score
        other = game.away_score if game.home_team_id == "NYK" else game.home_score
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        plan = plan.model_copy(
            update={
                "timeframe": Timeframe(
                    kind="date_range",
                    start_date=game.game_date.isoformat(),
                    end_date=game.game_date.isoformat(),
                    label=f"{game.game_date} NYK {own}-{other} {opponent}",
                )
            }
        )
    if resolved_game_ids:
        allowed_game_ids = set(resolved_game_ids)
        selected_games = [game for game in selected_games if game.id in allowed_game_ids]
        rows = [row for row in rows if row["game_id"] in allowed_game_ids]
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
    if (
        getattr(get_settings(), "player_pattern_facts_enabled", False)
        and len(plan.resolved_players) == 1
        and plan.stats
    ):
        result["pattern_facts"] = [
            fact.model_dump(mode="json")
            for fact in generate_pattern_facts(
                rows,
                player_id=plan.resolved_players[0].player_id,
                metric=plan.stats[0],
                threshold=plan.threshold,
            )
        ]
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
