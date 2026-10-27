"""Deterministic multi-turn follow-up audit: backend scope, prefetch and fallback, no provider.

This is the offline half of the follow-up benchmark. It replays each session through the same
AnalystTools.prepare, backend prefetch and deterministic fallback the server uses, with the
committed state a turn would store. The provider is never called, so the result isolates
conversation scope and fallback correctness from model wording. The live half is
tools/release/followup_bench.py.

    DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
      uv run --package knicksiq-api python tools/release/followup_scope_audit.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from analyst_scoring import score_response
from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.analyst_fallback import decline_text, fallback_claims, re_search_discovery
from app.services.analyst_prefetch import prefetch_calls
from app.services.analyst_tool_registry import recovery_tool
from app.services.analyst_tools import AnalystTools
from app.services.evidence_contracts import ToolCall
from followup_oracle import (
    compare_scope,
    expectation_case,
    expectation_checks,
    expectation_for,
    load_sessions,
    oracle,
    scoped,
)
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ROOT / "apps/api/app/evaluation/followup_sessions.jsonl"
OUT = ROOT / "docs/release-evidence/llm-primary-20261021/w3-followups/offline_scope_audit.json"


class FakeLoop:
    """Only the attributes the deterministic fallback reads."""

    def __init__(self, tools: AnalystTools, results: list) -> None:
        self.tools = tools
        self.results = results
        self.recovery_ran = True
        self.remaining = lambda: 0.0


def clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def citations_for(claims: list) -> list[dict]:
    citations = []
    for claim in claims:
        for ref in claim.supporting_evidence_ids[:3]:
            citations.append(
                {
                    "claim": claim.statement,
                    "type": "verified_claim",
                    "title": claim.statement,
                    "metadata": {
                        "claim": claim.model_dump(mode="json"),
                        "evidence_id": ref,
                    },
                }
            )
    return citations


def committed_state(tools: AnalystTools, claims: list) -> dict:
    """The state delivery commits: used claims, their evidence and delivered subjects."""
    state = clone(tools.state)
    state["declined"] = not claims
    references = {ref for claim in claims for ref in claim.supporting_evidence_ids}
    state["claims"] = [claim.model_dump(mode="json") for claim in claims]
    state["evidence"] = [
        tools.evidence[ref].model_dump(mode="json") for ref in references if ref in tools.evidence
    ]
    state["last_subjects"] = list(dict.fromkeys(claim.subject_id for claim in claims))
    players = [
        int(subject.split(":")[1])
        for subject in state["last_subjects"]
        if subject.startswith("player:")
    ]
    if players and state.get("scope"):
        state["scope"]["player_ids"] = players
        state["scope_origin"] = "delivered_subject"
    return state


def classify(turn: dict, scope_issues: list[str], expected_ok: bool, declined: bool) -> str:
    if not scope_issues:
        if expected_ok:
            return "ok"
        if declined and turn["expect"]["kind"] != "decline":
            return "answer:declined"
        return "answer:value"
    if expected_ok:
        return "latent_scope"
    if declined and turn["expect"]["kind"] != "decline":
        return "scope+decline"
    return "scope"


async def audit_session(
    db, release, session: dict, archive, ids: dict[str, int], teams: dict[str, str], values
) -> dict:
    state: dict[str, Any] = {}
    records = []
    for index, turn in enumerate(session["turns"], start=1):
        expectation = expectation_for(turn, archive, ids, teams)
        tools = AnalystTools(db, release, turn["question"], release.season, clone(state))
        await tools.prepare()
        assert tools.scope is not None
        actual_scope = tools.scope.model_dump(mode="json")
        carried = list(tools.claims.values())
        calls = prefetch_calls(tools)
        results = [await tools.execute(call) for call in calls]
        recovery: ToolCall | None = None
        if not any(result.claims for result in results):
            # analyst_delivery.fallback runs one recovery lookup when a turn has no claims.
            spec = recovery_tool(
                "discovery"
                if re_search_discovery(tools.question)
                else "player"
                if tools.scope.player_ids
                else "team"
            )
            recovery = ToolCall(
                name=spec.name,
                question=tools.question,
                aggregation=spec.recovery_aggregation,
            )
            results.append(await tools.execute(recovery))
        fake = FakeLoop(tools, results)
        claims = fallback_claims(fake)
        text = " ".join(claim.statement for claim in claims) or decline_text(fake)
        case = expectation_case(expectation)
        checks = expectation_checks(text, expectation, teams)
        response = {
            "answer": text,
            "citations": citations_for(claims),
            "llm_validated": True,
            "warnings": [],
            "refused": False,
        }
        score = score_response(
            case,
            response,
            universe=values.universe,
            archive=values.archive,
            scoped=scoped(text, case, values),
            strict=True,
        )
        expected_ok = bool(
            checks.get("decline")
            or checks.get("record_ok")
            or checks.get("fact_ok")
            or checks.get("value_ok")
        )
        if expectation.kind == "decline":
            expected_ok = score["checks"]["declined"]
        scope_issues = (
            []
            if expectation.kind == "decline"
            else compare_scope(actual_scope, expectation.scope, archive)
        )
        records.append(
            {
                "turn": index,
                "question": turn["question"],
                "kind": expectation.kind,
                "expected_fact": expectation.fact,
                "expected_scope": expectation.scope,
                "actual_scope": actual_scope,
                "scope_issues": scope_issues,
                "carried_claims": [
                    {
                        "metric": claim.metric_id,
                        "season_type": claim.season_type,
                        "games": len(claim.game_ids or []),
                    }
                    for claim in carried
                ],
                "prefetch": [
                    {
                        "tool": call.name,
                        "aggregation": call.aggregation,
                        "status": result.status,
                        "claims": len(result.claims),
                    }
                    for call, result in zip(calls, results, strict=False)
                ],
                "recovery": (
                    {
                        "tool": recovery.name,
                        "aggregation": recovery.aggregation,
                        "status": results[-1].status,
                        "claims": len(results[-1].claims),
                    }
                    if recovery
                    else None
                ),
                "fallback_text": text,
                "fallback_checks": checks,
                "fallback_score": score,
                "fallback_ok": expected_ok and score["meets_expectation"],
                "cause": classify(turn, scope_issues, expected_ok, score["checks"]["declined"]),
            }
        )
        state = committed_state(tools, claims)
    return {
        "id": session["id"],
        "category": session.get("category"),
        "turns": records,
        "pass": all(record["fallback_ok"] for record in records),
        "scope_clean": all(not record["scope_issues"] for record in records),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, default=SESSIONS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--session", action="append", default=[])
    args = parser.parse_args()
    sessions = load_sessions(args.sessions)
    if args.session:
        wanted = set(args.session)
        sessions = [session for session in sessions if session["id"] in wanted]
    values, ids, teams = await oracle()
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active", DatasetRelease.validation_passed.is_(True)
                )
            )
        ).scalar_one()
        results = [
            await audit_session(db, release, session, values.archive, ids, teams, values)
            for session in sessions
        ]
    out = {
        "mode": "offline_backend_fallback",
        "release": release.version,
        "sessions": results,
        "summary": {
            "sessions": len(results),
            "sessions_pass": sum(session["pass"] for session in results),
            "sessions_scope_clean": sum(session["scope_clean"] for session in results),
            "turns": sum(len(session["turns"]) for session in results),
            "turns_pass": sum(
                record["fallback_ok"] for session in results for record in session["turns"]
            ),
            "turns_scope_clean": sum(
                not record["scope_issues"] for session in results for record in session["turns"]
            ),
        },
    }
    out["causes"] = {}
    for session in results:
        for record in session["turns"]:
            if record["cause"] != "ok":
                out["causes"].setdefault(record["cause"], []).append(
                    {
                        "session": session["id"],
                        "turn": record["turn"],
                        "question": record["question"],
                        "issues": record["scope_issues"],
                    }
                )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    for session in results:
        marks = " ".join("ok" if record["cause"] == "ok" else "FAIL" for record in session["turns"])
        print(f"{session['id']}: {marks}")
    print(json.dumps(out["summary"]))
    print(json.dumps({key: len(value) for key, value in out["causes"].items()}))


if __name__ == "__main__":
    asyncio.run(main())
