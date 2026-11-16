"""Private discovery never broadens missing or unsupported season scope."""

import pytest
from app.services.analyst_tools import AnalystTools
from app.tests.support.factual_queries import lookup
from app.tests.support.player_archive import _seed_release_stats


@pytest.mark.parametrize(
    "question",
    [
        "Something surprising about Brunson in the playoffs?",
        "Something surprising about Brunson on 2026-01-02?",
        "Something surprising about Brunson in 2024-25?",
        "Something surprising about Nobody McFake?",
        "An interesting stat about the Lakers season",
    ],
)
async def test_missing_evidence_never_broadens_scope(db_session, question):
    release, _ = await _seed_release_stats(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    result = await lookup(tools)
    assert not result.claims


@pytest.mark.parametrize(
    "question",
    [
        "Is Brunson injured today?",
        "Give me an interesting stat from the current season",
        "Something surprising about Brunson tonight?",
    ],
)
async def test_live_requests_are_not_reinterpreted_as_discovery(db_session, question):
    release, _ = await _seed_release_stats(db_session)
    tools = AnalystTools(db_session, release, question, release.season, {})
    await tools.prepare()
    result = await lookup(tools)
    assert result.status == "unsupported_metric_or_scope"
    assert not result.claims


async def test_discovery_binds_player_and_release(db_session):
    release, player = await _seed_release_stats(db_session)
    tools = AnalystTools(
        db_session, release, "Something surprising about Brunson?", release.season, {}
    )
    await tools.prepare()
    result = await lookup(tools)
    assert result.status == "ok"
    assert result.claims
    assert any(
        claim.metric_id == "box_score"
        and isinstance(claim.value, dict)
        and claim.value["points"] == 30
        for claim in result.claims
    )
    assert all(claim.release_id == release.version for claim in result.claims)
    assert all(claim.subject_id == f"player:{player.id}" for claim in result.claims)
    assert all(claim.supporting_evidence_ids for claim in result.claims)
