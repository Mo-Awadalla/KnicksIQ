"""Verified player box-score games that meet a per-game stat threshold."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from app.services.evidence_contracts import Evidence, ToolResult
from app.services.team_aliases import team_ids_in_text
from basketball_core.analytics import (
    STAT_REGISTRY,
    StatThreshold,
    aggregate_rows,
    parse_stat_threshold,
)

if TYPE_CHECKING:
    from app.services.analyst_tools import AnalystTools


def _row_evidence(
    tools: AnalystTools, threshold: StatThreshold, stat: Any, player: Any, game: Any
) -> Evidence:
    data = {
        "date": str(game.game_date),
        "season_type": game.season_type,
        "home": game.home_team_id,
        "away": game.away_team_id,
        "home_score": game.home_score,
        "away_score": game.away_score,
        "subject_id": f"player:{player.id}",
        "player": player.full_name,
        "metric_id": threshold.stat,
        **{column: getattr(stat, column) for column in STAT_REGISTRY[threshold.stat].columns},
    }
    return Evidence(
        evidence_id=(
            f"{tools.release.version}:game:{game.id}:player:{player.id}:threshold:{threshold.stat}"
        ),
        release_id=tools.release.version,
        game_id=game.id,
        text=json.dumps(data, sort_keys=True),
        source_name=game.source_name,
        source_url=game.source_url,
        metadata=data,
    )


_SUPPORTED = {
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "threes_made",
}
_LISTING = re.compile(r"\b(which|list|show|when)\b|\bwhat games\b", re.I)
_COUNT = re.compile(r"\b(how many|count|number of)\b", re.I)
_NAME = re.compile(r"\b(?:[A-Z][A-Za-z'-]*)(?:\s+[A-Z][A-Za-z'-]*){0,2}\b")
_PLAYER_SUBJECT = re.compile(
    r"\b(?:did|does|do|has|have|had)\s+(?P<subject>.+?)\s+"
    r"(?:score|scores|scored|scoring|have|has|had|make|makes|made|grab|grabs|grabbed|"
    r"get|gets|got|record|records|recorded|post|posts|posted|hit|hits)\b",
    re.I,
)
_STOP = {
    "how",
    "many",
    "games",
    "which",
    "score",
    "scored",
    "points",
    "point",
    "did",
    "the",
    "knicks",
}


def is_player_threshold_question(question: str) -> bool:
    threshold = parse_stat_threshold(question)
    return bool(
        threshold
        and threshold.stat in _SUPPORTED
        and re.search(r"\b(games?|times|occasions)\b", question, re.I)
        and not re.search(r"\b(per game|per appearance|average|averaged)\b", question, re.I)
    )


def has_unresolved_player_subject(question: str) -> bool:
    if not is_player_threshold_question(question):
        return False
    if any(
        any(word.lower() not in _STOP for word in match.group().split())
        and not re.search(r"\b(knicks|new york|opponents?)\b", match.group(), re.I)
        for match in _NAME.finditer(question)
    ):
        return True
    subject = _PLAYER_SUBJECT.search(question)
    return bool(subject and not team_ids_in_text(subject["subject"]))


def wants_game_listing(question: str) -> bool:
    return bool(_LISTING.search(question) and not _COUNT.search(question))


def threshold_call(tools: AnalystTools) -> ToolResult:
    """Build count and matching-game claims from the full scoped player rows."""
    assert tools.scope is not None
    threshold = parse_stat_threshold(tools.question)
    if threshold is None or threshold.stat not in _SUPPORTED:
        return ToolResult(
            status="unsupported_metric_or_scope",
            message="Specify a supported per-game stat threshold.",
        )
    scope = tools.scope
    game_map = {game.id: game for game in tools.selected_games(scope)}
    claims = []
    evidence = []
    for player_id in scope.player_ids:
        rows = sorted(
            [
                (stat, player)
                for stat, player in tools.rows
                if stat.player_id == player_id and stat.game_id in game_map and stat.minutes > 0
            ],
            key=lambda row: (
                game_map[row[0].game_id].game_date,
                game_map[row[0].game_id].nba_game_id,
            ),
        )
        if scope.relative_game_count:
            rows = (
                rows[: scope.relative_game_count]
                if scope.relative_game_order == "first"
                else rows[-scope.relative_game_count :]
            )
        if not rows:
            continue
        matched = [
            (stat, player)
            for stat, player in rows
            if threshold.meets(
                {column: getattr(stat, column) for column in STAT_REGISTRY[threshold.stat].columns}
            )
        ]
        receipts = [
            _row_evidence(tools, threshold, stat, player, game_map[stat.game_id])
            for stat, player in matched
        ]
        evidence.extend(receipts)
        games = [game_map[stat.game_id] for stat, _ in rows]
        name = rows[0][1].full_name
        predicate = {
            "metric_id": threshold.stat,
            "operator": threshold.symbol,
            "cutoff": threshold.value,
        }
        count_statement = (
            f"{name} had {len(matched)} games with {threshold.description} across "
            f"{len(rows)} observed appearances in {tools.scope_label(scope, games)}."
        )
        calculation_id = hashlib.sha256(
            f"{tools.release.version}:{player_id}:{predicate}:"
            f"{[game.id for game in games]}".encode()
        ).hexdigest()
        count_evidence = Evidence(
            evidence_id=f"calculation:threshold:{calculation_id}",
            release_id=tools.release.version,
            text=count_statement,
            metadata={
                "calculation_version": "player-threshold-v1",
                "subject_id": f"player:{player_id}",
                "stat_predicate": predicate,
                "sample_size": len(rows),
                "matching_game_ids": [stat.game_id for stat, _ in matched],
                "box_score_rows": [receipt.metadata for receipt in receipts],
            },
        )
        evidence.append(count_evidence)
        claims.append(
            tools.claim(
                subject=f"player:{player_id}",
                metric="games:count",
                value=len(matched),
                unit="games",
                games=[game_map[stat.game_id] for stat, _ in matched],
                evidence=[count_evidence],
                statement=count_statement,
                scope=scope,
                sample=len(rows),
                denominator=None,
                eligibility={
                    "appearance": "minutes > 0",
                    "stat_predicate": predicate,
                    "matching_game_ids": [stat.game_id for stat, _ in matched],
                    "population_game_count": len(rows),
                },
            )
        )
        if wants_game_listing(tools.question):
            for stat, _player in matched:
                game = game_map[stat.game_id]
                opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
                value = aggregate_rows([stat], [threshold.stat])[threshold.stat]
                claims.append(
                    tools.claim(
                        subject=f"player:{player_id}",
                        metric=f"{threshold.stat}:total",
                        value=value,
                        unit=STAT_REGISTRY[threshold.stat].label.lower(),
                        games=[game],
                        evidence=[count_evidence],
                        statement=(
                            f"{name} recorded {value:g} "
                            f"{STAT_REGISTRY[threshold.stat].label.lower()} "
                            f"on {game.game_date} against {opponent}."
                        ),
                        scope=scope,
                        sample=1,
                        denominator=None,
                        eligibility={"stat_predicate": predicate, "appearance": "minutes > 0"},
                        window={"date_start": str(game.game_date), "date_end": str(game.game_date)},
                    )
                )
    if not claims:
        return ToolResult(
            status="no_matching_results",
            message="No observed player appearances exist in this scope.",
            scope=scope.model_dump(mode="json"),
        )
    return ToolResult(
        status="ok",
        message=f"Counted every observed appearance against {threshold.description}.",
        claims=claims,
        evidence=evidence,
        scope=scope.model_dump(mode="json"),
    )
