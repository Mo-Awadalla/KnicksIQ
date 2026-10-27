"""Redis process, seeded tools and scripted model fixtures for analyst integration."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess

import pytest
from app.services import analyst_budget, analyst_loop, analyst_sessions
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
            answer = analyst_loop.payload_proposed_answer(payload)
            assert answer is not None
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
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
                    },
                )
            )
        available = analyst_loop.payload_claims(payload)
        profile_metrics = {"points", "rebounds", "assists", "game_score"}
        scope = payload["capabilities"].get("scope", {})
        if (
            payload["schema"]["title"] == "Action"
            and scope.get("player_ids")
            and len(scope.get("game_ids", [])) == 1
            and scope.get("metric") is None
            and not profile_metrics <= {claim["metric_id"].partition(":")[0] for claim in available}
        ):
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "action": "call_tools",
                        "tools": [
                            {"name": "get_player_stats", "question": payload["requested_question"]}
                        ],
                        "answer": None,
                    },
                )
            )
        if not available:
            return json.dumps(
                analyst_loop.encode_model_response(
                    payload,
                    {
                        "action": "call_tools",
                        "tools": [
                            {"name": "discover_facts", "question": payload["requested_question"]}
                        ],
                        "answer": None,
                    },
                )
            )
        candidate = next(iter(payload.get("candidates", [])), None)
        claims = (
            [claim for claim in available if claim["claim_id"] in candidate["claim_ids"]]
            if candidate
            else available[:1]
        )
        if profile_metrics <= {claim["metric_id"].partition(":")[0] for claim in available}:
            claims = [
                claim
                for claim in available
                if claim["metric_id"].partition(":")[0] in profile_metrics
            ]
            candidate = None
        if payload.get("required_claim_indexes"):
            claims = [available[domain[0]] for domain in payload["required_claim_indexes"]]
            candidate = None
        answer = {
            "text": " ".join(c["statement"] for c in claims),
            "claims": [
                {"claim_id": c["claim_id"], "displayed_value": c["value"], "decimal_places": None}
                for c in claims
            ],
            "evidence_ids": [],
            "fact_ids": [candidate["fact_id"]] if candidate else [],
            "follow_up_questions": [],
        }
        return json.dumps(
            analyst_loop.encode_model_response(
                payload,
                answer
                if payload["schema"]["title"] == "ProposedAnswer"
                else {"action": "answer_from_available_evidence", "tools": [], "answer": answer},
            )
        )
