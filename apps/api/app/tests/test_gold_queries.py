"""Gold-query smoke regression for analysis grounding."""

from __future__ import annotations

import json
from pathlib import Path

from app.api import analysis


def _gold_queries() -> list[dict]:
    path = Path(__file__).with_name("gold_queries.json")
    return json.loads(path.read_text())


async def test_gold_query_smoke_set_preserves_routing_and_grounding(client):
    analysis._requests_by_client.clear()
    failures: list[str] = []
    for case in _gold_queries():
        response = await client.post(
            "/analysis/query",
            json={"question": case["question"]},
        )
        if response.status_code != 200:
            failures.append(f"{case['question']}: HTTP {response.status_code}")
            continue
        body = response.json()
        tools = {call["tool"] for call in body["tool_calls"]}
        if body["route"] != case["route"]:
            failures.append(
                f"{case['question']}: route {body['route']} != {case['route']}"
            )
        for text in case.get("answer_contains", []):
            if text not in body["answer"] and text not in " ".join(body["warnings"]):
                failures.append(f"{case['question']}: missing answer text {text!r}")
        for tool in case.get("required_tools", []):
            if tool not in tools:
                failures.append(f"{case['question']}: missing tool {tool}")
        for tool in case.get("forbidden_tools", []):
            if tool in tools:
                failures.append(f"{case['question']}: forbidden tool {tool}")
        if body["route"] == "table_rag" and not body["evidence"]:
            failures.append(f"{case['question']}: table route returned no evidence")
    assert failures == []
