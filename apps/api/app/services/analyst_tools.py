"""Controlled, release-pinned analytics. Retrieval never supplies a denominator."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from app.core.config import get_settings
from app.models.box_score import PlayerGameStat
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.player import Player
from app.services.analyst_calculations import METRICS
from app.services.analyst_dispatch import execute_call
from app.services.analyst_tool_registry import capability_data_types
from app.services.archive_retrieval import (
    fuse_archive_evidence,
    search_archive_lexical,
    search_archive_vectors,
)
from app.services.evidence_contracts import Candidate, Evidence, ToolCall, ToolResult, VerifiedClaim
from app.services.query_policy import names_phase
from app.services.query_resolution import ResolvedQuery, is_record_request, resolve_query
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
        self.different = bool(re.search(r"\bdifferent player\b", question, re.I))
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
        self.timings.append(
            {
                "stage": "prepare",
                "tool": "archive_records",
                "latency_ms": round((time.monotonic() - records_started) * 1000),
                "games": len(self.games),
                "box_score_rows": len(self.rows),
            }
        )
        resolve_started = time.monotonic()
        self.scope = await resolve_query(
            self.db, self.question, intent="analyst", data_version=self.release.version
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
        prior = self.state.get("scope", {})
        followup = bool(
            re.search(
                r"\b(he|him|his|that|another|different player)\b|^\s*(why|now|and|what about)",
                self.question,
                re.I,
            )
        )
        if followup:
            updates = {}
            named_phase = names_phase(self.question)
            for key in ("player_ids", "season_type", "opponent_id", "home_away", "game_result"):
                if key == "game_result" and is_record_request(self.question):
                    continue
                if key == "season_type":
                    # Matchup questions span every phase, and a follow-up keeps the phase
                    # under discussion unless it names one.
                    if self.scope.opponent_id and not named_phase:
                        continue
                    if prior.get("season_type") and not named_phase:
                        updates[key] = prior["season_type"]
                        continue
                if not getattr(self.scope, key) and prior.get(key):
                    updates[key] = prior[key]
            if self.different:
                updates["player_ids"] = []
            self.scope = self.scope.model_copy(update=updates)
        unknown_subject = re.search(r"\babout\s+(.+?)[?.!]*$", self.question, re.I)
        if (
            unknown_subject
            and not self.scope.player_ids
            and not self.different
            and not re.search(
                r"\b(knicks|nyk|season|archive|team|playoff|game)\b", unknown_subject[1], re.I
            )
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
        self.state["intent"] = self.question[:1200]
        # Immutable release references are revalidated for identity and integrity at admission.
        if self.state.get("release") == self.release.version:
            permitted_games = {g.id for g in self.selected_games(self.scope)}
            for raw in self.state.get("claims", []):
                claim = VerifiedClaim.model_validate(raw)
                if (
                    claim.release_id == self.release.version
                    and set(claim.game_ids or []) <= permitted_games
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

    async def search(self, call: ToolCall, scope: ResolvedQuery, games: list[Game]) -> ToolResult:
        filters = scope.planner_filters()
        filters["game_ids"] = [g.id for g in games]
        lexical = await search_archive_lexical(
            self.db,
            query=call.question,
            collections=["games", "box_scores", "reports", "possessions"],
            filters=filters,
            data_version=self.release.version,
            limit=20,
        )
        dense, failure = [], False
        if get_settings().rag_qdrant_enabled:
            try:
                dense = await asyncio.to_thread(
                    search_archive_vectors,
                    queries=[call.question],
                    collections=["games", "box_scores", "reports", "possessions"],
                    filters=filters,
                    data_version=self.release.version,
                    limit=20,
                    candidate_limit=20,
                )
            except Exception:
                failure = True
        found = fuse_archive_evidence(lexical, dense, limit=20)
        evidence = [
            Evidence(
                evidence_id=f"{self.release.version}:{e.evidence_id}",
                release_id=self.release.version,
                text=e.text,
                game_id=e.metadata.get("game_id"),
                source_name=e.metadata.get("source_name"),
                source_url=e.metadata.get("source_url"),
                metadata=e.metadata,
            )
            for e in found
            if e.metadata.get("data_version") == self.release.version
            and e.metadata.get("game_id") in {g.id for g in games}
        ]
        return ToolResult(
            status=("incomplete_coverage" if failure else "ok")
            if evidence
            else ("dependency_failure" if failure else "no_matching_results"),
            message="Retrieved examples only, never a season denominator. "
            + ("Vector retrieval unavailable." if failure else ""),
            evidence=evidence,
            scope={"release": self.release.version, **filters},
        )
