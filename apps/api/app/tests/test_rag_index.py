"""Tests for staged local RAG indexing."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.models.game import Game
from app.models.game_event import GameEvent
from app.services.possession_chunks import PossessionChunk
from app.services.rag_index import build_rag_artifacts
from sqlalchemy import delete


async def _replace_games(db_session, count: int) -> list[Game]:
    await db_session.execute(delete(GameEvent))
    await db_session.execute(delete(Game))
    games = [
        Game(
            nba_game_id=f"staged-{index}",
            season="2025-26",
            game_date=date(2025, 10, 1) + timedelta(days=index),
            home_team_id="NYK",
            away_team_id="BOS",
            home_score=100 + index,
            away_score=90 + index,
            status="final",
            season_type="regular",
            data_status="events_ready",
        )
        for index in range(count)
    ]
    db_session.add_all(games)
    await db_session.commit()
    for game in games:
        await db_session.refresh(game)
    return games


async def test_build_rag_artifacts_limits_to_recent_games_and_reports_manifest(
    monkeypatch,
    db_session,
    tmp_path: Path,
):
    await _replace_games(db_session, 12)
    chunked_game_ids: list[int] = []
    reset_calls: list[str] = []
    upsert_calls: list[tuple[str, int]] = []

    def fake_chunks(game, _events, **_kwargs):
        chunked_game_ids.append(game.id)
        return [
            PossessionChunk(
                chunk_id=f"game:{game.id}:poss:0",
                game_id=game.id,
                text=f"{game.game_date} possession",
                metadata={
                    "game_id": game.id,
                    "date": str(game.game_date),
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                    "season": game.season,
                    "season_type": game.season_type,
                    "data_status": game.data_status,
                    "possession_index": 0,
                    "start_period": 1,
                    "end_period": 1,
                    "start_clock": "12:00",
                    "end_clock": "11:45",
                    "team_ids": ["NYK"],
                    "player_ids": [],
                    "player_names": [],
                    "row_count": 1,
                },
                rows=[{"description": "Knicks made shot"}],
            )
        ]

    monkeypatch.setattr("app.services.rag_index.build_possession_chunks", fake_chunks)
    monkeypatch.setattr(
        "app.services.rag_index.get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=None,
            rag_qdrant_enabled=True,
            rag_qdrant_possessions_collection="knicks_possessions",
        ),
    )
    monkeypatch.setattr(
        "app.services.rag_index.recreate_collection",
        lambda collection: reset_calls.append(collection),
    )
    monkeypatch.setattr(
        "app.services.rag_index.embed_texts",
        lambda texts: [[0.1] * 1024 for _text in texts],
    )

    def fake_upsert(collection, records, embeddings):
        upsert_calls.append((collection, len(records)))
        assert len(records) == len(embeddings)
        return len(records)

    monkeypatch.setattr("app.services.rag_index.upsert_points", fake_upsert)

    manifest = await build_rag_artifacts(
        db_session,
        season="2025-26",
        out_dir=tmp_path,
        game_limit=10,
        game_order="recent",
        reset_qdrant=True,
    )

    selected_dates = [item["date"] for item in manifest["selected_games"]]
    assert selected_dates == sorted(selected_dates, reverse=True)
    assert selected_dates[0] == "2025-10-12"
    assert selected_dates[-1] == "2025-10-03"
    assert len(chunked_game_ids) == 10
    assert manifest["available_games"] == 12
    assert manifest["selected_game_count"] == 10
    assert manifest["possession_chunk_count"] == 10
    assert manifest["qdrant_reset_requested"] is True
    assert manifest["qdrant_reset"] is True
    assert manifest["qdrant_upserted"] == 10
    assert manifest["qdrant_batch_size"] == 512
    assert manifest["elapsed_seconds"] >= 0
    assert reset_calls == ["knicks_possessions"]
    assert upsert_calls == [("knicks_possessions", 10)]


async def test_build_rag_artifacts_does_not_reset_qdrant_unless_requested(
    monkeypatch,
    db_session,
    tmp_path: Path,
):
    await _replace_games(db_session, 1)
    reset_calls: list[str] = []
    ensure_calls: list[bool] = []

    monkeypatch.setattr(
        "app.services.rag_index.build_possession_chunks",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.rag_index.get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key=None,
            rag_qdrant_enabled=True,
            rag_qdrant_possessions_collection="knicks_possessions",
        ),
    )
    monkeypatch.setattr(
        "app.services.rag_index.recreate_collection",
        lambda collection: reset_calls.append(collection),
    )
    monkeypatch.setattr(
        "app.services.rag_index.ensure_collections",
        lambda: ensure_calls.append(True),
    )

    manifest = await build_rag_artifacts(
        db_session,
        season="2025-26",
        out_dir=tmp_path,
        reset_qdrant=False,
    )

    assert manifest["qdrant_reset_requested"] is False
    assert manifest["qdrant_reset"] is False
    assert reset_calls == []
    assert ensure_calls == []
