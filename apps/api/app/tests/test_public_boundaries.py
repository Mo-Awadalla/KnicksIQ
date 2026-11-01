"""Public conversation-state round trips respect persisted release identities."""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.tests.support.player_archive import _seed_release_stats
from sqlalchemy import select


@pytest.mark.parametrize("length", [41, 64])
async def test_supported_release_version_survives_followup(client, monkeypatch, length):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", False)
    monkeypatch.setattr(settings, "rag_structured_conversation_state_enabled", True)
    version = "archive-" + "v" * (length - len("archive-"))
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
        release = (await db.execute(select(DatasetRelease))).scalar_one()
        release.version = version
        await db.commit()

    response = await client.post(
        "/analysis/query", json={"question": "What was the Knicks record this season?"}
    )
    assert response.status_code == 200
    state = response.json()["conversation_state"]
    assert state["data_version"] == version
    followup = await client.post(
        "/analysis/query",
        json={
            "question": "What was the Knicks record this season?",
            "conversation_state": state,
        },
    )
    assert followup.status_code == 200
    assert followup.json()["conversation_state"]["data_version"] == version
