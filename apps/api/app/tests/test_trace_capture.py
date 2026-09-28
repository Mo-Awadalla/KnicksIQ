"""Internal capture isolation: no public state, no fabricated search or replay trace."""

import asyncio

from app.evaluation.trace_capture import capture_turn, record_search, record_tool, record_turn


async def test_concurrent_capture_is_turn_local_and_inactive_by_default():
    record_search({"returned_evidence_ids": ["outside"]})

    async def run(name):
        with capture_turn() as captured:
            record_search({"returned_evidence_ids": [name], "candidate_evidence_ids": [name]})
            await asyncio.sleep(0)
            record_tool({"evidence": [{"evidence_id": name}]})
            record_turn({"request_id": name})
        record_search({"returned_evidence_ids": ["after"]})
        return captured

    first, second = await asyncio.gather(run("first"), run("second"))
    assert first["searches"][0]["returned_evidence_ids"] == ["first"]
    assert second["searches"][0]["returned_evidence_ids"] == ["second"]
    assert len(first["searches"]) == len(second["searches"]) == 1
    assert first["turn"]["request_id"] == "first"


def test_no_search_is_not_a_synthetic_empty_search():
    with capture_turn() as captured:
        record_turn({"replayed": True})
    assert captured["searches"] == [] and captured["turn"]["replayed"]
