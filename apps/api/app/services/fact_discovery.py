"""Discover release-scoped facts; models select receipts, never author their claims."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.generated_stat_fact import GeneratedStatFact
from app.models.player import Player
from app.services.conversation_state import ConversationState, state_from_resolved
from app.services.query_resolution import resolve_query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DISCOVERY = re.compile(r"\b(?:interesting|surprising|notable|fun|cool)\b|\bdiscover\b", re.I)
_ANOTHER = re.compile(
    r"^\s*(?:(?:give|show|tell) me )?(?:another(?: one| stat| fact)?|one more)\s*[.!?]*$",
    re.I,
)
_OPENINGS = {
    "here": "Here's one",
    "look": "Take a look at this",
    "another": "Here's another one",
}


def is_discovery(question: str) -> bool:
    return bool(_DISCOVERY.search(question) or _ANOTHER.fullmatch(question))


class StoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str
    opening: Literal["here", "look", "another"]


@dataclass
class DiscoveryAnswer:
    answer: str
    state: ConversationState | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    route: str = "discover_fact"


async def _choose(candidates: list[dict[str, Any]], question: str, another: bool) -> StoryChoice:
    fallback = StoryChoice(
        fact_id=candidates[0]["fact_id"], opening="another" if another else "here"
    )
    return fallback


async def discover_fact(
    db: AsyncSession,
    *,
    question: str,
    season: str,
    prior: ConversationState | None,
    context: list[dict[str, str]],
) -> DiscoveryAnswer:
    release = (
        await db.execute(
            select(DatasetRelease).where(
                DatasetRelease.status == "active",
                DatasetRelease.validation_passed.is_(True),
            )
        )
    ).scalar_one_or_none()
    if release is None:
        return DiscoveryAnswer("I don't have a verified archive available to draw a stat from yet.")
    another = bool(_ANOTHER.fullmatch(question))
    same_release = prior is not None and prior.data_version == release.version
    scope_question = question
    if another:
        if same_release and prior and prior.discovery_question:
            scope_question = prior.discovery_question
        else:
            scope_question = next(
                (
                    item["content"]
                    for item in reversed(context)
                    if item["role"] == "user" and _DISCOVERY.search(item["content"])
                ),
                "Give me an interesting stat",
            )
    mentioned = set(re.findall(r"\b20\d{2}-\d{2}(?!-\d{2})\b", scope_question))
    if season != release.season or (mentioned and mentioned != {release.season}):
        return DiscoveryAnswer(
            f"I have verified stats for the {release.season} archive. "
            "I don't have that requested season available."
        )
    if re.search(
        r"\b(?:injur\w*|trades?|today|tonight|tomorrow|live|current\w*|future)\b",
        scope_question,
        re.I,
    ):
        return DiscoveryAnswer(
            "I don't have live updates. I can find a verified fact from "
            f"the {release.season} Knicks archive."
        )
    if re.search(
        r"\b(?:lakers|warriors|nets|yankees|mets|football|baseball|politics|weather)\b",
        scope_question,
        re.I,
    ) and not re.search(r"\b(?:against|versus|vs)\b", scope_question, re.I):
        return DiscoveryAnswer(
            f"My verified facts cover Knicks games in the {release.season} "
            "archive. I don't have that team's broader season here."
        )
    resolved = await resolve_query(
        db, scope_question, intent="discover_fact", data_version=release.version
    )
    state = state_from_resolved(resolved)
    state.discovery_question = scope_question
    state.seen_fact_ids = list(prior.seen_fact_ids) if same_release and prior else []
    if resolved.requires_clarification:
        return DiscoveryAnswer(
            "Which did you mean? " + "; ".join(resolved.clarification_options),
            state=state,
            route="clarification",
        )
    if resolved.periods:
        return DiscoveryAnswer(
            "I can discover verified full-game box-score facts here. "
            "I don't yet have a discovery pool for that quarter.",
            state=state,
        )
    # Never turn an unrecognized explicit subject into a random Knicks-player fact.
    subject = re.search(r"\babout\s+(.+?)[?.!]*$", scope_question, re.I)
    if (
        subject
        and not resolved.player_ids
        and not re.search(r"\b(?:knicks|nyk|season|archive|team)\b", subject[1], re.I)
    ):
        return DiscoveryAnswer(
            "Which Knicks player did you mean? I couldn't match that name to the archive.",
            state=state,
            route="clarification",
        )
    games = list(
        (
            await db.execute(
                select(Game)
                .where(
                    Game.release_id == release.id,
                    Game.season == season,
                )
                .order_by(Game.game_date, Game.id)
            )
        ).scalars()
    )
    games = [
        g
        for g in games
        if (not resolved.game_ids or g.id in resolved.game_ids)
        and (not resolved.season_type or g.season_type == resolved.season_type)
        and (not resolved.opponent_id or resolved.opponent_id in (g.home_team_id, g.away_team_id))
        and (not resolved.date_start or g.game_date >= resolved.date_start)
        and (not resolved.date_end or g.game_date <= resolved.date_end)
        and (not resolved.home_away or (g.home_team_id == "NYK") == (resolved.home_away == "home"))
    ]
    if resolved.game_result:
        games = [
            g
            for g in games
            if ((g.home_score > g.away_score) == (g.home_team_id == "NYK"))
            == (resolved.game_result == "W")
        ]
    game_map = {g.id: g for g in games}
    rows = (
        await db.execute(
            select(PlayerGameStat, Player)
            .join(Player)
            .where(
                PlayerGameStat.release_id == release.id,
                PlayerGameStat.game_id.in_(game_map),
                PlayerGameStat.team_id == "NYK",
                PlayerGameStat.minutes > 0,
            )
        )
    ).all()
    rows = [
        (stat, player)
        for stat, player in rows
        if not resolved.player_ids or player.id in resolved.player_ids
    ]
    candidates: list[dict[str, Any]] = []
    for stat, player in rows:
        game = game_map[stat.game_id]
        opponent = game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
        identity = f"{release.version}:box:{game.id}:{player.id}"
        candidates.append(
            {
                "fact_id": hashlib.sha256(identity.encode()).hexdigest(),
                "statement": (
                    f"{player.full_name} put up {stat.points} points, "
                    f"{stat.rebounds} rebounds and {stat.assists} assists, "
                    f"with {stat.turnovers} turnovers against {opponent} on {game.game_date}."
                ),
                "source_game_ids": [game.id],
                "player_ids": [player.id],
                "season": season,
                "season_type": game.season_type,
                "date_start": str(game.game_date),
                "date_end": str(game.game_date),
                "data_version": release.version,
                "sample_size": 1,
                "values": {
                    key: getattr(stat, key)
                    for key in (
                        "points",
                        "rebounds",
                        "assists",
                        "turnovers",
                        "steals",
                        "blocks",
                        "three_pointers_made",
                        "plus_minus",
                    )
                },
                "coverage_limit": (
                    "An observed game in the available archive; "
                    "no season or historical ranking claimed."
                ),
                "score": float(getattr(stat, resolved.metric, 0))
                if resolved.metric
                else stat.points + 1.5 * stat.assists + stat.rebounds - stat.turnovers,
            }
        )
        extra_labels = {
            "steals": "steals",
            "blocks": "blocks",
            "three_pointers_made": "made three-pointers",
            "plus_minus": "plus-minus",
        }
        if resolved.metric in extra_labels:
            candidates[-1]["statement"] += (
                f" He finished with {getattr(stat, resolved.metric)} "
                f"{extra_labels[resolved.metric]}."
            )
    # Published catalogs add verified comparisons; only use facts whose entire
    # evidence window is inside the requested scope, never a truncated baseline.
    source_map = {g.nba_game_id: g.id for g in games}
    people = {p.nba_player_id for _, p in rows}
    catalog = (
        await db.execute(
            select(GeneratedStatFact).where(
                GeneratedStatFact.release_id == release.id,
            )
        )
    ).scalars()
    for fact in catalog:
        sources = json.loads(fact.source_game_ids_json)
        if not sources or not set(sources).issubset(source_map):
            continue
        if resolved.player_ids and not set(json.loads(fact.player_ids_json)).intersection(people):
            continue
        if resolved.metric and resolved.metric not in json.loads(fact.stat_keys_json):
            continue
        candidates.append(
            {
                "fact_id": fact.fingerprint,
                "statement": fact.statement,
                "source_game_ids": [source_map[s] for s in sources],
                "data_version": release.version,
                "season": season,
                "timeframe": json.loads(fact.timeframe_json),
                "date_start": str(min(game_map[source_map[s]].game_date for s in sources)),
                "date_end": str(max(game_map[source_map[s]].game_date for s in sources)),
                "season_types": sorted({game_map[source_map[s]].season_type for s in sources}),
                "nba_player_ids": json.loads(fact.player_ids_json),
                "sample_size": fact.sample_size,
                "baseline": json.loads(fact.result_json),
                "coverage_limit": (
                    "Comparison is limited to the available archive and stated qualifiers."
                ),
                "score": 40 * fact.total_score,
            }
        )
    prior_answers = [item["content"] for item in context if item["role"] == "assistant"]
    candidates = [
        fact
        for fact in candidates
        if fact["fact_id"] not in state.seen_fact_ids
        and not any(fact["statement"] in answer for answer in prior_answers)
    ]
    candidates.sort(key=lambda fact: (-fact["score"], fact["fact_id"]))
    if not candidates:
        return DiscoveryAnswer(
            "I don't have another verified fact for that selection yet. "
            "Try a different player or a wider archive window.",
            state=state,
        )
    choice = await _choose(candidates, question, another)
    fact = next(item for item in candidates if item["fact_id"] == choice.fact_id)
    state.seen_fact_ids = [*state.seen_fact_ids, fact["fact_id"]][-200:]
    answer = f"{_OPENINGS[choice.opening]} from the {season} archive: {fact['statement']}"
    if "baseline" in fact:
        answer += " This comparison covers the games available here."
    citations = []
    for game_id in fact["source_game_ids"][:5]:
        game = game_map[game_id]
        citations.append(
            {
                "claim": fact["statement"],
                "type": "game",
                "game_id": game.id,
                "title": f"{game.game_date} {game.away_team_id} @ {game.home_team_id}",
                "source_name": game.source_name,
                "source_url": game.source_url,
                "metadata": {
                    **{k: v for k, v in fact.items() if k != "score"},
                    "source_game_id": game.source_game_id,
                },
            }
        )
    return DiscoveryAnswer(answer, state, citations)
