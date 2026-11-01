"""Check a local production-profile API against an approved archive bundle.

This sends factual analyst turns but never deploys, approves content, changes
basketball data, or calls a provider directly. Run the API with provider keys
empty and a dedicated Redis database. Results do not replace release approval.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def worktree_sha256() -> str:
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--modified", "--deleted", "--others", "--exclude-standard", "-z"]
        )
        .decode()
        .split("\0")
    )
    digest = hashlib.sha256()
    snapshot = Path("docs/release-evidence/readiness-20261028.json")
    for relative in sorted(path for path in paths if path and path != str(snapshot)):
        digest.update(relative.encode())
        digest.update(b"\0")
        path = Path(relative)
        digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
        digest.update(b"\0")
    return digest.hexdigest()


async def run(args: argparse.Namespace) -> dict:
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "scope": "Local production-profile HTTP smoke with optional providers disabled. "
        "Not a retrieval evaluation, provider evaluation, or deployment approval.",
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "worktree_sha256": worktree_sha256(),
        "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "bundle_sha256": args.sha256,
        "checks": [],
        "passed": False,
    }
    checks = report["checks"]

    def verify(name: str, condition: bool, evidence: object) -> None:
        checks.append({"name": name, "passed": condition, "evidence": evidence})
        if not condition:
            raise RuntimeError(f"Readiness check failed: {name}")

    try:
        if urlsplit(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("This command only targets a local API with providers disabled")
        compressed = args.bundle.read_bytes()
        verify(
            "bundle_identity",
            hashlib.sha256(compressed).hexdigest() == args.sha256,
            str(args.bundle),
        )
        bundle = json.loads(gzip.decompress(compressed))
        version = bundle["manifest"]["version"]
        canonical = bundle["data"]
        games = {game["nba_game_id"]: game for game in canonical["games"]}
        headers = {"X-Forwarded-Proto": "https"} if args.local_https_proxy else {}
        async with httpx.AsyncClient(
            base_url=args.base_url,
            headers=headers,
            timeout=35,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get("/health/ready")
            ready = response.json()
            verify("ready", response.status_code == 200 and ready["data_version"] == version, ready)
            verify(
                "providers_disabled",
                ready["optional_dependencies"].get("qdrant") == "disabled"
                and ready["optional_dependencies"].get("openrouter") in {"disabled", "degraded"},
                ready["optional_dependencies"],
            )
            status = await client.get("/archive/status")
            status.raise_for_status()
            archive = status.json()
            verify(
                "archive_identity",
                archive["data_version"] == version
                and archive["games"] == len(games)
                and archive["reports"] == len(canonical["reports"]),
                archive,
            )
            response = await client.get("/games", params={"season": "2025-26", "limit": 200})
            response.raise_for_status()
            served = response.json()
            fields = (
                "nba_game_id",
                "game_date",
                "home_team_id",
                "away_team_id",
                "home_score",
                "away_score",
                "season_type",
            )
            verify(
                "canonical_schedule",
                len(served) == len(games)
                and {game["nba_game_id"] for game in served} == set(games)
                and all(
                    all(game[key] == games[game["nba_game_id"]][key] for key in fields)
                    for game in served
                ),
                {"games_compared": len(served)},
            )
            ids = {game["nba_game_id"]: game["id"] for game in served}
            first = canonical["games"][0]
            game_id = ids[first["nba_game_id"]]
            response = await client.get(f"/games/{game_id}/box-score")
            response.raise_for_status()
            points = {team["team_id"]: team["points"] for team in response.json()["teams"]}
            verify(
                "box_score",
                points
                == {
                    first["home_team_id"]: first["home_score"],
                    first["away_team_id"]: first["away_score"],
                },
                points,
            )
            response = await client.get("/reports", params={"limit": 200})
            response.raise_for_status()
            reports = response.json()
            expected = {ids[row["nba_game_id"]]: row for row in canonical["reports"]}
            verify(
                "report_population",
                len(reports) == len(expected)
                and {row["game_id"] for row in reports} == set(expected),
                {"reports": len(reports)},
            )
            for row in reports:
                response = await client.get(f"/reports/{row['id']}")
                response.raise_for_status()
                body = response.json()
                keys = ("title", "summary", "turning_point", "best_stretch", "worst_stretch")
                if not all(body[key] == expected[row["game_id"]][key] for key in keys):
                    raise RuntimeError(f"Report {row['id']} differs from approved content")
            verify("approved_report_content", True, {"reports_compared": len(reports)})
            for path in ("/docs", "/openapi.json", "/jobs", "/health/rag"):
                response = await client.get(path)
                verify(f"private_route:{path}", response.status_code == 404, response.status_code)
            response = await client.post("/reports/postgame", json={})
            verify("write_route_disabled", response.status_code in {404, 405}, response.status_code)
            payload = {
                "question": "What was the Knicks record this season?",
                "season": "2025-26",
                "turn_id": "readiness-" + uuid.uuid4().hex,
                "expected_revision": 0,
            }
            response = await client.post("/analysis/query", json=payload)
            response.raise_for_status()
            answer = response.json()
            wins = sum(
                (game["home_score"] > game["away_score"]) == (game["home_team_id"] == "NYK")
                for game in games.values()
            )
            values = {
                citation.get("metadata", {}).get("claim", {}).get("metric_id"): citation.get(
                    "metadata", {}
                )
                .get("claim", {})
                .get("value")
                for citation in answer.get("citations", [])
            }
            verify(
                "canonical_analyst_record",
                values.get("wins") == wins
                and values.get("losses") == len(games) - wins
                and answer.get("data_version") == version
                and not answer.get("llm_validated"),
                {"answer": answer.get("answer"), "cited_values": values},
            )
            verify(
                "session_committed",
                answer.get("state_committed") is True and answer.get("revision") == 1,
                {"revision": answer.get("revision")},
            )
            payload["session_token"] = answer["session_token"]
            replay = await client.post("/analysis/query", json=payload)
            verify(
                "turn_replay",
                replay.status_code == 200 and replay.json() == answer,
                {"status": replay.status_code},
            )
            conflict = await client.post(
                "/analysis/query", json={**payload, "question": "Changed turn"}
            )
            verify("turn_conflict", conflict.status_code == 409, conflict.status_code)
            invalid = await client.post("/analysis/query", json={"question": ""})
            verify("invalid_request", invalid.status_code == 422, invalid.status_code)
            verify(
                "security_headers",
                response.headers.get("x-content-type-options") == "nosniff"
                and response.headers.get("x-frame-options") == "DENY"
                and "max-age=" in response.headers.get("strict-transport-security", ""),
                {
                    key: response.headers.get(key)
                    for key in (
                        "x-content-type-options",
                        "x-frame-options",
                        "strict-transport-security",
                    )
                },
            )
        report["passed"] = True
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-https-proxy", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
