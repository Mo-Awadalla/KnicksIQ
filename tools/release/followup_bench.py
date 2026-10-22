"""Multi-turn follow-up session benchmark against the real provider.

Each session sends 2 to 4 turns through the same in-process app path the web client uses:
session token, expected revision and `context` history. Expected values are computed from the
local archive by followup_oracle; the model never supplies an expected number. Every turn is
scored with the honest checks plus an expected-scope comparison read from the committed
session state. Session integrity required: one token, consecutive revisions, state committed.

    uv run --package knicksiq-api python tools/release/followup_bench.py --trials 2

Live runs need ANALYSIS_ANSWER_MODE=llm_primary, ANALYST_EVIDENCE_LOOP_ENABLED=true, the local
DB_URL, this worker's REDIS_URL and OPENROUTER_API_KEY in the environment. A refusal that
happens before the analyst path does not commit a turn, so the client keeps the prior token
and revision; the harness does the same.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_DAY", "1000000")
os.environ.setdefault("AI_REASONING_EFFORT", "none")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyst_scoring import score_response  # noqa: E402
from followup_oracle import (  # noqa: E402
    compare_scope,
    expectation_case,
    expectation_checks,
    expectation_for,
    load_sessions,
    oracle,
    scoped,
)

SESSIONS = ROOT / "apps/api/app/evaluation/followup_sessions.jsonl"
OUT = ROOT / "docs/release-evidence/llm-primary-20261021/w3-followups/followup_sessions.json"


def require_live_env() -> None:
    settings = {
        "ANALYSIS_ANSWER_MODE": os.environ.get("ANALYSIS_ANSWER_MODE", ""),
        "ANALYST_EVIDENCE_LOOP_ENABLED": os.environ.get("ANALYST_EVIDENCE_LOOP_ENABLED", ""),
        "DB_URL": os.environ.get("DB_URL", ""),
        "REDIS_URL": os.environ.get("REDIS_URL", ""),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
    }
    problems = []
    if settings["ANALYSIS_ANSWER_MODE"] != "llm_primary":
        problems.append("ANALYSIS_ANSWER_MODE must be llm_primary")
    if settings["ANALYST_EVIDENCE_LOOP_ENABLED"] != "true":
        problems.append("ANALYST_EVIDENCE_LOOP_ENABLED must be true")
    if "localhost:55500" not in settings["DB_URL"]:
        problems.append("DB_URL must be the local restored release")
    if "neon" in settings["DB_URL"].lower():
        problems.append("DB_URL points at Neon")
    if not settings["REDIS_URL"]:
        problems.append("REDIS_URL is required")
    elif urlparse(settings["REDIS_URL"]).path.strip("/") in {"", "0"}:
        problems.append("REDIS_URL must select this worker's db, never db 0")
    if not settings["OPENROUTER_API_KEY"]:
        problems.append("OPENROUTER_API_KEY is required")
    if problems:
        raise SystemExit("; ".join(problems))


def classify(
    status: int,
    body: dict,
    honest_ok: bool,
    expected_ok: bool,
    scope_issues: list[str],
    revision_ok: bool,
) -> str:
    if status != 200:
        return f"pipeline:http_{status}"
    if body.get("degraded"):
        return "pipeline:degraded"
    if not revision_ok:
        return "session:revision"
    if scope_issues and not (honest_ok and expected_ok):
        if body.get("refused"):
            return "scope+decline"
        return "scope"
    if honest_ok and expected_ok:
        return "ok"
    failures = (body.get("_score") or {}).get("failures") or []
    if "declined:phrase:decline" in failures or "declined:field:refused" in failures:
        return "answer:declined"
    if "not_validated" in failures:
        return "answer:not_validated"
    return "answer:value"


async def read_state(redis, token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        raw = await redis.hget(f"analyst:{{{token}}}", "state")
    except Exception:
        return {}
    return json.loads(raw) if raw else {}


async def run_session(
    client,
    redis,
    session: dict,
    archive,
    ids: dict[str, int],
    teams: dict[str, str],
    values,
) -> dict:
    turns = []
    token: str | None = None
    revision = 0
    history: list[dict[str, str]] = []
    token_seen: set[str] = set()
    committed: list[int] = []
    for index, spec in enumerate(session["turns"], start=1):
        expectation = expectation_for(spec, archive, ids, teams)
        case = expectation_case(expectation)
        expected_revision = revision
        try:
            response = await client.post(
                "/analysis/query",
                json={
                    "question": spec["question"],
                    "season": "2025-26",
                    "turn_id": uuid.uuid4().hex,
                    "session_token": token,
                    "expected_revision": expected_revision,
                    "context": history[-40:],
                },
            )
        except Exception as exc:
            turns.append(
                {
                    "turn": index,
                    "question": spec["question"],
                    "status": 0,
                    "cause": f"pipeline:transport:{type(exc).__name__}",
                    "answer": "",
                }
            )
            break
        body = response.json() if response.status_code == 200 else {}
        answer = body.get("answer") or ""
        checks = expectation_checks(answer, expectation, teams)
        state = await read_state(redis, body.get("session_token") or token)
        actual_scope = (state.get("scope") or {}) if state else {}
        scope_issues = (
            []
            if expectation.kind == "decline" or not body.get("state_committed")
            else compare_scope(actual_scope, expectation.scope, archive)
        )
        score = score_response(
            case,
            {
                "answer": answer,
                "citations": body.get("citations") or [],
                "llm_validated": body.get("llm_validated"),
                "warnings": body.get("warnings") or [],
                "refused": body.get("refused", False),
                "degraded": body.get("degraded", False),
                "outcome": "live",
            },
            universe=values.universe,
            archive=values.archive,
            scoped=scoped(answer, case, values),
            strict=True,
        )
        if expectation.kind == "decline":
            expected_ok = score["checks"]["declined"]
        else:
            expected_ok = bool(
                checks.get("decline")
                or checks.get("record_ok")
                or checks.get("fact_ok")
                or checks.get("value_ok")
            )
        honest_ok = score["meets_expectation"]
        new_token = body.get("session_token")
        new_revision = body.get("revision")
        if new_token:
            token_seen.add(new_token)
        if new_revision is not None:
            committed.append(new_revision)
        revision_ok = new_revision in (None, expected_revision + 1)
        if new_token:
            token = new_token
        if new_revision is not None:
            revision = new_revision
        stages = [
            {
                key: item.get(key)
                for key in ("stage", "tool", "action", "tools_requested", "status", "claims")
                if item.get(key) is not None
            }
            for item in (body.get("tool_calls") or [])
            if item.get("stage") != "prepare" or item.get("tool") in {"query_resolution"}
        ]
        body["_score"] = score
        cause = classify(
            response.status_code, body, honest_ok, expected_ok, scope_issues, revision_ok
        )
        turns.append(
            {
                "turn": index,
                "question": spec["question"],
                "status": response.status_code,
                "answer": answer,
                "cause": cause,
                "expected": {
                    "kind": expectation.kind,
                    "fact": expectation.fact,
                    "record": expectation.record,
                    "scope": expectation.scope,
                },
                "expected_checks": checks,
                "expected_ok": expected_ok,
                "honest_ok": honest_ok,
                "failures": score["failures"],
                "checks": score["checks"],
                "actual_scope": actual_scope,
                "scope_issues": scope_issues,
                "state_intent": state.get("intent"),
                "carried_claims": [
                    {
                        "metric": claim.get("metric_id"),
                        "season_type": claim.get("season_type"),
                        "games": len(claim.get("game_ids") or []),
                    }
                    for claim in state.get("claims") or []
                ],
                "stages": stages,
                "citations": [
                    {
                        "metric": (citation.get("metadata") or {})
                        .get("claim", {})
                        .get("metric_id"),
                        "value": (citation.get("metadata") or {}).get("claim", {}).get("value"),
                        "season_type": (citation.get("metadata") or {})
                        .get("claim", {})
                        .get("season_type"),
                        "games": len(
                            (citation.get("metadata") or {}).get("claim", {}).get("game_ids") or []
                        ),
                    }
                    for citation in (body.get("citations") or [])
                ],
                "warnings": body.get("warnings") or [],
                "llm_validated": body.get("llm_validated"),
                "refused": body.get("refused", False),
                "degraded": body.get("degraded", False),
                "revision": new_revision,
                "expected_revision": expected_revision,
                "revision_ok": revision_ok,
                "state_committed": body.get("state_committed"),
                "session_token_returned": bool(new_token),
            }
        )
        if response.status_code != 200:
            break
        history += [
            {"role": "user", "content": spec["question"]},
            {"role": "assistant", "content": answer[:2000]},
        ]
    integrity = {
        "single_token": len(token_seen) <= 1,
        "revisions": committed,
        "consecutive": committed == list(range(1, len(committed) + 1)),
        "turns_committed": sum(1 for turn in turns if turn.get("revision") is not None),
        "turns": len(turns),
        "all_200_settled": all(
            turn.get("state_committed") or turn.get("refused")
            for turn in turns
            if turn["status"] == 200
        ),
    }
    integrity_ok = (
        integrity["single_token"] and integrity["consecutive"] and integrity["all_200_settled"]
    )
    return {
        "id": session["id"],
        "category": session.get("category"),
        "turns": turns,
        "integrity": integrity,
        "pass": integrity_ok and all(turn["cause"] == "ok" for turn in turns),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--sessions", type=Path, default=SESSIONS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--session", action="append", default=[])
    parser.add_argument("--flush-redis", action="store_true")
    args = parser.parse_args()
    require_live_env()
    if args.flush_redis:
        from redis.asyncio import Redis

        redis = Redis.from_url(os.environ["REDIS_URL"])
        await redis.flushdb()
        await redis.aclose()
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient
    from redis.asyncio import Redis

    sessions = load_sessions(args.sessions)
    if args.session:
        wanted = set(args.session)
        sessions = [session for session in sessions if session["id"] in wanted]
    values, ids, teams = await oracle()
    app = create_app()
    results: dict[str, list[dict]] = {session["id"]: [] for session in sessions}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=120
        ) as client:
            redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
            for trial in range(1, args.trials + 1):
                for session in sessions:
                    run = await run_session(
                        client, redis, session, values.archive, ids, teams, values
                    )
                    run["trial"] = trial
                    results[session["id"]].append(run)
                    print(
                        session["id"],
                        trial,
                        " ".join(turn["cause"] for turn in run["turns"]),
                        run["pass"],
                    )
            await redis.aclose()
    summary = {}
    for session in sessions:
        runs = results[session["id"]]
        summary[session["id"]] = {
            "passes": sum(run["pass"] for run in runs),
            "trials": len(runs),
            "turn_passes": [sum(turn["cause"] == "ok" for turn in run["turns"]) for run in runs],
            "turns": [len(run["turns"]) for run in runs],
        }
    causes: dict[str, list[dict]] = {}
    for session in sessions:
        for run in results[session["id"]]:
            for turn in run["turns"]:
                if turn["cause"] != "ok":
                    causes.setdefault(turn["cause"], []).append(
                        {
                            "session": session["id"],
                            "trial": run["trial"],
                            "turn": turn["turn"],
                            "question": turn["question"],
                            "issues": turn.get("scope_issues") or turn.get("failures"),
                        }
                    )
    out = {
        "mode": "live_llm_primary",
        "base": os.environ.get("BENCH_BASE", "5b585e6"),
        "trials": args.trials,
        "sessions": results,
        "summary": summary,
        "causes": causes,
        "totals": {
            "turns": sum(len(run["turns"]) for runs in results.values() for run in runs),
            "turn_passes": sum(
                turn["cause"] == "ok"
                for runs in results.values()
                for run in runs
                for turn in run["turns"]
            ),
            "session_passes": sum(run["pass"] for runs in results.values() for run in runs),
            "session_runs": sum(len(runs) for runs in results.values()),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out["totals"]))
    print(json.dumps({key: len(value) for key, value in causes.items()}))


if __name__ == "__main__":
    asyncio.run(main())
