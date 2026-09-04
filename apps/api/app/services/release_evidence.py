"""Fail-closed release evidence gate and generated owner review view.

Run: python -m app.services.release_evidence PATH [--render]
This command never deploys, approves evidence, or promotes retrieval aliases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MINIMUMS = {
    "semantic_recall_at_5": 0.95,
    "exact_numeric_correctness": 1.0,
    "canonical_entity_correctness": 1.0,
    "citation_correctness": 0.95,
    "paraphrase_success": 0.95,
    "correct_abstention_rate": 1.0,
}
REQUIRED_CHECKS = (
    "active_archive_identity",
    "report_audit",
    "retrieval_targets",
    "retrieval_filters",
    "evaluation",
    "evaluation_services_disabled",
    "production_router_contracts",
    "backend",
    "frontend",
    "migrations_loader",
    "security",
    "desktop_mobile_keyboard",
    "accessibility",
    "warm_load",
    "shadow_dependencies",
    "rollback_snapshot",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_record(record: dict[str, Any], root: Path) -> list[str]:
    failures = []
    commit = record.get("tested_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        failures.append("missing exact tested Git commit")
    if (
        record.get("configuration", {}).get("answer_mode") != "shadow"
        or record.get("configuration", {}).get("shadow_sample_rate") != 0.1
    ):
        failures.append("requires 10% shadow mode with deterministic delivered answers")
    for name in ("data", "bundle", "evaluation"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("hashes", {}).get(name, ""))):
            failures.append(f"missing {name} hash")
    evidence = record.get("checks", {})
    for name in REQUIRED_CHECKS:
        item = evidence.get(name, {})
        if item.get("status") != "passed" or item.get("tested_commit") != commit:
            failures.append(f"{name}: missing passing evidence for tested commit")
            continue
        path = root / str(item.get("path", ""))
        if not path.is_file() or sha256(path) != item.get("sha256"):
            failures.append(f"{name}: evidence content hash mismatch or missing file")
    for mode in ("evaluation", "evaluation_services_disabled"):
        metrics = evidence.get(mode, {}).get("metrics", {})
        for name, minimum in MINIMUMS.items():
            # Semantic retrieval is deliberately unavailable in service-disabled evaluation.
            if mode == "evaluation_services_disabled" and name == "semantic_recall_at_5":
                continue
            value = metrics.get(name)
            if not isinstance(value, (int, float)) or not minimum <= value <= 1:
                failures.append(f"{mode}: {name} must be >= {minimum}")
        if metrics.get("query_count") != 120 or metrics.get("missing_labels") != 0:
            failures.append(f"{mode}: all 120 reviewed labels required")
        if mode == "evaluation" and metrics.get("missing_ranked_traces") != 0:
            failures.append("evaluation: missing ranked retrieval traces")
    load = evidence.get("warm_load", {}).get("metrics", {})
    if not (
        load.get("concurrency") == 10
        and 0 < load.get("archive_p95_ms", 1000) < 1000
        and 0 < load.get("analyst_p95_ms", 4000) < 4000
        and 0 <= load.get("error_rate", 1) < 0.01
    ):
        failures.append("warm latency/concurrency/error gates not met")
    accessibility = evidence.get("accessibility", {}).get("metrics", {})
    if accessibility.get("serious") != 0 or accessibility.get("critical") != 0:
        failures.append("accessibility: zero serious/critical findings required")
    for name in ("template", "exceptions", "report_audit", "evaluation_labels", "launch"):
        approval = record.get("approvals", {}).get(name, {})
        path = root / str(approval.get("path", ""))
        if (
            not approval.get("owner")
            or not approval.get("approved_at")
            or not path.is_file()
            or sha256(path) != approval.get("sha256")
        ):
            failures.append(f"{name}: missing owner approval bound to content")
    rollback = record.get("rollback", {})
    if not all(
        rollback.get(key)
        for key in ("api_deployment", "web_deployment", "data_version", "qdrant_aliases")
    ):
        failures.append("missing coordinated rollback targets")
    return failures


def render(record: dict[str, Any], failures: list[str]) -> str:
    return "\n".join(
        [
            "# Release evidence",
            "",
            f"Record: `{record['id']}`",
            f"Tested commit: `{record.get('tested_commit') or 'unverified'}`",
            f"Deployment gate: **{'BLOCKED' if failures else 'eligible for manual deployment'}**",
            "",
            "Generated from release-record.json; this view is not approval evidence.",
            "",
            *[f"- {failure}" for failure in failures],
            "",
            "Agents verify every report against canonical evidence. The owner",
            "approves the template, exceptions, and final content-hash-bound audit",
            "summary. Reviewed flags do not establish approval; unresolved checks block release.",
            "",
            "Render rebuilds the tested commit. Artifacts are not claimed identical to CI builds.",
            "Rollback coordinates restoration of services, dataset activation and alias mappings;",
            "not atomically. Stop promotion and alert the owner on any restoration failure.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    failures = validate_record(record, args.root)
    if args.render:
        args.record.with_suffix(".md").write_text(render(record, failures))
    print(json.dumps({"eligible": not failures, "failures": failures}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
