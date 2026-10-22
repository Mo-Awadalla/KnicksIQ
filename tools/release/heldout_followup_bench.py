"""Live two-turn benchmark for the held-out v2 follow-up sessions.

`followup_bench.py` reads sessions whose turns carry a structured ``expect`` spec that
``followup_oracle`` turns into an expected value. The held-out v2 file carries fact strings
computed by its generator instead (``required_facts``, ``required_entities``,
``required_phrases``, ``filters.game_id``), so this thin adapter drives the same live session
loop and reuses the same honest scorer, scope comparison and cause classifier:

- turn 1 is sent with no history; turn 2 is sent with the session token, the expected
  revision and the answer the app actually gave for turn 1;
- every turn is scored by ``analyst_scoring.score_response`` against the committed held-out
  row (no new labels, no oracle guesses);
- the committed Redis scope is compared with the game the held-out session names via
  ``followup_oracle.compare_scope``;
- session integrity and the per-turn cause come from ``followup_rescore.classify``.

    . /tmp/go.env
    REDIS_URL=redis://localhost:56500/11 \
      uv run --package knicksiq-api python tools/release/heldout_followup_bench.py \
      --out docs/release-evidence/llm-primary-20261021/heldout-final/followups.json
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
from followup_oracle import compare_scope, oracle, scoped  # noqa: E402
from followup_rescore import classify  # noqa: E402

SESSIONS = ROOT / "apps/api/app/evaluation/heldout_v2/follow_ups.jsonl"

METRICS = {
    "margin": "margin",
    "three-pointers": "three_pointers_made",
    "three pointers": "three_pointers_made",
    "rebounds": "rebounds",
    "boards": "rebounds",
    "assists": "assists",
    "dimes": "assists",
    "points": "points",
}


def load_sessions(path: Path) -> list[dict[str, Any]]:
    sessions = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for session in sessions:
        turns = session.get("turns") or []
        if len(turns) != 2:
            raise SystemExit(f"{session['id']}: expected 2 turns, got {len(turns)}")
        for index, turn in enumerate(turns):
            if not turn.get("question") or not turn.get("required_facts"):
                raise SystemExit(f"{session['id']} turn {index + 1}: question/facts required")
        if not (session.get("filters") or {}).get("game_id"):
            raise SystemExit(f"{session['id']}: filters.game_id required")
    return sessions


def turn_case(session: dict, index: int) -> dict:
    turn = session["turns"][index]
    case: dict[str, Any] = {
        "id": f"{session['id']}-t{index + 1}",
        "category": "follow_ups",
        "question": turn["question"],
        "answerable": True,
        "required_facts": list(turn.get("required_facts") or []),
    }
    if index == 1:
        # The committed row labels the scored follow-up; turn 1 is context but its score
        # fact still has to be right for the session to pass.
        case["required_entities"] = list(session.get("required_entities") or [])
        case["required_phrases"] = list(session.get("required_phrases") or [])
        case["filters"] = dict(session.get("filters") or {})
    return case


def metric_for(facts: list[str]) -> str | None:
    text = " ".join(facts).casefold()
    for needle, metric in METRICS.items():
        if needle in text:
            return metric
    return None


def expected_scope(session: dict, index: int, archive, ids: dict[str, int]) -> dict:
    game_id = int(session["filters"]["game_id"])
    game = archive.game(game_id)
    scope: dict[str, Any] = {
        "season_type": game.season_type,
        "all_phases": False,
        "game_count": 1,
        "game_ids": [game_id],
        "player_ids": [],
        "metric": None,
        "home_away": None,
        "opponent_id": None,
        "relative_game_count": None,
        "date_start": None,
        "date_end": None,
    }
    if index == 1:
        entities = session.get("required_entities") or []
        for entity in entities:
            if entity in ids:
                scope["player_ids"] = [ids[entity]]
        scope["metric"] = metric_for(list(session["turns"][1].get("required_facts") or []))
    return scope


async def read_state(redis, token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        raw = await redis.hget(f"analyst:{{{token}}}", "state")
    except Exception:
        return {}
    return json.loads(raw) if raw else {}


def require_live_env() -> None:
    settings = {
        "ANALYSIS_ANSWER_MODE": os.environ.get("ANALYSIS_ANSWER_MODE", ""),
        "ANALYST_EVIDENCE_LOOP_ENABLED": os.environ.get("ANALYST_EVIDENCE_LOOP_ENABLED", ""),
        "DB_URL": os.environ.get("DB_URL", ""),
        "REDIS_URL": os.environ.get("REDIS_URL", ""),
        "API_KEY": os.environ.get("AI_API_KEY") or os.environ.get("OPENROUTER_API_KEY", ""),
    }
    problems = []
    if settings["ANALYSIS_ANSWER_MODE"] != "llm_primary":
        problems.append("ANALYSIS_ANSWER_MODE must be llm_primary")
    if settings["ANALYST_EVIDENCE_LOOP_ENABLED"] != "true":
        problems.append("ANALYST_EVIDENCE_LOOP_ENABLED must be true")
    if "localhost:55500" not in settings["DB_URL"]:
        problems.append("DB_URL must be the local restored release")
    if not settings["REDIS_URL"]:
        problems.append("REDIS_URL is required")
    elif urlparse(settings["REDIS_URL"]).path.strip("/") in {"", "0"}:
        problems.append("REDIS_URL must select this worker's db, never db 0")
    if not settings["API_KEY"]:
        problems.append("AI_API_KEY (or OPENROUTER_API_KEY) is required")
    if problems:
        raise SystemExit("; ".join(problems))


async def run_session(client, redis, session, values, ids) -> dict:
    turns = []
    token: str | None = None
    revision = 0
    history: list[dict[str, str]] = []
    token_seen: set[str] = set()
    committed: list[int] = []
    for index, spec in enumerate(session["turns"]):
        case = turn_case(session, index)
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
                    "turn": index + 1,
                    "question": spec["question"],
                    "status": 0,
                    "cause": f"pipeline:transport:{type(exc).__name__}",
                    "answer": "",
                }
            )
            break
        body = response.json() if response.status_code == 200 else {}
        answer = body.get("answer") or ""
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
        checks = score["checks"]
        expected_ok = bool(checks["required_facts_ok"])
        if checks["required_entities_ok"] is False:
            expected_ok = False
        if checks["required_phrases_ok"] is False:
            expected_ok = False
        honest_ok = score["meets_expectation"]
        state = await read_state(redis, body.get("session_token") or token)
        actual_scope = (state.get("scope") or {}) if state else {}
        scope_issues = (
            []
            if not body.get("state_committed")
            else compare_scope(
                actual_scope, expected_scope(session, index, values.archive, ids), values.archive
            )
        )
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
                for key in (
                    "stage",
                    "tool",
                    "action",
                    "model",
                    "served_model",
                    "protocol",
                    "provider",
                    "review_accepted",
                    "latency_ms",
                )
                if item.get(key) is not None
            }
            for item in (body.get("tool_calls") or [])
            if item.get("stage") != "prepare" or item.get("tool") in {"query_resolution"}
        ]
        cause = classify(
            response.status_code,
            {"degraded": body.get("degraded"), "refused": body.get("refused"), "_score": score},
            honest_ok,
            expected_ok,
            scope_issues,
            revision_ok,
        )
        turns.append(
            {
                "turn": index + 1,
                "question": spec["question"],
                "status": response.status_code,
                "answer": answer,
                "cause": cause,
                "honest_ok": honest_ok,
                "expected_ok": expected_ok,
                "failures": score["failures"],
                "checks": checks,
                "expected_scope": expected_scope(session, index, values.archive, ids),
                "actual_scope": actual_scope,
                "scope_issues": scope_issues,
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
    parser.add_argument("--sessions", type=Path, default=SESSIONS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--session", action="append", default=[])
    parser.add_argument("--flush-redis", action="store_true")
    args = parser.parse_args()

    sessions = load_sessions(args.sessions)
    if args.session:
        wanted = set(args.session)
        sessions = [session for session in sessions if session["id"] in wanted]
    require_live_env()
    values, ids, _teams = await oracle()

    if args.flush_redis:
        from redis.asyncio import Redis

        redis = Redis.from_url(os.environ["REDIS_URL"])
        await redis.flushdb()
        await redis.aclose()
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient
    from redis.asyncio import Redis

    app = create_app()
    results = {session["id"]: [] for session in sessions}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=120
        ) as client:
            redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
            for trial in range(1, args.trials + 1):
                for session in sessions:
                    run = await run_session(client, redis, session, values, ids)
                    run["trial"] = trial
                    results[session["id"]].append(run)
                    print(
                        session["id"],
                        trial,
                        " ".join(turn["cause"] for turn in run["turns"]),
                        run["pass"],
                    )
            await redis.aclose()

    summary = {
        session["id"]: {
            "passes": sum(run["pass"] for run in results[session["id"]]),
            "trials": len(results[session["id"]]),
            "turn_passes": [
                sum(turn["cause"] == "ok" for turn in run["turns"])
                for run in results[session["id"]]
            ],
            "turns": [len(run["turns"]) for run in results[session["id"]]],
        }
        for session in sessions
    }
    causes: dict[str, list[dict]] = {}
    for session in sessions:
        for run in results[session["id"]]:
            for turn in run["turns"]:
                if turn["cause"] != "ok":
                    causes.setdefault(turn["cause"], []).append(
                        {
                            "session": session["id"],
                            "trial": run.get("trial"),
                            "turn": turn["turn"],
                            "question": turn["question"],
                            "failures": turn.get("failures"),
                            "scope_issues": turn.get("scope_issues"),
                        }
                    )
    totals = {
        "turns": sum(len(run["turns"]) for runs in results.values() for run in runs),
        "turn_passes": sum(
            turn["cause"] == "ok"
            for runs in results.values()
            for run in runs
            for turn in run["turns"]
        ),
        "session_passes": sum(run["pass"] for runs in results.values() for run in runs),
        "session_runs": sum(len(runs) for runs in results.values()),
    }
    out = {
        "mode": "live_llm_primary",
        "source": "live in-process API",
        "adapter": "tools/release/heldout_followup_bench.py",
        "trials": args.trials,
        "sessions": results,
        "summary": summary,
        "causes": causes,
        "totals": totals,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(totals))
    print(json.dumps({key: len(value) for key, value in causes.items()}))


if __name__ == "__main__":
    asyncio.run(main())
