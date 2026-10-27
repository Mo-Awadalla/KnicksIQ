"""Game, document, and possession receipts for narrative answers."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analysis_policy as runtime
from app.api.analysis_generation import _generate_grounded_answer
from app.api.analysis_models import AnalysisCitation, AnalysisQueryRequest, AnalysisQueryResponse
from app.api.analysis_policy import _retrieval_limitation_note, _unknown_data_question
from app.api.analysis_presenters import _format_answer, _possession_evidence_note, _score_line
from app.api.analysis_retrieval import _matching_games, _schedule_shadow
from app.models.dataset_release import DatasetRelease
from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.archive_retrieval import (
    ArchiveEvidence,
)
from app.services.canonical_narrative import build_narrative, select_narrative
from app.services.possession_chunks import chunk_evidence
from app.services.query_classifier import QueryClassifierResult, classify_query
from app.services.rag import search_possession_chunks, search_season_docs
from app.services.releases import restrict_to_active_release
from app.services.retrieval_planner import (
    deterministic_retrieval_plan,
)
from app.services.team_scope import scores


async def answer_narrative_query(
    req: AnalysisQueryRequest,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    settings: Any,
    question: str,
    effective_question: str,
    response_metadata: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    classifier: QueryClassifierResult,
    classifier_payload: dict[str, Any],
    route: str,
    answer_mode: str,
    archive_vector_evidence: list[ArchiveEvidence],
    selected_narrative_game: Game | None,
) -> AnalysisQueryResponse:
    warnings: list[str] = []
    t0 = time.perf_counter()
    games = await _matching_games(db, effective_question, req.season)
    if len(games) == 1 and not re.search(r"\b20\d{2}-\d{2}-\d{2}\b", effective_question):
        effective_question = f"{effective_question} on {games[0].game_date}"
    tool_calls.append(
        {
            "tool": "get_games",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(games),
        }
    )

    t0 = time.perf_counter()
    docs = await search_season_docs(db, effective_question, season=req.season, limit=3)
    matching_game_ids = {game.id for game in games}
    if matching_game_ids:
        docs = [doc for doc in docs if int(doc.metadata.get("game_id") or -1) in matching_game_ids]
    tool_calls.append(
        {
            "tool": "search_season_docs",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(docs),
        }
    )

    t0 = time.perf_counter()
    retrieval_trace: list[dict[str, Any]] = []
    possession_chunks, retrieval_filters = await search_possession_chunks(
        db,
        effective_question,
        season=req.season,
        limit=getattr(settings, "rag_retrieval_limit", 5),
        trace=retrieval_trace,
    )
    possession_evidence = [chunk_evidence(chunk) for chunk in possession_chunks]
    if retrieval_filters.periods or retrieval_filters.last_minutes is not None:
        # Whole-game summaries cannot serve as receipts for a narrower event window.
        docs = []
    tool_calls.extend(retrieval_trace)
    tool_calls.append(
        {
            "tool": "search_possession_chunks",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "result_count": len(possession_chunks),
            "filters": retrieval_filters.as_dict(),
        }
    )

    citations: list[AnalysisCitation] = []
    lines: list[str] = []
    for game in games[:3]:
        lines.append(_score_line(game))
        citations.append(
            AnalysisCitation(
                claim=_score_line(game),
                type="game",
                title=f"{game.game_date} {game.away_team_id} @ {game.home_team_id}",
                game_id=game.id,
                source_name=game.source_name,
                source_url=game.source_url,
                metadata={
                    "data_status": game.data_status,
                    "season_type": game.season_type,
                    "source_game_id": game.source_game_id,
                },
            )
        )

    event_ready_game_ids = {g.id for g in games if g.data_status != "summary_only"}
    if event_ready_game_ids and any(
        term in question.lower() for term in ("run", "stretch", "play", "quarter")
    ):
        event_count = (
            (
                await db.execute(
                    select(GameEvent).where(GameEvent.game_id.in_(event_ready_game_ids)).limit(5)
                )
            )
            .scalars()
            .all()
        )
        if event_count:
            lines.append(
                "Event-level play-by-play is available for "
                f"{len(event_ready_game_ids)} matching game(s)."
            )

    for doc in docs:
        citations.append(
            AnalysisCitation(
                claim=doc.text[:240],
                type="document",
                title=doc.title,
                game_id=doc.metadata.get("game_id"),
                source_name=doc.metadata.get("source_name"),
                source_url=doc.metadata.get("source_url"),
                metadata=doc.metadata,
            )
        )

    for evidence_item in possession_evidence[:3]:
        first_description = next(
            (str(row["description"]) for row in evidence_item["rows"] if row.get("description")),
            "Possession-level play-by-play evidence",
        )
        citations.append(
            AnalysisCitation(
                claim=first_description,
                type="possession",
                title=(
                    f"{evidence_item['date']} "
                    f"Q{evidence_item['period_window'][0]} "
                    f"{evidence_item['clock_window'][0]}-{evidence_item['clock_window'][1]}"
                ),
                game_id=evidence_item["game_id"],
                metadata={
                    "possession_id": evidence_item["possession_id"],
                    "players": evidence_item["players"],
                    "teams": evidence_item["teams"],
                    "row_count": len(evidence_item["rows"]),
                },
            )
        )

    if classifier.kind == "counterfactual":
        warnings.append(
            "Counterfactual answer is bounded to the available historical baseline plus a "
            "labeled hypothetical adjustment."
        )
    if not possession_evidence:
        warnings.append("No possession-level evidence matched the available season data.")

    if _unknown_data_question(question):
        lines = [
            "I can only answer from the games currently in KnicksIQ, and that question "
            "does not identify an available game."
        ]
    elif not lines:
        lines.append(
            "I could not find an available Knicks game matching that question in "
            "the selected season."
        )

    fallback_answer = " ".join(lines)
    grounded_evidence = {
        item.evidence_id: item.text for item in archive_vector_evidence if item.text
    }
    grounded_evidence.update(
        {
            f"game:{game.id}": json.dumps(
                {
                    "summary": _score_line(game),
                    "date": str(game.game_date),
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                },
                sort_keys=True,
            )
            for game in games[:5]
        }
    )
    grounded_evidence.update({f"document:{doc.chunk_id}": doc.text for doc in docs[:5] if doc.text})
    grounded_evidence.update(
        {
            f"possession:{item['possession_id']}": json.dumps(item, sort_keys=True)
            for item in possession_evidence[:5]
        }
    )
    answer = None
    if answer_mode == "llm_primary" and not response_metadata["degraded"]:
        answer = await _generate_grounded_answer(
            question=question,
            season=req.season,
            evidence=grounded_evidence,
            chat_context=req.context,
            evidence_metadata={
                **{
                    item.evidence_id: {
                        "reviewed_report": item.collection == "reports",
                        "connected_sequence": item.collection == "possessions",
                    }
                    for item in archive_vector_evidence
                },
                **{
                    f"possession:{item['possession_id']}": {
                        "connected_sequence": len(item.get("sequence_ids", [])) > 1
                    }
                    for item in possession_evidence[:5]
                },
            },
        )
    elif answer_mode == "shadow":
        _schedule_shadow(
            background_tasks,
            settings=settings,
            request_id=response_metadata["request_id"],
            question=effective_question,
            season=req.season,
            data_version=response_metadata["data_version"],
            fallback_plan=deterministic_retrieval_plan(
                effective_question,
                intent=classifier.kind,
                is_aggregative=False,
            ),
            evidence=grounded_evidence,
        )
    if answer:
        tool_calls.append(
            {
                "tool": "llm_generate",
                "estimated_cost_usd": 0.01,
                "model": runtime.get_settings().ai_chat_model,
                "latency_ms": 0,
            }
        )

    limitation_note = None
    retrieval_limitation = _retrieval_limitation_note(question)
    if retrieval_limitation:
        warnings.append(retrieval_limitation)
        limitation_note = retrieval_limitation
    elif warnings:
        limitation_note = " ".join(warnings)
    elif not answer and not possession_evidence:
        limitation_note = (
            "The available Knicks game data was not detailed enough to support a more "
            "specific answer."
        )

    retrieval_metadata = {
        **response_metadata,
        "degraded": response_metadata["degraded"]
        or (answer_mode == "llm_primary" and answer is None),
    }
    response = AnalysisQueryResponse(
        **retrieval_metadata,
        answer=(
            (
                answer
                if answer_mode == "llm_primary" or "Receipts" in answer or not possession_evidence
                else answer + _possession_evidence_note(possession_evidence)
            )
            if answer
            else _format_answer(
                direct_answer=fallback_answer,
                evidence_note=_possession_evidence_note(possession_evidence),
                limitation_note=limitation_note,
            )
        ),
        route=route,
        classifier=classifier_payload,
        evidence=possession_evidence,
        warnings=warnings,
        citations=citations,
        tool_calls=tool_calls,
    )
    if selected_narrative_game is not None:
        response.answer = (
            "Using fewest points allowed as the measure of best defensive game, "
            f"the Knicks allowed {scores(selected_narrative_game)[1]} points "
            f"on {selected_narrative_game.game_date}. "
            "This identifies the lowest opponent score; the selected play receipts alone "
            f"do not establish why the defense succeeded.\n\n{response.answer}"
        )
    return response


async def _deterministic_lead_narrative_response(
    db: AsyncSession,
    question: str,
    *,
    season: str,
    game_id: int | None,
    response_metadata: dict[str, Any],
) -> AnalysisQueryResponse:
    def clarification(message: str) -> AnalysisQueryResponse:
        return AnalysisQueryResponse(
            **response_metadata,
            answer=_format_answer(direct_answer=message),
            route="clarification",
            classifier=classify_query(question).as_dict(),
            evidence=[],
            warnings=["unverified_game_condition"],
            citations=[],
            tool_calls=[{"tool": "get_game_narrative", "result_count": 0}],
        )

    if game_id is None:
        return clarification(
            "I cannot verify the requested lead-change condition from the selected game. "
            "Which archived game date should I use?"
        )
    game_stmt = restrict_to_active_release(
        select(Game).where(Game.id == game_id, Game.season == season)
    )
    game = (await db.execute(game_stmt)).scalar_one_or_none()
    if game is None:
        return clarification(
            "I cannot verify the selected game's lead-change condition from the active archive. "
            "Which archived game date should I use?"
        )
    release = await db.get(DatasetRelease, game.release_id)
    if release is None or release.season != season:
        return clarification(
            "I cannot verify the selected game's lead-change condition from the active archive. "
            "Which archived game date should I use?"
        )
    selection = select_narrative(question, [game])
    if selection is None or selection.kind != "lead_changes":
        return clarification(
            "I cannot verify the requested lead change from this game's canonical score sequence."
        )
    result = await build_narrative(db, release, selection)
    if result.status != "ok" or len(result.claims) != 1:
        return clarification(
            result.message
            or "I cannot verify the requested lead change from this game's score sequence."
        )
    claim = result.claims[0]
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    citations = []
    for evidence_id in claim.supporting_evidence_ids[:3]:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            return clarification(
                "I cannot verify the requested lead change from this game's score sequence."
            )
        citations.append(
            AnalysisCitation(
                claim=claim.statement,
                type="verified_claim",
                title=claim.statement,
                game_id=evidence.game_id,
                source_name=evidence.source_name,
                source_url=evidence.source_url,
                metadata={
                    "claim": claim.model_dump(mode="json"),
                    "evidence_id": evidence_id,
                },
            )
        )
    if not citations:
        return clarification(
            "I cannot verify the requested lead change from this game's score sequence."
        )
    return AnalysisQueryResponse(
        **response_metadata,
        answer=_format_answer(
            direct_answer=claim.statement,
            limitation_note=(
                "The archive contains the verified scoreboard sequence, but does not "
                "establish the cause or mechanism of the lead change."
            ),
        ),
        route="retrieval_rag",
        classifier=classify_query(question).as_dict(),
        evidence=[item.model_dump(mode="json") for item in result.evidence],
        warnings=[],
        citations=citations,
        tool_calls=[{"tool": "get_game_narrative", "result_count": len(result.claims)}],
    )
