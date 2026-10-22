"""Redis process, seeded tools and scripted model fixtures for analyst integration."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess

import pytest
from app.services import analyst_budget, analyst_sessions
from app.services.analyst_tools import AnalystTools
from app.tests.support.player_archive import _seed_release_stats
from redis.asyncio import Redis


@pytest.fixture
async def local_redis(monkeypatch, tmp_path):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server is required for atomic concurrency integration tests")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            binary,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def connection():
        return Redis.from_url(f"redis://127.0.0.1:{port}", socket_timeout=1)

    redis = await connection()
    try:
        for _ in range(100):
            try:
                await redis.ping()
                break
            except ConnectionError:
                await asyncio.sleep(0.01)
            except Exception:
                await asyncio.sleep(0.01)
        monkeypatch.setattr(analyst_budget, "_redis", connection)
        monkeypatch.setattr(analyst_sessions, "_session_redis", connection)
        yield redis
    finally:
        await redis.aclose()
        process.terminate()
        process.wait(timeout=5)


async def make_tools(db, question="Give me an interesting stat", state=None):
    release, player = await _seed_release_stats(db)
    tools = AnalystTools(db, release, question, release.season, state or {})
    await tools.prepare()
    return tools, player


class ScriptedAdapter:
    """Protocol fixture, deliberately not an evaluation of model quality."""

    def __init__(self):
        self.max_tokens = 0
        self.last_metadata = {"usage": {"cost": 0}, "provider": "protocol-fixture"}
        self.prompts = []

    async def generate(self, *, system, user):
        payload = json.loads(user)
        self.prompts.append(payload)
        if payload["schema"]["title"] == "AnswerReview":
            answer = payload["proposed_answer"]
            return json.dumps(
                {
                    "assertions": [
                        {
                            "text": span,
                            "verdict": "supported",
                            "assertion_type": "factual",
                            "offending_text": None,
                            "supporting_claim_ids": [c["claim_id"] for c in answer["claims"]],
                            "supporting_evidence_ids": [],
                            "reason": "Matches backend claims.",
                        }
                        for span in payload["review_spans"]
                    ]
                }
            )
        if not payload["claims"]:
            return json.dumps(
                {
                    "action": "call_tools",
                    "tools": [{"name": "discover_facts", "question": payload["question"]}],
                    "answer": None,
                }
            )
        candidate = next(iter(payload["candidates"]), None)
        claims = (
            [c for c in payload["claims"] if c["claim_id"] in candidate["claim_ids"]]
            if candidate
            else payload["claims"][:1]
        )
        return json.dumps(
            {
                "action": "answer_from_available_evidence",
                "tools": [],
                "answer": {
                    "text": " ".join(c["statement"] for c in claims),
                    "claims": [
                        {"claim_id": c["claim_id"], "displayed_value": c["value"]} for c in claims
                    ],
                    "evidence_ids": [],
                    "fact_ids": [candidate["fact_id"]] if candidate else [],
                },
            }
        )
