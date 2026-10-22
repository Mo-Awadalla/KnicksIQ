"""Same API session: regular-season record, then "And overall?" must move 53-29 to 69-32.

Real provider, in-process app, local restored release. Writes overall_followup_session.json.
"""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path

os.environ.setdefault("PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE", "100000")

from app.main import create_app  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

TURNS = [("What was the Knicks' record?", "53-29"), ("And overall?", "69-32")]


async def main() -> None:
    app = create_app()
    turns, token, revision, history = [], None, 0, []
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=90
        ) as client:
            for question, want in TURNS:
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
                records = re.findall(r"\b\d{1,2}-\d{1,2}\b", answer)
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
    same_session = turns[1]["revision"] == turns[0]["revision"] + 1
    out = {"same_session": same_session, "pass": same_session and all(t["ok"] for t in turns)}
    out["turns"] = turns
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in ("same_session", "pass")}))
    for t in turns:
        print(t["question"], t["records_in_answer"], t["llm_validated"], t["revision"])


asyncio.run(main())
