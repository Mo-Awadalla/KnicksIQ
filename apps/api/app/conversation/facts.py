from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.conversation.event_window import event_window
from app.conversation.publication import PublishedClaim
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.dataset_release import DatasetRelease
from app.services.analyst_citations import collection, priority, requested_sources
from app.services.analyst_dispatch import season_matches
from app.services.analyst_player_stats import METRICS
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import Evidence, ToolCall, ToolResult, VerifiedClaim
from app.services.query_operations import RANKING_OPERATIONS, normalize_text
from app.services.query_players import _player_aliases
from app.services.team_aliases import TEAM_ALIASES
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_QUESTION_CHARS = 300
MAX_FACTS_PER_LOOKUP = 8
MAX_NARRATIVE_FACTS = 3
MAX_NARRATIVE_CHARS = 280
PERSISTED_STATE_KEYS = ("scope", "scope_origin", "release")
UNAVAILABLE = {"status": "unavailable", "message": "Exact season data is unavailable right now."}

_FACT_ASK = re.compile(
    r"\b(?:how many|how much|score[ds]?|scoring|final|points?|pts|rebounds?|boards|assists?|"
    r"steals?|blocks?|turnovers?|minutes|threes|three[- ]pointers?|shooting|shot|percent(?:age)?|"
    r"field goals?|free throws?|plus[- ]minus|record|averag\w*|stats?|stat ?line|box score|"
    r"play[- ]by[- ]play|possessions?|recaps?|what happened|who (?:led|won|scored)|beat|lost to|"
    r"margin|won by|lost by|wins?|losses|streak)\b",
    re.IGNORECASE,
)
_NARRATIVE = re.compile(
    r"\b(?:play[- ]by[- ]play|possessions?|recaps?|reports?|what happened|describe|explain|"
    r"walk me through|tell the story|moment|sequence|comeback|clutch|late in|"
    r"final (?:minute|seconds?))\b",
    re.IGNORECASE,
)
_DISCOVERY = re.compile(
    r"\b(?:interesting|surprising|notable|fun|another|different player)\b", re.IGNORECASE
)
_STATUS = {
    "ok": "found",
    "incomplete_coverage": "found",
    "ambiguous_entity": "ambiguous",
    "no_matching_results": "not_found",
    "unsupported_metric_or_scope": "unsupported",
    "dependency_failure": "unavailable",
}

logger = get_logger("knicksiq.conversation.facts")


def wants_facts(message: str) -> bool:
    return _FACT_ASK.search(message) is not None


def _bounded(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit - 1)
    return text[: cut if cut > 0 else limit - 1] + "\u2026"


class FactDesk:
    def __init__(self, season: str, state: dict[str, Any], evidence_budget: int, request_id: str):
        self.season = season
        self.request_id = request_id
        self.state = {key: state[key] for key in PERSISTED_STATE_KEYS if key in state}
        self.budget = evidence_budget
        self.facts: dict[str, PublishedClaim] = {}
        self.lexicon: dict[str, frozenset[str]] = {}
        self._team_aliases()
        self._references: dict[tuple[str, str], str] = {}
        self.lookups = 0
        self._session: AsyncSession | None = None
        self._release: DatasetRelease | None = None

    def persisted_state(self) -> dict[str, Any]:
        return {key: self.state[key] for key in PERSISTED_STATE_KEYS if key in self.state}

    async def close(self) -> None:
        if self._session is not None:
            session, self._session = self._session, None
            await session.close()

    async def _open(self) -> tuple[AsyncSession, DatasetRelease | None]:
        if self._session is None:
            self._session = AsyncSessionLocal()
        if self._release is None:
            self._release = (
                await self._session.execute(
                    select(DatasetRelease).where(
                        DatasetRelease.status == "active",
                        DatasetRelease.validation_passed.is_(True),
                    )
                )
            ).scalar_one_or_none()
        return self._session, self._release

    def _alias(self, alias: str, identity: str) -> None:
        normalized = normalize_text(alias)
        if normalized:
            self.lexicon[normalized] = self.lexicon.get(normalized, frozenset()) | {identity}

    def _team_aliases(self) -> None:
        path = Path(__file__).resolve().parents[1] / "core" / "seed" / "teams.json"
        for team in json.loads(path.read_text(encoding="utf-8")):
            identity = f"team:{team['id']}"
            for alias in (
                team["id"],
                team["abbreviation"],
                team["name"],
                team["city"],
                f"{team['city']} {team['name']}",
            ):
                self._alias(alias, identity)
        for alias, team_id in TEAM_ALIASES.items():
            self._alias(alias, f"team:{team_id}")

    def _register(self, claim: PublishedClaim) -> str | None:
        key = (claim.text, claim.authority)
        existing = self._references.get(key)
        if existing is not None:
            return existing
        cost = len(claim.text.encode())
        if cost > self.budget:
            return None
        self.budget -= cost
        ref = f"f{len(self.facts) + 1}"
        self.facts[ref] = claim
        self._references[key] = ref
        return ref

    async def lookup(self, question: str) -> dict[str, Any]:
        question = " ".join(question.split())[:MAX_QUESTION_CHARS]
        if not question:
            return {"status": "error", "error": "invalid arguments: a question is required"}
        self.lookups += 1
        try:
            session, release = await self._open()
            if release is None:
                return UNAVAILABLE
            tools = AnalystTools(session, release, question, self.season, self.state)
            await tools.prepare()
            players = {player.id: player for _, player in tools.rows}
            for player in players.values():
                for alias in _player_aliases(player):
                    self._alias(alias, f"player:{player.id}")
            result = await lookup_result(tools, request_id=self.request_id)
            self.state = {
                key: tools.state[key] for key in PERSISTED_STATE_KEYS if key in tools.state
            }
            return self._outcome(tools, result)
        except Exception as exc:
            logger.warning("conversation.lookup_failed", error_type=type(exc).__name__)
            await self.close()
            self._release = None
            return UNAVAILABLE

    @staticmethod
    def _call(tools: AnalystTools, question: str) -> ToolCall:
        scope = tools.scope
        sources = requested_sources(question)
        season_summary = (
            scope is not None
            and not scope.requires_clarification
            and scope.operation is None
            and not scope.player_ids
            and not scope.periods
            and not scope.game_ids
            and re.search(r"\bseason\b", question, re.I) is not None
            and re.search(r"\b(?:what happened|summari[sz]e|season summary)\b", question, re.I)
            is not None
        )
        if sources or (_NARRATIVE.search(question) and not season_summary):
            return ToolCall(name="search_archive", question=question)
        if _DISCOVERY.search(question):
            return ToolCall(name="discover_facts", question=question)
        if scope is not None and scope.player_ids and scope.comparison is None:
            return ToolCall(name="get_player_stats", question=question)
        return ToolCall(name="get_team_stats", question=question, aggregation="total")

    def _outcome(self, tools: AnalystTools, result: ToolResult) -> dict[str, Any]:
        status = _STATUS[result.status]
        event_window = any(claim.metric_id == "event_window" for claim in result.claims)
        numeric = [
            self._project(tools, claim)
            for claim in result.claims
            if claim.metric_id != "event_window"
        ]
        narrative = [
            item
            for item in result.evidence
            if collection(item) in {"reports", "possessions"}
            and (not event_window or isinstance(item.metadata.get("event_sequence"), int))
        ]
        reserved_count = 0
        coverage_note = ""
        if event_window:
            total_events = len(narrative)
            complete_events = [item for item in narrative if len(item.text) <= MAX_NARRATIVE_CHARS]
            window = result.scope.get("event_window", {}) if result.scope else {}
            selection = window.get("selection") if isinstance(window, dict) else None
            if selection == "last":
                narrative = complete_events[-MAX_NARRATIVE_FACTS:]
                direction = "final"
            else:
                narrative = complete_events[:MAX_NARRATIVE_FACTS]
                direction = "first"
            omitted = total_events - len(narrative)
            if omitted:
                coverage_note = (
                    f"Only the {direction} {len(narrative)} complete plays are checked; "
                    f"{omitted} other matching events are not shown."
                )
            if not narrative and total_events:
                coverage_note = (
                    "The matching play is too long to include as one complete checked event."
                )
        else:
            reserved = priority(tools.question, narrative)
            narrative = reserved + [item for item in narrative if item not in reserved]
            reserved_count = min(len(reserved), len(narrative))
            narrative = narrative[:MAX_NARRATIVE_FACTS]
        descriptions = [
            self._evidence_claim(tools, item, event_atom=event_window) for item in narrative
        ]
        slots = MAX_FACTS_PER_LOOKUP - len(descriptions)
        if event_window:
            statements = descriptions + numeric[:slots]
        else:
            statements = (
                descriptions[:reserved_count] + numeric[:slots] + descriptions[reserved_count:]
            )
        facts = []
        for claim in statements:
            ref = self._register(claim)
            if ref is None:
                break
            facts.append({"ref": ref, "text": claim.text})
        if status == "found" and facts:
            body: dict[str, Any] = {"status": "found", "facts": facts}
            messages = [coverage_note] if coverage_note else []
            if result.status == "incomplete_coverage":
                messages.append(_bounded(result.message, 200))
            if messages:
                body["message"] = " ".join(messages)[:200]
            return body
        if status == "found":
            status = "limit" if statements or (event_window and narrative == []) else "not_found"
        return_body: dict[str, Any] = {
            "status": status,
            "message": _bounded(coverage_note or result.message, 200),
        }
        if result.choices:
            return_body["choices"] = [_bounded(choice, 60) for choice in result.choices[:8]]
        return return_body

    @staticmethod
    def _game_entities(tools: AnalystTools, game_ids: frozenset[int]) -> frozenset[str]:
        return frozenset(
            f"team:{team}"
            for game in tools.games
            if game.id in game_ids
            for team in (game.away_team_id, game.home_team_id)
        )

    def _project(self, tools: AnalystTools, claim: VerifiedClaim) -> PublishedClaim:
        game_ids = frozenset(claim.game_ids or ())
        metric, separator, aggregation = claim.metric_id.partition(":")
        one_game_average = (
            aggregation == "average"
            and len(game_ids) == 1
            and claim.sample_size == claim.denominator == 1
            and tools.scope is not None
            and {game.id for game in tools.considered_games(tools.scope)} == game_ids
        )
        value = None
        if (
            claim.subject_id is not None
            and claim.subject_id.startswith("player:")
            and len(game_ids) == 1
            and separator
            and (aggregation in {"game", "total"} or one_game_average)
            and metric in METRICS
            and not any(
                value
                for key, value in claim.filters.items()
                if key not in {"opponent_id", "home_away", "game_result"}
            )
            and isinstance(claim.value, (int, float, str))
            and not isinstance(claim.value, bool)
        ):
            try:
                candidate = Decimal(str(claim.value))
                if candidate.is_finite():
                    value = candidate
            except InvalidOperation:
                pass
        return PublishedClaim(
            authority=claim.claim_id,
            text=self._statement(tools, claim),
            subject=claim.subject_id,
            value=value,
            metric=metric if value is not None else None,
            game_ids=game_ids,
            game_entities=self._game_entities(tools, game_ids),
        )

    def _evidence_claim(
        self, tools: AnalystTools, item: Evidence, *, event_atom: bool = False
    ) -> PublishedClaim:
        game_ids = frozenset({item.game_id}) if item.game_id is not None else frozenset()
        player_id = item.metadata.get("player_id")
        return PublishedClaim(
            authority=item.evidence_id,
            text=(
                item.text
                if event_atom and isinstance(item.metadata.get("event_sequence"), int)
                else self._narrative(tools, item.text, item.game_id)
            ),
            subject=f"player:{player_id}" if isinstance(player_id, int) else None,
            game_ids=game_ids,
            game_entities=self._game_entities(tools, game_ids),
        )

    def _statement(self, tools: AnalystTools, claim: VerifiedClaim) -> str:
        statement = _bounded(claim.statement, 400)
        ids = set(claim.game_ids or [])
        games = sorted(
            (game for game in tools.games if game.id in ids),
            key=lambda game: (game.game_date, game.id),
        )
        if len(games) != len(ids):
            raise ValueError("Claim game is outside the resolved release")
        game = games[0] if len(games) == 1 else None
        game_bound = (
            game is not None
            and str(game.game_date) in statement
            and all(
                re.search(rf"\b{re.escape(team)}\b", statement)
                for team in (game.away_team_id, game.home_team_id)
            )
        )
        context = []
        if not game_bound:
            if claim.season not in statement:
                context.append(claim.season)
            phase = claim.season_type or "all season phases"
            if phase.casefold() not in statement.casefold():
                context.append(phase)
        if game is not None:
            if not game_bound:
                context.append(f"{game.game_date}, {game.away_team_id} at {game.home_team_id}")
        elif games:
            opponents = sorted(
                {
                    game.away_team_id if game.home_team_id == "NYK" else game.home_team_id
                    for game in games
                }
            )
            opponents_label = (
                ", ".join(opponents) if len(opponents) <= 3 else f"{len(opponents)} opponents"
            )
            context.append(f"{len(games)} games against {opponents_label}")
            context.append(f"{games[0].game_date} to {games[-1].game_date}")
        for key, labels in (
            ("home_away", {"home": "home games", "away": "away games"}),
            ("game_result", {"win": "wins", "loss": "losses"}),
        ):
            value = claim.filters.get(key)
            if value in labels:
                context.append(labels[value])
        periods = claim.filters.get("periods")
        if periods:
            context.append("periods " + ", ".join(str(period) for period in periods))
        window = claim.window or {}
        for position in ("first", "last"):
            count = window.get(f"{position}_n")
            if count is not None:
                basis = window.get("basis", "games").replace("_", " ")
                context.append(f"{position} {count} {basis}")
        if window.get("all_star_break") in {"before", "after"}:
            context.append(f"{window['all_star_break']} the All-Star break")
        return f"{statement.rstrip('.')} ({'; '.join(context)})." if context else statement

    def _narrative(self, tools: AnalystTools, text: str, game_id: int | None) -> str:
        game = next((item for item in tools.games if item.id == game_id), None)
        where = (
            f"the {game.game_date} {game.away_team_id} at {game.home_team_id} game"
            if game is not None
            else f"a {tools.release.season} game"
        )
        return f"From {where}: {_bounded(text, MAX_NARRATIVE_CHARS)}"


async def lookup_result(tools: AnalystTools, *, request_id: str) -> ToolResult:
    tools.request_id = request_id
    result = await event_window(tools)
    if result is None:
        call = FactDesk._call(tools, tools.question)
        scope = tools.scope
        assert scope is not None
        if (
            call.name != "search_archive"
            or scope.requires_clarification
            or scope.operation_reason
            or not season_matches(tools)
        ):
            return await tools.execute(call)
        selection = None
        if scope.operation in RANKING_OPERATIONS:
            selection = await tools.execute(
                ToolCall(name="get_team_stats", question=tools.question, aggregation="total")
            )
            if selection.status != "ok" or not selection.claims:
                return selection
            selected_ids = {
                game_id for claim in selection.claims for game_id in (claim.game_ids or [])
            }
            games = [game for game in tools.games if game.id in selected_ids]
        else:
            games = tools.selected_games(scope)
        if not games:
            return ToolResult(
                status="no_matching_results",
                message="No archived games match this narrative scope; "
                "missing evidence is not absence.",
            )
        try:
            result = await tools.search(
                call,
                scope,
                games,
                collections=requested_sources(tools.question)
                or frozenset({"reports", "possessions"}),
            )
        except Exception as exc:
            result = ToolResult(
                status="dependency_failure",
                message="Narrative evidence is temporarily unavailable.",
                scope={"error_type": type(exc).__name__},
            )
        if selection is not None:
            result = result.model_copy(
                update={
                    "claims": selection.claims,
                    "evidence": selection.evidence + result.evidence,
                    "status": result.status if result.evidence else "incomplete_coverage",
                    "message": (
                        f"{selection.message} {result.message}"
                        if result.evidence
                        else f"{selection.message} No narrative explanation is available. "
                        f"{result.message}"
                    ),
                }
            )
    for item in result.evidence:
        tools.evidence[item.evidence_id] = item
        tools.issued_evidence_ids.add(item.evidence_id)
        tools.issued_evidence_ids.update(item.metadata.get("source_evidence_ids", []))
    return result
