"""Verify the isolated local Docker stack through real HTTP; retain restart receipts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

VERSION = "2025-26.20260928.1"
BUNDLE_SHA256 = "549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b"
DETERMINISTIC_WARNING = "Model or budget unavailable."


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def local_origin(value: str) -> str:
    parsed = urlsplit(value)
    require(
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment,
        "Verification requires a literal loopback HTTP origin with no credentials or path",
    )
    return value.rstrip("/")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Probe:
    def __init__(self, observations: list[dict]):
        self.observations = observations
        self.client = build_opener(ProxyHandler({}), NoRedirects())

    def request(self, name: str, url: str, payload: dict | None = None, status: int = 200):
        request = Request(
            url,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        started = time.monotonic()
        observation = {"name": name, "url": url, "method": request.method, "request": payload}
        self.observations.append(observation)
        try:
            try:
                response = self.client.open(request, timeout=40)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read()
                observation["status"] = response.code
                observation["response"] = json.loads(raw)
                observation["request_id"] = response.headers.get("X-Request-ID")
            require(observation["status"] == status, f"{name}: expected HTTP {status}")
            return observation["response"]
        except Exception as error:
            observation["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            observation["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)


def committed(body: dict, revision: int) -> None:
    require(body.get("state_committed") is True, "Redis did not commit conversation state")
    require(body.get("revision") == revision, "Unexpected committed session revision")
    token = body.get("session_token", "")
    require(
        len(token) == 64 and all(c in "0123456789abcdef" for c in token), "Invalid session token"
    )
    require(body.get("data_version") == VERSION, "Analyst used the wrong archive")
    require(not body.get("llm_validated"), "Probe unexpectedly used a validated model answer")
    if body.get("degraded"):
        require(
            body.get("route") == "factual_fallback"
            and body.get("warnings") == [DETERMINISTIC_WARNING]
            and bool(body.get("citations"))
            and body.get("refused") is False,
            "Analyst degraded beyond the expected deterministic factual fallback",
        )


def preflight(probe: Probe, api: str, web: str) -> None:
    for name, origin in (("direct API readiness", api), ("web proxy readiness", web + "/api")):
        ready = probe.request(name, origin + "/health/ready")
        require(ready.get("status") == "ready", f"{name}: service is not ready")
        require(ready.get("data_version") == VERSION, f"{name}: wrong release")
        optional = ready.get("optional_dependencies", {})
        require(optional.get("redis") == "configured", f"{name}: Redis is not configured")
        require(optional.get("openrouter") == "disabled", f"{name}: OpenRouter must be disabled")
        require(optional.get("qdrant") == "disabled", f"{name}: vector service must be disabled")
    archive = probe.request("archive status", web + "/api/archive/status")
    require(archive.get("data_version") == VERSION, "Archive status used the wrong release")
    require(archive.get("games") == 101 and archive.get("reports") == 101, "Incomplete archive")
    games = probe.request("games page", web + "/api/games?limit=1")
    require(isinstance(games, list) and len(games) == 1, "Games page is empty")
    game = probe.request("game detail", web + f"/api/games/{games[0]['id']}")
    require(game.get("id") == games[0]["id"], "Game detail does not match the archive list")
    reports = probe.request("reports page", web + "/api/reports?limit=1")
    require(isinstance(reports, list) and len(reports) == 1, "Reports page is empty")
    report = probe.request("report detail", web + f"/api/reports/{reports[0]['id']}")
    require(report.get("id") == reports[0]["id"], "Report detail does not match the archive list")


def initial(probe: Probe, endpoint: str, run_id: str) -> dict:
    question = "What was the Knicks score against Cleveland on 2025-10-22?"
    payload = {"question": question, "turn_id": run_id + "-first", "expected_revision": 0}
    first = probe.request("committed dated answer", endpoint, payload)
    committed(first, 1)
    require(bool(first.get("citations")), "Dated answer is missing citations")
    require("119" in first.get("answer", "") and "111" in first["answer"], "Wrong dated score")
    replay = probe.request("exact turn replay", endpoint, payload)
    require(replay == first, "Repeated turn did not return the exact committed response")
    probe.request(
        "changed input conflict",
        endpoint,
        {**payload, "question": "What was the score against Boston?"},
        status=409,
    )
    missing = probe.request(
        "unbound game reference",
        endpoint,
        {"question": "How did JB play in that game?", "turn_id": run_id + "-missing"},
    )
    committed(missing, 1)
    require(missing.get("answer") == "Which game?", "Unbound game reference was not clarified")
    followup = probe.request(
        "bound game reference",
        endpoint,
        {
            "question": "How did JB play in that game?",
            "turn_id": run_id + "-followup",
            "session_token": first["session_token"],
            "expected_revision": 1,
            "context": [
                {"role": "user", "content": question},
                {"role": "assistant", "content": first["answer"][:2000]},
            ],
        },
    )
    committed(followup, 2)
    require(followup.get("route") != "clarification", "Committed game reference lost its game")
    require(bool(followup.get("citations")), "Bound game reference has no citations")
    require("Brunson" in followup.get("answer", ""), "Bound reference lost the player")
    probe.request(
        "stale revision conflict",
        endpoint,
        {
            "question": question,
            "turn_id": run_id + "-stale",
            "session_token": first["session_token"],
            "expected_revision": 0,
        },
        status=409,
    )
    return {"request": payload, "response": first}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-origin", default="http://127.0.0.1:18000")
    parser.add_argument("--web-origin", default="http://127.0.0.1:18080")
    parser.add_argument("--output", type=Path, required=True, help="New artifact directory")
    parser.add_argument("--phase", choices=("initial", "replay"), default="initial")
    parser.add_argument("--receipt", type=Path, help="Initial verification.json for restart replay")
    args = parser.parse_args()
    api, web = local_origin(args.api_origin), local_origin(args.web_origin)
    if args.phase == "replay" and args.receipt is None:
        parser.error("--receipt is required for the replay phase")
    args.output.mkdir(parents=True, exist_ok=False)
    artifact = {
        "schema_version": 1,
        "scope": "Local container check; hosted and provider release gates remain open",
        "deterministic_mode_limitation": (
            "The evidence loop marks cited factual_fallback answers degraded when models are "
            "disabled. Only the exact warning 'Model or budget unavailable.' is accepted; "
            "other dependency degradation fails this probe. No paid-provider quality is tested."
        ),
        "started_at": datetime.now(UTC).isoformat(),
        "argv": sys.argv,
        "phase": args.phase,
        "run_id": "local-docker-" + uuid.uuid4().hex,
        "api_origin": api,
        "web_origin": web,
        "expected_release": VERSION,
        "expected_bundle_sha256": BUNDLE_SHA256,
        "status": "failed",
        "observations": [],
    }
    probe = Probe(artifact["observations"])
    try:
        preflight(probe, api, web)
        endpoint = web + "/api/analysis/query"
        if args.phase == "initial":
            artifact["restart_receipt"] = initial(probe, endpoint, artifact["run_id"])
        else:
            previous = json.loads(args.receipt.read_text())
            require(previous.get("status") == "passed", "Initial verification did not pass")
            require(previous.get("phase") == "initial", "Receipt is not from an initial probe")
            require(previous.get("web_origin") == web, "Receipt belongs to another local stack")
            receipt = previous["restart_receipt"]
            replay = probe.request(
                "exact replay after container restart", endpoint, receipt["request"]
            )
            require(replay == receipt["response"], "Redis lost or changed the committed response")
            artifact["initial_receipt"] = str(args.receipt.resolve())
        artifact["status"] = "passed"
    except Exception as error:
        artifact["error"] = f"{type(error).__name__}: {error}"
    finally:
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        path = args.output / "verification.json"
        try:
            with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
                json.dump(artifact, output, indent=2)
                output.write("\n")
        except Exception as error:
            artifact["status"] = "failed"
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "verification_error": artifact.get("error"),
                        "artifact_error": f"{type(error).__name__}: {error}",
                        "artifact": str(path),
                    }
                ),
                file=sys.stderr,
            )
        print(json.dumps({"status": artifact["status"], "artifact": str(path.resolve())}))
    if artifact["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
