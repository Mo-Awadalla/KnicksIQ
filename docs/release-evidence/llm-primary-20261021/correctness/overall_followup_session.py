"""Same API session follow-ups must move between phases: 53-29 regular, 69-32 overall, 16-3 playoffs.

Real provider, in-process app, local restored release. Each session sends the turns in order with
the session token, revision and `context` history the web client sends. Writes
overall_followup_session.json with every trial.

    uv run --package knicksiq-api python \
      docs/release-evidence/llm-primary-20261021/correctness/overall_followup_session.py --trials 3
"""

import argparse
import asyncio
import json
import os
import re
import uuid
from pathlib import Path

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")
os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_DAY", "1000000")

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

SESSIONS = {
    "implicit_then_overall": [("What was the Knicks' record?", "53-29"), ("And overall?", "69-32")],
    "explicit_then_overall": [
        ("What was their regular-season record?", "53-29"),
        ("And overall?", "69-32"),
    ],
    "overall_then_playoffs": [
        ("What was their regular-season record?", "53-29"),
        ("And overall?", "69-32"),
        ("And in the playoffs?", "16-3"),
    ],
}


def records_in(answer: str) -> list[str]:
    """Records as "W-L", or as the fallback's "wins: W over N ... losses: L over N"."""
    found = re.findall(r"\b\d{1,2}-\d{1,2}\b", answer)
    wins = re.search(r"\bwins: (\d+) over", answer)
    losses = re.search(r"\blosses: (\d+) over", answer)
    if wins and losses:
        found.append(f"{wins[1]}-{losses[1]}")
    return found


async def run_session(client: AsyncClient, turns_spec: list[tuple[str, str]]) -> dict:
    turns, token, revision, history = [], None, 0, []
    for question, want in turns_spec:
        response = await client.post(
            "/analysis/query",
            json={
                "question": question,
                "season": "2025-26",
                "turn_id": uuid.uuid4().hex,
                "session_token": token,
                "expected_revision": revision,
                "context": history,
            },
        )
        body = response.json()
        answer = body.get("answer") or ""
        records = records_in(answer)
        turns.append(
            {
                "question": question,
                "status": response.status_code,
                "want": want,
                "records_in_answer": records,
                "ok": want in records,
                "llm_validated": body.get("llm_validated"),
                "revision": body.get("revision"),
                "answer": answer,
            }
        )
        token, revision = body.get("session_token"), body.get("revision", revision)
        history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    revisions = [t["revision"] for t in turns]
    same_session = revisions == list(range(1, len(turns) + 1))
    return {
        "same_session": same_session,
        "pass": same_session and all(t["ok"] for t in turns),
        "turns": turns,
    }


async def main(trials: int) -> None:
    app = create_app()
    results: dict[str, list[dict]] = {name: [] for name in SESSIONS}
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=90
        ) as client:
            for _ in range(trials):
                for name, spec in SESSIONS.items():
                    results[name].append(await run_session(client, spec))
    summary = {
        name: f"{sum(r['pass'] for r in runs)}/{len(runs)}" for name, runs in results.items()
    }
    out = {"summary": summary, "sessions": results}
    Path(__file__).with_suffix(".json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(summary))
    for name, runs in results.items():
        for run in runs:
            print(name, [t["records_in_answer"] for t in run["turns"]], run["pass"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    asyncio.run(main(parser.parse_args().trials))
