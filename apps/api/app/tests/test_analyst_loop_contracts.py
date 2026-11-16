from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from app.tests.support.analyst_protocol import make_tools


async def test_release_change_drops_old_claims_and_scope_transition(db_session):
    tools, player = await make_tools(db_session, "Brunson points")
    result = await tools.execute(ToolCall(name="get_player_stats", question=tools.question))
    state = {
        "release": "superseded",
        "claims": [c.model_dump() for c in result.claims],
        "evidence": [e.model_dump() for e in result.evidence],
        "scope": {"player_ids": [player.id]},
        "delivered_fact_ids": ["old"],
    }
    current = AnalystTools(
        db_session, tools.release, "Now only playoff games", tools.release.season, state
    )
    await current.prepare()
    assert not current.claims and not current.evidence
    assert current.scope is not None
    assert current.scope.player_ids == [player.id]
    assert current.scope.season_type == "playoffs"
    assert not current.state["delivered_fact_ids"]
