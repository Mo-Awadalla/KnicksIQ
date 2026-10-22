"""Controlled, release-pinned analytics. Retrieval never supplies a denominator."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.models.team import Team
from app.services.analyst_calculations import METRICS
from app.services.analyst_dispatch import execute_call
from app.services.analyst_tool_registry import capability_data_types
from app.services.evidence_contracts import Candidate, Evidence, ToolCall, ToolResult, VerifiedClaim
from app.services.query_game_scope import (
    InheritedScope,
    is_elliptical_follow_up,
    needs_many_games,
)
from app.services.query_resolution import ResolvedQuery, phrase_names_scope, resolve_query
from app.services.query_text import aggregation_of
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AnalystTools:
    def __init__(
        self,
        db: AsyncSession,
        release: DatasetRelease,
        question: str,
        season: str,
        state: dict[str, Any],
    ):
        self.db, self.release, self.question, self.season = db, release, question, season
        self.state = state
        self.claims: dict[str, VerifiedClaim] = {}
        self.evidence: dict[str, Evidence] = {}
        self.candidates: dict[str, Candidate] = {}
        self.issued_evidence_ids: set[str] = set()
        self.games: list[Game] = []
        self.rows: list[tuple[PlayerGameStat, Player]] = []
        self.scope: ResolvedQuery | None = None
        self.aggregation: str | None = None
        self.team_names: dict[str, str] = {}
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
        single_game = len(prior_scope.get("game_ids") or []) == 1 or bool(
            prior_scope.get("date_start")
            and prior_scope.get("date_start") == prior_scope.get("date_end")
        )
        if single_game and needs_many_games(self.question):
            self.followup = False
        followup = self.followup and bool(prior_topic or prior_scope)
        inherited = (
            InheritedScope(
                topic=prior_topic,
                player_ids=prior_scope.get("player_ids") or [],
                metric=prior_scope.get("metric"),
                aggregation=aggregation_of(prior_topic),
                season_type=prior_scope.get("season_type"),
                all_phases=bool(prior_scope.get("all_phases")),
                home_away=prior_scope.get("home_away"),
                opponent_id=prior_scope.get("opponent_id"),
                game_result=prior_scope.get("game_result"),
                date_start=prior_scope.get("date_start"),
                date_end=prior_scope.get("date_end"),
                relative_game_count=prior_scope.get("relative_game_count"),
                relative_from_start=bool(prior_scope.get("relative_from_start")),
                game_ids=prior_scope.get("game_ids") or [],
                periods=prior_scope.get("periods") or [],
            )
            if followup and (prior_topic or prior_scope)
            else None
        )
        self.aggregation = aggregation_of(self.question) or (
            inherited.aggregation if inherited else None
        )
        resolve_started = time.monotonic()
        # Resolving with the inherited scope as the default, rather than patching keys
        # afterwards, keeps the phase, window and game ids in one consistent population.
        self.scope = await resolve_query(
            self.db,
            self.question,
            intent="analyst",
            data_version=self.release.version,
            default_season_type=(inherited.season_type if inherited is not None else "regular"),
            default_all_phases=inherited.all_phases if inherited is not None else False,
            inherit=inherited,
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
        if (
            self.scope.date_start
            and self.scope.date_end
            and (self.scope.date_start != self.scope.date_end)
            and re.search(r"\b(between|from|through|until)\b", self.question, re.I)
        ):
            self.scope = self.scope.model_copy(update={"game_ids": []})
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
        if self.state.get("release") == self.release.version:
            permitted_games = {g.id for g in self.selected_games(self.scope)}
            for raw in self.state.get("claims", []):
                claim = VerifiedClaim.model_validate(raw)
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
        else:
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
            "metrics": list(METRICS),
            "team_metrics": ["wins", "losses", "points", "margin"],
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
        self, game: Game, stat: PlayerGameStat | None = None, player: Player | None = None
    ) -> Evidence:
        identity = f"{self.release.version}:game:{game.id}"
        if stat is not None and player is not None:
            identity += f":player:{player.id}"
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
        if stat is not None and player is not None:
            data.update(
                subject_id=f"player:{player.id}",
                player=player.full_name,
                **{m: getattr(stat, m) for m in METRICS},
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
            result = await execute_call(self, call)
            for item in result.evidence:
                self.evidence[item.evidence_id] = item
                self.issued_evidence_ids.add(item.evidence_id)
                self.issued_evidence_ids.update(item.metadata.get("source_evidence_ids", []))
            self.issued_evidence_ids.update(
                ref for c in result.claims for ref in c.supporting_evidence_ids
            )
            return result
        except Exception as exc:
            # Do not disclose provider/database errors or turn failure into absence.
            return ToolResult(
                status="dependency_failure",
                message=f"{call.name} unavailable",
                scope={"error_type": type(exc).__name__},
            )
