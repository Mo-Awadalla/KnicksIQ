"""Controlled, release-pinned analytics. Retrieval never supplies a denominator."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from app.core.config import get_settings
from app.evaluation.trace_capture import record_search, record_tool
from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.team import Team
from app.services.analyst_calculations import METRICS
from app.services.analyst_dispatch import execute_call
from app.services.analyst_tool_facts import ToolFactsMixin
from app.services.analyst_tool_registry import capability_data_types
from app.services.archive_retrieval import search_archive_lexical
from app.services.archive_units import build_archive_units
from app.services.canonical_narrative import NarrativeSelection, select_narrative
from app.services.evidence_contracts import (
    PLAYER_METRICS,
    TEAM_METRICS,
    Candidate,
    Evidence,
    ToolCall,
    ToolResult,
    VerifiedClaim,
)
from app.services.game_reference import references_recent_game, resolve_game_reference
from app.services.player_threshold_games import has_unresolved_player_subject
from app.services.query_dates import date_window
from app.services.query_game_scope import (
    InheritedScope,
    is_elliptical_follow_up,
    names_season_scope,
    needs_many_games,
)
from app.services.query_policy import names_phase
from app.services.query_resolution import ResolvedQuery, phrase_names_scope, resolve_query
from app.services.query_text import aggregations_in_text, is_record_request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AnalystTools(ToolFactsMixin):
    def __init__(
        self,
        db: AsyncSession,
        release: DatasetRelease,
        question: str,
        season: str,
        state: dict[str, Any],
        context: list[dict[str, str]] | None = None,
    ):
        self.db, self.release, self.question, self.season = db, release, question, season
        self.state = state
        self.context = context or []
        self.claims: dict[str, VerifiedClaim] = {}
        self.evidence: dict[str, Evidence] = {}
        self.candidates: dict[str, Candidate] = {}
        self.issued_evidence_ids: set[str] = set()
        self.games: list[Game] = []
        self.rows: list[tuple[PlayerGameStat, Player]] = []
        self.scope: ResolvedQuery | None = None
        self.team_names: dict[str, str] = {}
        self.narrative: NarrativeSelection | None = None
        self.discovery: ToolResult | None = None
        self.different = bool(re.search(r"\bdifferent player\b", question, re.I))
        self.topic = question
        # Resolved once the archive games are loaded: the question's own population decides.
        self.followup = False
        self.timings: list[dict[str, Any]] = []

    async def prepare(self) -> None:
        records_started = time.monotonic()
        self.games = list(
            (
                await self.db.execute(
                    select(Game)
                    .where(
                        Game.release_id == self.release.id,
                        Game.season == self.release.season,
                        (Game.home_team_id == "NYK") | (Game.away_team_id == "NYK"),
                    )
                    .order_by(Game.game_date, Game.id)
                )
            ).scalars()
        )
        loaded_rows = list(
            (
                await self.db.execute(
                    select(PlayerGameStat, Player)
                    .join(Player)
                    .where(
                        PlayerGameStat.release_id == self.release.id,
                        PlayerGameStat.game_id.in_([g.id for g in self.games]),
                        PlayerGameStat.team_id == "NYK",
                    )
                )
            ).all()
        )
        self.rows = [(stat, player) for stat, player in loaded_rows]
        self.team_names = {
            team_id: name
            for team_id, name in (await self.db.execute(select(Team.id, Team.name))).all()
        }
        self.timings.append(
            {
                "stage": "prepare",
                "tool": "archive_records",
                "latency_ms": round((time.monotonic() - records_started) * 1000),
                "games": len(self.games),
                "box_score_rows": len(self.rows),
            }
        )
        entry_topic = str(self.state.get("intent") or "")
        entry_scope = self.state.get("scope") or {}
        # A question that names its own population starts a new topic; one that only names a
        # metric, period or player continues the population already under discussion.
        self.followup = is_elliptical_follow_up(self.question, self.games)
        # A declined turn keeps the last accepted topic and scope for the next follow-up.
        declined = bool(self.state.get("declined", False))
        if entry_topic and not declined:
            self.state["last_topic"] = entry_topic
            self.state["last_scope"] = entry_scope
        prior_topic = (
            entry_topic if entry_topic and not declined else str(self.state.get("last_topic") or "")
        )
        prior_scope = (
            entry_scope if entry_scope and not declined else (self.state.get("last_scope") or {})
        )
        previous_release = self.state.get("release")
        previous_intent = self.state.get("intent")
        raw_previous_scope = self.state.get("scope")
        previous_scope = raw_previous_scope if isinstance(raw_previous_scope, dict) else None
        previous_claims: list[VerifiedClaim] = []
        if previous_release == self.release.version:
            for raw in self.state.get("claims", []):
                claim = VerifiedClaim.model_validate(raw)
                if claim.release_id == self.release.version:
                    previous_claims.append(claim)
        leader_query = bool(
            re.search(r"\b(?:who|which player)\b", self.question, re.I)
            and re.search(r"\b(?:lead|led|leading|leader|most|highest|top)\b", self.question, re.I)
        )
        # Main's release freshness: a prior scope is authoritative only for the active
        # release. A retired release still supplies conversation identity at most, never
        # game ids, internals, windows or claims.
        prior_scope_current = not prior_scope or (
            (prior_scope.get("data_version") or previous_release) == self.release.version
        )
        single_game = len(prior_scope.get("game_ids") or []) == 1 or bool(
            prior_scope.get("date_start")
            and prior_scope.get("date_start") == prior_scope.get("date_end")
        )
        if single_game and needs_many_games(self.question):
            self.followup = False
        followup = self.followup and bool(prior_topic or prior_scope)
        prior_aggregations = aggregations_in_text(prior_topic)
        prior_aggregation = next(iter(prior_aggregations)) if len(prior_aggregations) == 1 else None
        if followup and (prior_topic or prior_scope):
            if prior_scope_current:
                inherited = InheritedScope(
                    topic=prior_topic,
                    # A leader question asks a new subject; only the game/window may carry.
                    player_ids=[] if leader_query else (prior_scope.get("player_ids") or []),
                    metric=prior_scope.get("metric"),
                    aggregation=prior_scope.get("aggregation") or prior_aggregation,
                    requested_metrics=prior_scope.get("requested_metrics") or [],
                    requested_aggregations=prior_scope.get("requested_aggregations") or [],
                    season_type=prior_scope.get("season_type"),
                    all_phases=bool(prior_scope.get("all_phases")),
                    home_away=prior_scope.get("home_away"),
                    opponent_id=prior_scope.get("opponent_id"),
                    game_result=prior_scope.get("game_result"),
                    date_start=prior_scope.get("date_start"),
                    date_end=prior_scope.get("date_end"),
                    relative_game_count=prior_scope.get("relative_game_count"),
                    relative_from_start=bool(prior_scope.get("relative_from_start")),
                    relative_game_order=prior_scope.get("relative_game_order") or "last",
                    game_ids=prior_scope.get("game_ids") or [],
                    periods=prior_scope.get("periods") or [],
                )
            else:
                # Retired releases keep the named conversation identity only. Their game
                # ids, windows, opponent/phase and claims are not authoritative now.
                inherited = InheritedScope(
                    topic=prior_topic,
                    player_ids=[] if leader_query else (prior_scope.get("player_ids") or []),
                )
        else:
            inherited = None
        resolve_started = time.monotonic()
        # Resolving with the inherited scope as the default, rather than patching keys
        # afterwards, keeps the phase, window and game ids in one consistent population.
        self.scope = await resolve_query(
            self.db,
            self.question,
            intent="analyst",
            data_version=self.release.version,
            default_season_type=(inherited.season_type if inherited is not None else None),
            default_all_phases=inherited.all_phases if inherited is not None else False,
            inherit=inherited,
            select_extrema=False,
        )
        self.timings.append(
            {
                "stage": "prepare",
                "tool": "query_resolution",
                "latency_ms": round((time.monotonic() - resolve_started) * 1000),
                "resolved": bool(
                    self.scope.player_ids
                    or self.scope.team_ids
                    or self.scope.game_ids
                    or self.scope.date_start
                    or self.scope.date_end
                    or self.scope.relative_game_count
                    or self.scope.periods
                    or self.scope.metric
                ),
            }
        )
        # Always apply main's release-scoped reference resolver: InheritedScope restores
        # deictic scope, while this enforces topic changes and retired-release freshness.
        reference_scope = self.scope
        question_names_window = (
            date_window(
                self.question,
                self.games,
                self.games[-1].game_date if self.games else None,
            ).explicit
            or names_phase(self.question)
            or names_season_scope(self.question)
        )
        if (
            inherited is not None
            and not question_names_window
            and references_recent_game(self.question)
        ):
            # The inherited window is not evidence that this turn names one. Clear it so
            # the resolver checks the conversation anchor and release freshness first.
            reference_scope = self.scope.model_copy(
                update={
                    "date_start": None,
                    "date_end": None,
                    "relative_game_count": None,
                    "relative_from_start": False,
                    "game_ids": [],
                }
            )
        self.scope = resolve_game_reference(
            self.question,
            reference_scope,
            self.context,
            self.games,
            delivered_claims=previous_claims,
            prior_intent=previous_intent,
            prior_scope=previous_scope,
        )
        if (
            self.scope.date_start
            and self.scope.date_end
            and (self.scope.date_start != self.scope.date_end)
            and re.search(r"\b(between|from|through|until)\b", self.question, re.I)
        ):
            self.scope = self.scope.model_copy(update={"game_ids": []})
        if (
            followup
            and prior_scope_current
            and not leader_query
            and not self.scope.requires_clarification
        ):
            # Main's follow-up patch, kept alongside InheritedScope: fields the merged
            # resolver did not restore from the accepted turn fall back to its scope.
            prior = previous_scope or {}
            prior_query = ResolvedQuery.model_validate({**self.scope.model_dump(), **prior})
            updates = {}
            for key in ("player_ids", "season_type", "opponent_id", "home_away", "game_result"):
                if key == "player_ids" and not re.search(
                    r"\b(?:he|him|his)\b|^\s*(?:and|what about)\b|\bthat\b", self.question, re.I
                ):
                    continue
                if key == "game_result" and is_record_request(self.question):
                    continue
                if not getattr(self.scope, key) and prior.get(key):
                    updates[key] = prior[key]
            names_window = bool(
                self.scope.date_start
                or self.scope.date_end
                or self.scope.relative_game_count
                or self.scope.calendar_boundary
                or re.search(r"\b(?:season|overall|playoffs?|postseason)\b", self.question, re.I)
            )
            if not names_window:
                for key in (
                    "date_start",
                    "date_end",
                    "calendar_boundary",
                    "relative_game_count",
                    "relative_game_order",
                ):
                    updates[key] = getattr(prior_query, key)
                if (
                    not self.scope.game_ids
                    and not self.scope.team_ids
                    and not self.scope.home_away
                    and not self.scope.game_result
                ):
                    updates["game_ids"] = prior_query.game_ids
            if not self.scope.requested_metrics and not is_record_request(self.question):
                updates["metric"] = prior_query.metric
                updates["requested_metrics"] = prior_query.requested_metrics
            if not self.scope.requested_aggregations:
                updates["requested_aggregations"] = prior_query.requested_aggregations
            if self.different:
                updates["player_ids"] = []
            self.scope = self.scope.model_copy(update=updates)
        if (
            not self.scope.player_ids or not (self.scope.metric or self.scope.requested_metrics)
        ) and (
            not self.scope.requires_clarification
            or self.scope.clarification_reason == "ambiguous_game"
        ):
            selection = select_narrative(self.question, self.selected_games(self.scope))
            if selection:
                if not self.scope.player_ids:
                    self.narrative = selection
                self.scope = self.scope.model_copy(
                    update={
                        "game_ids": [g.id for g in selection.games],
                        "requires_clarification": False,
                        "clarification_reason": None,
                        "clarification_options": [],
                    }
                )
        if self.different:
            self.scope = self.scope.model_copy(update={"player_ids": []})
        unknown_subject = re.search(r"\babout\s+(.+?)[?.!]*$", self.question, re.I)
        if (
            unknown_subject
            and not self.scope.player_ids
            and not self.scope.team_ids
            and not self.different
            and not re.search(
                r"\b(knicks|nyk|season|archive|team|playoff|game)\b", unknown_subject[1], re.I
            )
            and not await phrase_names_scope(self.db, unknown_subject[1], self.release.version)
        ):
            self.scope = self.scope.model_copy(
                update={
                    "requires_clarification": True,
                    "clarification_options": sorted({p.full_name for _, p in self.rows}),
                }
            )
        if re.search(r"\b(he|him|his)\b", self.question, re.I) and not self.scope.player_ids:
            self.scope = self.scope.model_copy(
                update={
                    "requires_clarification": True,
                    "clarification_options": sorted({p.full_name for _, p in self.rows}),
                }
            )
        if (
            not self.scope.player_ids
            and has_unresolved_player_subject(self.question)
            and not self.scope.requires_clarification
        ):
            self.scope = self.scope.model_copy(
                update={
                    "requires_clarification": True,
                    "clarification_reason": "unknown_player",
                    "clarification_options": sorted({p.full_name for _, p in self.rows}),
                }
            )
        if leader_query or self.scope.requires_clarification:
            self.state["claims"] = []
            self.state["evidence"] = []
        self.state["scope"] = self.scope.model_dump(mode="json")
        self.state["scope_origin"] = "user" if not followup else "verified_followup"
        # An elliptical follow-up moves phase, window, site, opponent or game reference
        # without naming a subject, metric or new answer kind: it continues the topic.
        elliptical = bool(
            inherited is not None and inherited.continues_topic(self.question, self.scope)
        )
        self.topic = (
            inherited.topic if elliptical and inherited is not None and inherited.topic else None
        ) or self.question
        self.state["intent"] = self.topic[:1200]
        if not entry_topic:
            self.state["last_topic"] = self.topic
            self.state["last_scope"] = self.state["scope"]
        # Immutable release references are revalidated for identity and integrity at admission.
        if (
            previous_release == self.release.version
            and not leader_query
            and not self.scope.requires_clarification
        ):
            permitted_games = {g.id for g in self.selected_games(self.scope)}
            for claim in previous_claims:
                if (
                    claim.release_id == self.release.version
                    and set(claim.game_ids or []) <= permitted_games
                    # A one-phase claim is a subset of every phase but does not answer it;
                    # carried over, it also suppresses the prefetch that would.
                    and not (self.scope.all_phases and claim.season_type is not None)
                    and (
                        not self.scope.player_ids
                        or claim.subject_id in {f"player:{pid}" for pid in self.scope.player_ids}
                    )
                    and not self.different
                    and not re.search(r"\b(another|one more)\b", self.question, re.I)
                ):
                    self.claims[claim.claim_id] = claim
            for raw in self.state.get("evidence", []):
                item = Evidence.model_validate(raw)
                if item.release_id == self.release.version:
                    self.evidence[item.evidence_id] = item
                    self.issued_evidence_ids.add(item.evidence_id)
        elif previous_release != self.release.version:
            self.state["delivered_fact_ids"] = []
        self.state["release"] = self.release.version

    def manifest(self) -> dict[str, Any]:
        return {
            "release_id": self.release.version,
            "seasons": [self.release.season],
            "season_types": sorted({g.season_type for g in self.games}),
            "data_types": list(capability_data_types()),
            "date_range": {
                "first_game_date": str(self.games[0].game_date),
                "last_game_date": str(self.games[-1].game_date),
            }
            if self.games
            else {},
            "metrics": list(PLAYER_METRICS),
            "team_metrics": list(TEAM_METRICS),
            "games": len(self.games),
            "box_score_rows": len(self.rows),
            "known_gaps": [
                "No live injuries, trades or current updates.",
                "Archive coverage is not necessarily the complete NBA season.",
                "Box scores do not establish causation or overall playing quality.",
            ],
            "scope": self.scope.model_dump(mode="json") if self.scope else {},
        }

    def team_label(self, team_id: str) -> str:
        """The archive's display name for a team id, so prose never prints SAS."""
        return self.team_names.get(team_id, team_id)

    def selected_games(self, scope: ResolvedQuery) -> list[Game]:
        games = [
            g
            for g in self.games
            if (not scope.game_ids or g.id in scope.game_ids)
            and (not scope.season_type or g.season_type == scope.season_type)
            and (not scope.date_start or g.game_date >= scope.date_start)
            and (not scope.date_end or g.game_date <= scope.date_end)
            and (not scope.opponent_id or scope.opponent_id in (g.home_team_id, g.away_team_id))
            and (not scope.home_away or (g.home_team_id == "NYK") == (scope.home_away == "home"))
        ]
        if scope.game_result:
            games = [
                g
                for g in games
                if (self.score(g)[0] > self.score(g)[1]) == (scope.game_result == "W")
            ]
        return games

    @staticmethod
    def score(game: Game) -> tuple[int, int]:
        return (
            (game.home_score, game.away_score)
            if game.home_team_id == "NYK"
            else (game.away_score, game.home_score)
        )

    def receipt(
        self,
        game: Game,
        stat: PlayerGameStat | TeamGameStat | PeriodScore | None = None,
        player: Player | None = None,
    ) -> Evidence:
        identity = f"{self.release.version}:game:{game.id}"
        if isinstance(stat, PlayerGameStat) and player is not None:
            identity += f":player:{player.id}"
        elif isinstance(stat, TeamGameStat):
            identity += f":team_box:{stat.team_id}"
        elif isinstance(stat, PeriodScore):
            identity += f":period:{stat.team_id}:{stat.period}"
        if identity in self.evidence:
            return self.evidence[identity]
        data: dict[str, Any] = {
            "date": str(game.game_date),
            "season_type": game.season_type,
            "home": game.home_team_id,
            "away": game.away_team_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
        }
        if isinstance(stat, PlayerGameStat) and player is not None:
            data.update(
                subject_id=f"player:{player.id}",
                player=player.full_name,
                **{m: getattr(stat, m) for m in METRICS},
            )
            data.update(
                three_pointers_attempted=stat.three_pointers_attempted, starter=stat.starter
            )
        elif isinstance(stat, TeamGameStat):
            data.update(
                canonical_source_id=f"team_box:{game.nba_game_id}:{stat.team_id}",
                **{
                    key: getattr(stat, key)
                    for key in ("turnovers", "field_goals_made", "field_goals_attempted")
                },
            )
        elif isinstance(stat, PeriodScore):
            data.update(
                canonical_source_id=f"period:{game.nba_game_id}:{stat.team_id}:{stat.period}",
                period=stat.period,
                points=stat.points,
            )
        evidence = Evidence(
            evidence_id=identity,
            release_id=self.release.version,
            game_id=game.id,
            text=json.dumps(data, sort_keys=True),
            source_name=game.source_name,
            source_url=game.source_url,
            metadata=data,
        )
        self.evidence[identity] = evidence
        return evidence

    def claim(
        self,
        *,
        subject: str,
        metric: str,
        value: Any,
        unit: str,
        games: list[Game],
        evidence: list[Evidence],
        statement: str,
        scope: ResolvedQuery,
        sample: int,
        denominator: float | int | None,
        baseline: list[str] | None = None,
        limitations: list[str] | None = None,
        eligibility: dict[str, Any] | None = None,
        window: dict[str, Any] | None = None,
        population: str = "available release archive",
    ) -> VerifiedClaim:
        requested = scope.requested_window(
            relative_unit="appearances" if scope.player_ids else "games"
        )
        if requested and (window is None or set(window) <= {"date_start", "date_end", "periods"}):
            window = {**(window or {}), "requested": requested}
        if len(evidence) > 3:
            import hashlib

            source_ids = list(dict.fromkeys(e.evidence_id for e in evidence))
            identity = (
                "calculation:"
                + hashlib.sha256(
                    json.dumps(
                        [self.release.version, subject, metric, source_ids, value], sort_keys=True
                    ).encode()
                ).hexdigest()
            )
            receipt = Evidence(
                evidence_id=identity,
                release_id=self.release.version,
                text=statement,
                metadata={
                    "source_evidence_ids": source_ids,
                    "calculation_version": "analyst-v1",
                    "sample_size": sample,
                    "denominator": denominator,
                },
            )
            self.evidence[identity] = receipt
            evidence = [receipt]
        claim = VerifiedClaim.create(
            subject_id=subject,
            metric_id=metric,
            value=value,
            unit=unit,
            metric_definition_version="box-score-v1",
            population=population,
            filters={
                key: value
                for key, value in scope.model_dump(mode="json").items()
                if key in ("opponent_id", "home_away", "game_result", "periods")
            },
            season=self.release.season,
            season_type=next(iter({g.season_type for g in games}))
            if len({g.season_type for g in games}) == 1
            else None,
            game_ids=[g.id for g in games],
            window=window,
            sample_size=sample,
            denominator=denominator,
            baseline_claim_ids=baseline or [],
            calculation_version="analyst-v1",
            release_id=self.release.version,
            supporting_evidence_ids=[e.evidence_id for e in evidence],
            coverage_limitations=limitations or ["Available archive only; no causal inference."],
            eligibility=eligibility or {"appearance": "minutes > 0"},
            statement=statement,
        )
        self.claims[claim.claim_id] = claim
        return claim

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            if self.narrative and call.name in {
                "get_team_stats",
                "discover_facts",
                "get_game_narrative",
            }:
                from app.services.analyst_tool_narrative import run as run_narrative

                result = await run_narrative(
                    self,
                    call,
                    self.scope,
                    self.selected_games(self.scope) if self.scope is not None else [],
                )
            else:
                result = await execute_call(self, call)
            self.claims.update({c.claim_id: c for c in result.claims})
            for item in result.evidence:
                self.evidence[item.evidence_id] = item
                self.issued_evidence_ids.add(item.evidence_id)
                self.issued_evidence_ids.update(item.metadata.get("source_evidence_ids", []))
            self.issued_evidence_ids.update(
                ref for c in result.claims for ref in c.supporting_evidence_ids
            )
            if call.name == "discover_facts":
                self.discovery = result
            record_tool(
                {"call": call.model_dump(mode="json"), "result": result.model_dump(mode="json")}
            )
            return result
        except Exception as exc:
            # Do not disclose provider/database errors or turn failure into absence.
            result = ToolResult(
                status="dependency_failure",
                message=f"{call.name} unavailable",
                scope={"error_type": type(exc).__name__},
            )
            record_tool(
                {"call": call.model_dump(mode="json"), "result": result.model_dump(mode="json")}
            )
            return result

    async def search_archive_lexical(self, *args: Any, **kwargs: Any) -> Any:
        """Indirection so tests and callers can substitute the lexical search boundary."""
        return await search_archive_lexical(*args, **kwargs)

    async def canonical_discovery(self) -> ToolResult:
        """Search local records before admission without changing authoritative scope."""
        if self.discovery is not None:
            return self.discovery
        if self.scope is None:
            raise ValueError("Canonical discovery requires prepared request scope")
        scope = self.scope
        if scope.clarification_reason == "missing_conversation_game":
            self.discovery = ToolResult(
                status="ambiguous_entity",
                message="Which archived game date should I use?",
                choices=scope.clarification_options,
                scope=scope.model_dump(mode="json"),
            )
            return self.discovery
        games = self.selected_games(scope) if self.season == self.release.season else []
        names = sorted({p.full_name for _, p in self.rows if p.id in scope.player_ids})[:3]
        teams = {scope.opponent_id} if scope.opponent_id else set()
        anchors = names + sorted(teams)
        expansion = " OR ".join(json.dumps(value) for value in anchors)
        # Tool questions retain their existing cap. Only ordinary independently
        # resolved identities expand the user's bounded search query.
        query = self.question[: max(0, 1200 - len(expansion) - 4)]
        query += " OR " + expansion if expansion else ""
        try:
            # Integrity preparation shares the configured investigation budget;
            # the short lexical deadline must not truncate full SQL verification.
            async with asyncio.timeout(get_settings().analyst_investigation_seconds):
                unit_records = (
                    await build_archive_units(self.db, games, self.release.version) if games else []
                )
            async with asyncio.timeout(4):
                from app.services.analyst_tool_archive import run as search_archive

                self.discovery = await search_archive(
                    self,
                    ToolCall(name="search_archive", question=query),
                    scope,
                    games,
                    unit_records=unit_records,
                    local_only=True,
                    purpose="canonical_discovery",
                )
        except Exception as exc:
            record_search(
                {
                    "purpose": "canonical_discovery",
                    "status": "dependency_failure",
                    "release": self.release.version,
                    "question": self.question,
                    "query": query,
                    "filters": {**scope.planner_filters(), "game_ids": [g.id for g in games]},
                    "candidate_evidence_ids": [],
                    "returned_evidence_ids": [],
                    "lexical_evidence_ids": [],
                    "dense_evidence_ids": [],
                    "evidence": [],
                    "dense_failed": False,
                    "error_type": type(exc).__name__,
                }
            )
            self.discovery = ToolResult(
                status="dependency_failure",
                message="Local archive discovery is unavailable on this turn.",
            )
        for item in self.discovery.evidence:
            self.evidence[item.evidence_id] = item
            self.issued_evidence_ids.add(item.evidence_id)
        return self.discovery
