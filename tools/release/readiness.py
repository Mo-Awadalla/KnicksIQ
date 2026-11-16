"""Check a provider-free local API and its actual persisted canonical release rows.

The explicit local database must belong to the listening API process. No public
archive export, stored verification report, or manifest label substitutes for SQL.
This check does not approve provider quality or deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from runtime_mapping import (
    DatasetRelease,
    VerificationError,
    loopback_dsn,
    read_bundle,
    verify_restore,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def api_database_identity(pid: int, base_url: str, dsn: str) -> str:
    """Bind the selected database to the actual local origin listener, not a label."""
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise VerificationError("only a direct loopback API origin is supported")
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise VerificationError("use the direct API origin without credentials, path, or query")
    if pid <= 1:
        raise VerificationError("--api-pid must identify the local API worker")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    listener = subprocess.check_output(
        ["lsof", "-nP", "-a", "-p", str(pid), f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=10,
    ).splitlines()
    addresses = {f"n127.0.0.1:{port}", f"n[::1]:{port}"}
    if f"p{pid}" not in listener or not addresses.intersection(listener):
        raise VerificationError("--api-pid does not own the direct loopback API listener")
    identity = subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "lstart="], text=True, timeout=10
    ).strip()
    if not identity:
        raise VerificationError("the local API process is no longer alive")
    environment = Path(f"/proc/{pid}/environ")
    if environment.exists():
        entries = environment.read_bytes().decode().split("\0")
    else:
        command = subprocess.check_output(
            ["ps", "eww", "-p", str(pid), "-o", "command="], text=True, timeout=10
        )
        entries = command.split()
    selected = {}
    for key in ("DB_URL", "TEST_MODE", "ENVIRONMENT"):
        values = [entry.removeprefix(key + "=") for entry in entries if entry.startswith(key + "=")]
        if len(values) != 1:
            raise VerificationError(f"the API worker requires an explicit unique {key}")
        selected[key] = values[0]
    if (
        selected["TEST_MODE"].lower() not in {"false", "0"}
        or selected["ENVIRONMENT"] != "production"
    ):
        raise VerificationError("the API worker must explicitly use production and TEST_MODE=false")
    if loopback_dsn(selected["DB_URL"]) != loopback_dsn(dsn):
        raise VerificationError(
            "API database does not match --dsn; an explicit DB_URL on the worker is required"
        )
    return identity


async def verify_database(dsn: str, bundle: dict) -> dict:
    """Read one consistent snapshot with PostgreSQL itself enforcing read-only access."""
    engine = create_async_engine(loopback_dsn(dsn))
    try:
        async with engine.connect() as connection, connection.begin():
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                active = (
                    (
                        await session.execute(
                            select(DatasetRelease).where(DatasetRelease.status == "active")
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(active) != 1 or active[0].version != bundle["manifest"]["version"]:
                    raise VerificationError("the bundle must be the database's sole active release")
                verified = await verify_restore(session, bundle)
                if active[0].id != verified.release_id or not verified.counts.get("games"):
                    raise VerificationError("the active release has no verifiable canonical games")
                return {
                    "release_id": verified.release_id,
                    "version": verified.version,
                    "bundle_sha256": verified.bundle_sha256,
                    "collections": verified.counts,
                    "rows_verified": len(verified.rows),
                    "players_verified": len(verified.players),
                    "problems": list(verified.problems),
                    "transaction": "repeatable read, read only",
                }
    finally:
        await engine.dispose()


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
        "scope": "Local production-profile HTTP and canonical SQL row verification. "
        "Optional providers disabled. Not a retrieval evaluation, provider evaluation, "
        "or deployment approval.",
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
        if re.fullmatch(r"[0-9a-f]{64}", args.sha256) is None:
            raise VerificationError("--sha256 must be the original approved bundle SHA-256")
        if urlsplit(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("This command only targets a local API with providers disabled")
        loopback_dsn(args.dsn)
        identity = api_database_identity(args.api_pid, args.base_url, args.dsn)
        bundle = read_bundle(args.bundle, args.sha256)
        verify("bundle_identity", True, args.sha256)
        version = bundle["manifest"]["version"]
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
            database = await verify_database(args.dsn, bundle)
            verify("database_rows", not database["problems"], database)
            verify(
                "api_database_binding",
                api_database_identity(args.api_pid, args.base_url, args.dsn) == identity,
                {"api_pid": args.api_pid, "release_id": database["release_id"]},
            )
            response = await client.get("/health/ready")
            verify(
                "ready_after_rows",
                response.status_code == 200 and response.json()["data_version"] == version,
                response.json(),
            )
            response = await client.get("/health/live")
            verify("live", response.status_code == 200, response.status_code)
            for path in ("/docs", "/openapi.json", "/jobs", "/health/rag"):
                response = await client.get(path)
                verify(f"private_route:{path}", response.status_code == 404, response.status_code)
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
    parser.add_argument("--dsn", required=True, help="explicit loopback PostgreSQL URL")
    parser.add_argument(
        "--api-pid",
        required=True,
        type=int,
        help="local API worker PID, with explicit DB_URL and a direct loopback listener",
    )
    parser.add_argument("--local-https-proxy", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
