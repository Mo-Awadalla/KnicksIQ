"""Manual Render deployment of a gated commit with coordinated restoration.

The owner-controlled approval digest must match the entire input record. No
network mutation occurs before the evidence gate and rollback snapshot match.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from app.core.db import AsyncSessionLocal
from app.models.dataset_release import DatasetRelease
from app.services.qdrant_client import get_qdrant_client, switch_aliases
from app.services.release_evidence import sha256, validate_record
from sqlalchemy import select, update


def render_request(path: str, payload: dict | None = None) -> Any:
    request = urllib.request.Request(
        "https://api.render.com/v1/" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["RENDER_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def wait_deploy(service: str, deployment: str) -> dict:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        value = render_request(f"services/{service}/deploys/{deployment}")
        if value["status"] == "live":
            return value
        if value["status"] in {"build_failed", "update_failed", "canceled", "deactivated"}:
            raise RuntimeError(f"Deployment {deployment} failed")
        time.sleep(5)
    raise TimeoutError(f"Deployment {deployment} did not become live")


async def dataset_version() -> str:
    async with AsyncSessionLocal() as db:
        release = (
            await db.execute(
                select(DatasetRelease).where(
                    DatasetRelease.status == "active",
                    DatasetRelease.validation_passed.is_(True),
                )
            )
        ).scalar_one()
        return release.version


async def activate(version: str) -> None:
    async with AsyncSessionLocal() as db, db.begin():
        release = (
            await db.execute(
                select(DatasetRelease)
                .where(
                    DatasetRelease.version == version,
                    DatasetRelease.validation_passed.is_(True),
                )
                .with_for_update()
            )
        ).scalar_one()
        await db.execute(
            update(DatasetRelease)
            .where(
                DatasetRelease.status == "active",
                DatasetRelease.id != release.id,
            )
            .values(status="superseded")
        )
        release.status = "active"


def aliases() -> dict[str, str]:
    return {a.alias_name: a.collection_name for a in get_qdrant_client().get_aliases().aliases}


def smoke(api_url: str, web_url: str, expected_version: str) -> None:
    for url in [web_url, api_url + "/health/ready", api_url + "/archive/status"]:
        with urllib.request.urlopen(url, timeout=60) as response:
            body = response.read()
            if url.endswith("/archive/status"):
                if json.loads(body)["data_version"] != expected_version:
                    raise RuntimeError("Deployed archive version does not match")
    request = urllib.request.Request(
        api_url + "/analysis/query",
        data=json.dumps(
            {
                "question": "How many games did the Knicks win?",
                "season": "2025-26",
                "context": [],
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        answer = json.load(response)
        if (
            not answer.get("answer")
            or answer.get("refused")
            or answer.get("data_version") != expected_version
        ):
            raise RuntimeError("Analyst smoke failed")


def deploy(record: dict, save, request=render_request, wait=wait_deploy, smoke_check=smoke) -> None:
    services = record["services"]
    rollback = record["rollback"]
    changed: list[str] = []
    record["rollout"] = {"status": "starting", "restoration_failures": []}
    try:
        for name in ("api", "web"):
            changed.append(name)  # Record uncertain network outcomes before issuing mutations.
            save(record)
            value = request(
                f"services/{services[name]['id']}/deploys", {"commitId": record["tested_commit"]}
            )
            record["deployments"][name] = value["id"]
            save(record)
            deployed = wait(services[name]["id"], value["id"])
            if deployed.get("commit", {}).get("id") != record["tested_commit"]:
                raise RuntimeError("Render deployed a different commit")
        candidate = record.get("candidate", {})
        if candidate.get("data_version") and candidate["data_version"] != rollback["data_version"]:
            changed.append("data")
            save(record)
            asyncio.run(activate(candidate["data_version"]))
        if candidate.get("aliases") and candidate["aliases"] != rollback["qdrant_aliases"]:
            changed.append("aliases")
            save(record)
            # No new alias names are allowed: the captured mapping must restore every alias.
            if set(candidate["aliases"]) != set(rollback["qdrant_aliases"]):
                raise RuntimeError("Candidate aliases differ from rollback alias set")
            switch_aliases(candidate["aliases"])
        smoke_check(
            services["api"]["url"],
            services["web"]["url"],
            candidate.get("data_version") or rollback["data_version"],
        )
        record["rollout"]["status"] = "live"
        save(record)
    except Exception as exc:
        record["rollout"]["status"] = "restoring"
        record["rollout"]["failure_type"] = type(exc).__name__
        save(record)
        for component in reversed(changed):
            try:
                if component == "aliases":
                    switch_aliases(rollback["qdrant_aliases"])
                    if aliases() != rollback["qdrant_aliases"]:
                        raise RuntimeError("Alias restoration mismatch")
                elif component == "data":
                    asyncio.run(activate(rollback["data_version"]))
                    if asyncio.run(dataset_version()) != rollback["data_version"]:
                        raise RuntimeError("Dataset restoration mismatch")
                else:
                    # A timed-out create request may still be building remotely. Cancel
                    # all in-flight attempts for this tested commit before restoration.
                    try:
                        attempts = request(
                            f"services/{services[component]['id']}/deploys?limit=20", None
                        )
                        for attempt in attempts:
                            deployment = attempt["deploy"]
                            if deployment.get("commit", {}).get("id") == record[
                                "tested_commit"
                            ] and deployment["status"] in {
                                "created",
                                "build_in_progress",
                                "pre_deploy_in_progress",
                                "update_in_progress",
                                "queued",
                            }:
                                request(
                                    f"services/{services[component]['id']}/deploys/{deployment['id']}/cancel",
                                    {},
                                )
                    except Exception as cancellation:
                        record["rollout"]["restoration_failures"].append(
                            {
                                "component": component,
                                "stage": "cancel_pending",
                                "error_type": type(cancellation).__name__,
                            }
                        )
                    result = request(
                        f"services/{services[component]['id']}/rollback",
                        {"deployId": rollback[component + "_deployment"]},
                    )
                    wait(services[component]["id"], result["id"])
            except Exception as restoration:
                record["rollout"]["restoration_failures"].append(
                    {
                        "component": component,
                        "error_type": type(restoration).__name__,
                    }
                )
                # Continue restoring other components even when one restoration fails.
            save(record)
        record["rollout"]["status"] = (
            "restoration_failed" if record["rollout"]["restoration_failures"] else "restored"
        )
        save(record)
        raise RuntimeError(
            "Promotion stopped; inspect rollout evidence and alert the owner"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--tested-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    failures = validate_record(record, Path.cwd())
    if sha256(args.record) != os.environ.get("RELEASE_OWNER_APPROVAL_SHA256"):
        failures.append("owner-controlled approval digest does not match record")
    commit = subprocess.check_output(
        ["git", "-C", str(args.tested_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != record.get("tested_commit"):
        failures.append("checked-out commit does not match tested commit")
    if failures:
        raise SystemExit("\n".join(failures))
    for name in ("api", "web"):
        service_id = record["services"][name]["id"]
        service = render_request(f"services/{service_id}")
        if service.get("autoDeploy") not in ("no", False):
            raise SystemExit("Automatic deployments must be disabled")
        deployed = render_request(f"services/{service_id}/deploys?limit=20")
        live = [item["deploy"]["id"] for item in deployed if item["deploy"]["status"] == "live"]
        if live != [record["rollback"][name + "_deployment"]]:
            raise SystemExit("Application rollback snapshot is stale")
    if asyncio.run(dataset_version()) != record["rollback"]["data_version"]:
        raise SystemExit("Dataset rollback snapshot is stale")
    if aliases() != record["rollback"]["qdrant_aliases"]:
        raise SystemExit("Alias rollback snapshot is stale")
    deploy(record, lambda value: args.record.write_text(json.dumps(value, indent=2) + "\n"))


if __name__ == "__main__":
    main()
