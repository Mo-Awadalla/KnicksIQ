"""Private factual state retains supported release identities across follow-ups."""

import pytest
from app.conversation.facts import FactDesk
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.tests.support.player_archive import _seed_release_stats
from sqlalchemy import select


@pytest.mark.parametrize("length", [41, 64])
async def test_supported_release_version_survives_followup(client, length):
    version = "archive-" + "v" * (length - len("archive-"))
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
        release = (await db.execute(select(DatasetRelease))).scalar_one()
        release.version = version
        await db.commit()
    desk = FactDesk("2025-26", {}, 6000, "release-boundary-initial")
    try:
        first = await desk.lookup("What was the Knicks record this season?")
        assert first["status"] == "found"
        state = desk.persisted_state()
        assert state["release"] == version
    finally:
        await desk.close()
    followup = FactDesk("2025-26", state, 6000, "release-boundary-followup")
    try:
        assert (await followup.lookup("What was the Knicks record this season?"))[
            "status"
        ] == "found"
        assert followup.persisted_state()["release"] == version
    finally:
        await followup.close()
