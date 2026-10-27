"""Two executions of the SAME turn must not both be reported as committed with different answers.

Real Redis. Turn A begins and its lease expires; the client retries the same turn id and
request (B), which begins, executes and commits. A then commits its own, different answer.
The client must end up with the stored answer, whichever execution reports last.

    REDIS_URL=redis://localhost:56500/13 \
    uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/correctness/same_turn_lease_repro.py
"""

import asyncio
import json
import uuid

from app.services.analyst_sessions import SessionTurn
from app.services.runtime_store import _redis

REQUEST = {"question": "What was their record?", "season": "2025-26"}


def outcome(result):
    """(committed, fresh, stored response); the pre-fix commit returned a bare bool."""
    if isinstance(result, bool):
        return result, result, None
    return result.committed, result.fresh, result.response


async def main() -> None:
    turn_id = uuid.uuid4().hex
    a = await SessionTurn.begin(None, turn_id, 0, REQUEST)
    redis = await _redis()
    assert redis is not None
    await redis.delete(a.key + ":lease")  # A's lease expired while it was still working.
    b = await SessionTurn.begin(None, turn_id, 0, REQUEST)
    b_outcome = await b.commit({"answer": "B answer"}, {"by": "B"})
    a_outcome = await a.commit({"answer": "A answer"}, {"by": "A"})
    stored = json.loads(json.loads(await redis.hget(a.key, "turn:" + turn_id))["response"])[
        "answer"
    ]
    await redis.aclose()
    # What each execution would return to its client.
    a_committed, a_fresh, a_stored = outcome(a_outcome)
    b_committed, _, b_stored = outcome(b_outcome)
    a_reply = (a_stored or {}).get("answer") or "A answer"
    b_reply = (b_stored or {}).get("answer") or "B answer"
    checks = {
        "b_committed": b_committed,
        "a_not_a_fresh_commit": not a_fresh,
        "a_returns_stored_answer": a_committed and a_reply == stored,
        "b_returns_stored_answer": b_reply == stored,
    }
    print(json.dumps({"stored": stored, "a_reply": a_reply, "b_reply": b_reply, "checks": checks}))
    print("PASS" if all(checks.values()) else "FAIL")


asyncio.run(main())
