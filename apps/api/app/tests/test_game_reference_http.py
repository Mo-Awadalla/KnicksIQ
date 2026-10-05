"""Ten-message game references through actual HTTP/SQL/Redis, written first."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.evaluation.trace_capture import capture_turn
from app.services import analyst_loop
from app.tests.test_analyst_contracts import local_redis  # noqa: F401
from app.tests.test_player_intelligence import _seed_release_stats


def message(content, role="user"):
    return {"role": role, "content": content}


FILLER = [message("Thanks.", "assistant") for _ in range(10)]
MISSING = [
    ("empty", []),
    (
        "unverified-narrative",
        [
            message("How did the Knicks lose the lead against Boston?"),
            message("Boston took control during a decisive second-half run.", "assistant"),
        ],
    ),
    ("outside-ten", [message("Tell me about the Boston game on 2026-01-03."), *FILLER]),
    ("two-games", [message("Compare the Boston games on 2026-01-01 and 2026-01-03.")]),
    (
        "newer-unavailable",
        [message("The Boston game on 2026-01-01."), message("Now the game on 2026-05-31.")],
    ),
]
IDENTIFIED = [
    ("recent", [message("The Boston game on 2026-01-03.")]),
    ("at-ten", [message("The Boston game on 2026-01-03."), *FILLER[:9]]),
    ("latest", [message("The game on 2026-01-01."), message("Now the Boston game on 2026-01-03.")]),
    (
        "assistant-identity",
        [message("Jalen Brunson scored 999 points against Boston on 2026-01-03.", "assistant")],
    ),
    (
        "older-long-message",
        [
            message("Archive context. " * 20 + "The Boston game on 2026-01-03."),
            *[message("Thanks. " * 200, "assistant") for _ in range(9)],
        ],
    ),
]


@pytest.mark.parametrize(
    ("mode", "rate"), [("disabled", 0), ("llm_primary", 0), ("shadow", 0), ("shadow", 1)]
)
@pytest.mark.parametrize(("case_id", "context"), MISSING)
async def test_missing_game_reference_asks_before_model_admission(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    case_id,
    context,
    mode,
    rate,
    record_property,
):
    await exercise(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        case_id,
        context,
        mode,
        rate,
        identified=False,
    )


@pytest.mark.parametrize(("case_id", "context"), IDENTIFIED)
async def test_recent_game_reference_uses_canonical_game_only(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    case_id,
    context,
    record_property,
):
    await exercise(
        client,
        local_redis,
        monkeypatch,
        tmp_path,
        record_property,
        case_id,
        context,
        "disabled",
        0,
        identified=True,
    )


async def exercise(
    client,
    redis,
    monkeypatch,
    tmp_path,
    record_property,
    case_id,
    context,
    mode,
    rate,
    *,
    identified,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", mode)
    monkeypatch.setattr(settings, "analysis_shadow_sample_rate", rate)
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    key = f"ai-budget:{datetime.now(UTC):%Y-%m}"
    await redis.set(key, "0.125")
    attempts = 0

    def denied():
        nonlocal attempts
        attempts += 1
        raise AssertionError("Game reference handling must not invoke a provider")

    monkeypatch.setattr(analyst_loop, "get_llm_adapter", denied)
    payload = {
        "question": "How did JB play in that game?",
        "season": "2025-26",
        "context": context,
        "turn_id": f"game-reference-{case_id}-{mode}-{rate}",
        "expected_revision": 0,
    }
    with capture_turn() as capture:
        response = await client.post("/analysis/query", json=payload)
    body = response.json()
    replay = await client.post("/analysis/query", json=payload)
    conflict = await client.post(
        "/analysis/query", json={**payload, "question": "Changed question"}
    )
    context_conflict = None
    if identified:
        context_conflict = await client.post(
            "/analysis/query",
            json={
                **payload,
                "context": [
                    {**item, "content": item["content"].replace("2026-01-03", "2026-01-01")}
                    for item in context
                ],
            },
        )
    budget = (await redis.get(key)).decode()
    directory = Path(os.environ.get("KNICKSIQ_CONTEXT_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case_id}-{mode}-{rate}.json"
    with path.open("x") as artifact:
        json.dump(
            {
                "request": payload,
                "status": response.status_code,
                "response": body,
                "capture": capture,
                "replay": replay.json(),
                "conflict_status": conflict.status_code,
                "context_conflict_status": context_conflict.status_code
                if context_conflict is not None
                else None,
                "model_attempts": attempts,
                "budget_before": "0.125",
                "budget_after": budget,
            },
            artifact,
            indent=2,
        )
    record_property("game_reference_artifact", str(path))
    assert response.status_code == 200, body
    assert body["state_committed"] and body["revision"] == 1
    assert replay.json() == body and conflict.status_code == 409
    assert attempts == 0 and capture["turn"]["model_calls"] == 0
    assert budget == "0.125"
    if not identified:
        assert body["route"] == "clarification"
        assert body["citations"] == []
    else:
        assert context_conflict is not None and context_conflict.status_code == 409
        assert body["route"] != "clarification" and body["citations"]
        assert "30.0 points" in body["answer"] and "1 observed appearance" in body["answer"]
        assert "999" not in body["answer"]
        receipts = [e for t in capture["tools"] for e in t["result"]["evidence"]]
        assert receipts and all("2026-01-03" in e["text"] for e in receipts)


async def test_stale_committed_game_without_recent_anchor_still_asks(
    client,
    local_redis,  # noqa: F811
    monkeypatch,
    tmp_path,
    record_property,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "analyst_evidence_loop_enabled", True)
    monkeypatch.setattr(settings, "analysis_answer_mode", "disabled")
    async with AsyncSessionLocal() as db:
        await _seed_release_stats(db)
    first = await client.post(
        "/analysis/query",
        json={
            "question": "How many points did JB score on 2026-01-03?",
            "turn_id": "game-reference-committed-first",
            "expected_revision": 0,
        },
    )
    initial = first.json()
    payload = {
        "question": "How did JB play in that game?",
        "context": FILLER,
        "turn_id": "game-reference-committed-next",
        "expected_revision": initial["revision"],
        "session_token": initial["session_token"],
    }
    with capture_turn() as capture:
        second = await client.post("/analysis/query", json=payload)
    directory = Path(os.environ.get("KNICKSIQ_CONTEXT_ARTIFACT_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "stale-committed-game.json"
    with path.open("x") as artifact:
        json.dump(
            {"first": initial, "request": payload, "second": second.json(), "capture": capture},
            artifact,
            indent=2,
        )
    record_property("game_reference_artifact", str(path))
    assert first.status_code == second.status_code == 200
    assert initial["citations"]
    assert second.json()["route"] == "clarification"
    assert second.json()["citations"] == [] and capture["turn"]["model_calls"] == 0
