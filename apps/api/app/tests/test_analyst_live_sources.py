"""Reviewed archive receipts and scope decisions."""

from __future__ import annotations

import pytest
from app.services.analyst_loop import AnalystLoop
from app.services.evidence_contracts import Evidence, ProposedAnswer, ToolCall
from app.tests.support.analyst_protocol import make_tools


@pytest.mark.parametrize("reviewed,expected", [(True, "answer"), (False, None)])
async def test_archive_receipt_answer_has_a_disposition_only_after_review(
    db_session, reviewed, expected
):
    tools, _ = await make_tools(db_session, "What was the Knicks record in this archive?")
    result = await tools.execute(ToolCall(name="get_team_stats", question=tools.question))
    receipt = result.evidence[0]
    answer = ProposedAnswer(
        text="An archive-supported explanation.", evidence_ids=[receipt.evidence_id]
    )
    rendered = AnalystLoop(tools, []).render(answer, llm=reviewed, delivered=[])
    assert rendered["outcome"] == expected
    assert rendered["citations"][0]["type"] == "archive"
    assert rendered["state"]["evidence"][0]["evidence_id"] == receipt.evidence_id


@pytest.mark.parametrize(
    "collection,data_type", [("possessions", "play_by_play"), ("reports", "reviewed_game_reports")]
)
async def test_returned_archive_sources_are_disclosed_to_the_answer_reviewer(
    db_session, collection, data_type
):
    tools, _ = await make_tools(db_session)
    receipt = Evidence(
        evidence_id="archive-source",
        release_id=tools.release.version,
        text="A returned archive receipt.",
        metadata={"document_collection": collection},
    )
    tools.evidence[receipt.evidence_id] = receipt
    assert data_type in tools.manifest()["data_types"]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Who was better?", "clarify"),
        ("Will the Knicks win their next game?", "refuse"),
    ],
)
async def test_reviewed_scope_decision_does_not_require_an_unnecessary_tool_call(
    db_session, question, expected
):
    tools, _ = await make_tools(db_session, question)
    rendered = AnalystLoop(tools, []).render(
        ProposedAnswer(text="A reviewed scope response."), llm=True, delivered=[]
    )
    assert rendered["outcome"] == expected
    assert rendered["refused"] is (expected == "refuse")
    assert rendered["citations"] == []


async def test_large_server_provenance_does_not_hide_small_game_and_report_receipts(db_session):
    from app.services.evidence_contracts import Action, ToolResult

    tools, _ = await make_tools(db_session, "Search the archive for a cited final score.")
    receipts = [
        Evidence(
            evidence_id=ref,
            release_id=tools.release.version,
            text=text,
            metadata={
                "document_collection": collection,
                "document_payload": {"raw_rows": [{"description": "x" * 12000}]},
            },
        )
        for ref, collection, text in [
            ("game-receipt", "games", "New York 119, Cleveland 111."),
            ("report-receipt", "reports", "New York won the archived game by eight points."),
        ]
    ]
    tools.evidence.update({receipt.evidence_id: receipt for receipt in receipts})
    loop = AnalystLoop(tools, [])
    loop.results.append(
        ToolResult(status="ok", message="Retrieved archive sources.", evidence=receipts)
    )
    payload = loop.payload(Action)
    assert {item["evidence_id"]: item["text"] for item in payload["evidence"]} == {
        "game-receipt": "New York 119, Cleveland 111.",
        "report-receipt": "New York won the archived game by eight points.",
    }
