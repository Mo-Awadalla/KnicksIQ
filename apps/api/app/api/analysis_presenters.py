"""Evidence context and deterministic answer formatting."""

from __future__ import annotations

from typing import Any

from app.api.analysis_models import AnalysisContextMessage
from app.models.game import Game
from app.services.query_classifier import QueryClassifierResult
from app.services.rag import SearchResult


def _score_line(game: Game) -> str:
    opponent = game.home_team_id if game.away_team_id == "NYK" else game.away_team_id
    knicks_score = game.away_score if game.away_team_id == "NYK" else game.home_score
    opponent_score = game.home_score if game.away_team_id == "NYK" else game.away_score
    result = "beat" if knicks_score > opponent_score else "lost to"
    return f"On {game.game_date}, the Knicks {result} {opponent} {knicks_score}-{opponent_score}."


def _analysis_context(
    *,
    question: str,
    season: str,
    games: list[Game],
    docs: list[SearchResult],
    evidence: list[dict[str, Any]] | None = None,
    classifier: QueryClassifierResult | None = None,
    chat_context: list[AnalysisContextMessage] | None = None,
    computed_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "season": season,
        "classifier": classifier.as_dict() if classifier else {},
        "chat_context": [
            {"role": item.role, "content": item.content}
            for item in (chat_context or [])[-10:]
            if item.role in {"user", "assistant"}
        ],
        "games": [
            {
                "game_id": game.id,
                "date": str(game.game_date),
                "home_team_id": game.home_team_id,
                "away_team_id": game.away_team_id,
                "home_score": game.home_score,
                "away_score": game.away_score,
                "season_type": game.season_type,
                "data_status": game.data_status,
                "summary": _score_line(game),
            }
            for game in games[:5]
        ],
        "documents": [
            {
                "title": doc.title,
                "text": doc.text,
                "metadata": doc.metadata,
            }
            for doc in docs[:3]
        ],
        "evidence": evidence or [],
        "computed_facts": computed_facts or {},
    }


def _table_evidence_note(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    examples = ", ".join(
        f"{item['date']} vs {item['opponent']} ({item['score']['NYK']}-"
        f"{item['score'][item['opponent']]})"
        for item in evidence[:3]
    )
    suffix = f"; {len(evidence) - 3} more" if len(evidence) > 3 else ""
    return f"\n\nKey evidence\n- {len(evidence)} available Knicks game(s): {examples}{suffix}."


def _possession_evidence_note(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""
    notes: list[str] = []
    for item in evidence[:3]:
        first_row = next(
            (row for row in item.get("rows", []) if row.get("description")),
            None,
        )
        description = f" - {first_row['description']}" if first_row else ""
        notes.append(
            f"{item['date']} Q{item['period_window'][0]} "
            f"{item['clock_window'][0]}-{item['clock_window'][1]}{description}"
        )
    return "\n\nReceipts\n" + "\n".join(f"- {note}" for note in notes)


def _format_answer(
    *,
    direct_answer: str,
    evidence_note: str = "",
    limitation_note: str | None = None,
) -> str:
    sections = [f"Short answer\n{direct_answer.strip()}"]
    if evidence_note:
        sections.append(evidence_note.strip())
    if limitation_note:
        sections.append(f"Limitation\n{limitation_note.strip()}")
    return "\n\n".join(sections)
