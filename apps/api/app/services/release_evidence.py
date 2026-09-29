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
    "shadow_evaluation",
    "rollback_snapshot",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_readiness(record: dict[str, Any], root: Path) -> list[str]:
    failures = []
    commit = record.get("tested_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        failures.append("missing exact tested Git commit")
    if (
        record.get("pre_promotion_configuration", {}).get("answer_mode") != "shadow"
        or record.get("pre_promotion_configuration", {}).get("shadow_sample_rate") != 0.1
        or record.get("pre_promotion_configuration", {}).get("analyst_evidence_loop_enabled")
        is not True
    ):
        failures.append("requires pre-promotion 10% shadow with deterministic delivered answers")
    if (
        record.get("launch_configuration", {}).get("answer_mode") != "llm_primary"
        or record.get("launch_configuration", {}).get("analyst_evidence_loop_enabled") is not True
    ):
        failures.append("requires llm_primary final serving mode")
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
            if type(value) not in (int, float) or not minimum <= value <= 1:
                failures.append(f"{mode}: {name} must be >= {minimum}")
        if metrics.get("query_count") != 120 or metrics.get("missing_labels") != 0:
            failures.append(f"{mode}: all 120 reviewed labels required")
        if mode == "evaluation" and metrics.get("missing_ranked_traces") != 0:
            failures.append("evaluation: missing ranked retrieval traces")
        if metrics.get("semantic_case_count") != 50:
            failures.append(f"{mode}: original 50-case semantic cohort required")
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
    for name in ("template", "exceptions", "report_audit", "evaluation_labels"):
        approval = record.get("approvals", {}).get(name, {})
        path = root / str(approval.get("path", ""))
        if (
            not approval.get("owner")
            or not approval.get("approved_at")
            or not path.is_file()
            or sha256(path) != approval.get("sha256")
        ):
            failures.append(f"{name}: missing owner approval bound to content")
    failures.extend(validate_shadow_stage(record, root))
    rollback = record.get("rollback", {})
    if not all(
        rollback.get(key)
        for key in ("api_deployment", "web_deployment", "data_version", "qdrant_aliases")
    ):
        failures.append("missing coordinated rollback targets")
    return failures


def fixed_case_ids() -> list[str]:
    path = Path(__file__).parents[1] / "evaluation/questions.jsonl"
    return [json.loads(line)["id"] for line in path.read_text().splitlines() if line.strip()]


def evaluation_request_id(expectations_hash: str, mode: str, case_id: str) -> str:
    return hashlib.sha256(f"{expectations_hash}:{mode}:{case_id}".encode()).hexdigest()


def validate_shadow_stage(record: dict[str, Any], root: Path) -> list[str]:
    """Check actual fixed-cohort execution, not a declared configuration or status."""
    item = record.get("checks", {}).get("shadow_evaluation", {})
    try:
        path = root / item["path"]
        if sha256(path) != item["sha256"]:
            raise ValueError("content hash")
        payload = json.loads(path.read_text())
        expected = record.get("hashes", {}).get("evaluation")
        if (
            payload.get("tested_commit") != record.get("tested_commit")
            or payload.get("bundle_sha256") != record.get("hashes", {}).get("bundle")
            or payload.get("expectations_sha256") != expected
            or payload.get("configuration") != record.get("pre_promotion_configuration")
            or payload.get("scope") != "isolated_staging"
            or payload.get("passed") is not True
        ):
            raise ValueError("stage identity/configuration/scope")
        ids = fixed_case_ids()
        unsupported = {
            case["id"]
            for case in (
                json.loads(line)
                for line in (Path(__file__).parents[1] / "evaluation/questions.jsonl")
                .read_text()
                .splitlines()
                if line.strip()
            )
            if case["answerable"] is False and case.get("expected_route") is None
        }
        turns = payload["turns"]
        if payload.get("case_ids") != ids or [t["case_id"] for t in turns] != ids:
            raise ValueError("fixed cohort coverage")
        selected = 0
        for turn in turns:
            request_id = evaluation_request_id(expected, "shadow", turn["case_id"])
            sampled = (
                int.from_bytes(hashlib.sha256(request_id.encode()).digest()[:4], "big")
                / (2**32 - 1)
                < 0.1
            )
            live_refusal = turn["case_id"] in unsupported
            selected += sampled and not live_refusal
            calls = turn.get("model_calls")
            if (
                turn.get("request_id") != request_id
                or turn.get("sampled") is not sampled
                or type(calls) is not int
                or not 0 <= calls <= 6
                or (not sampled and calls != 0)
                or (live_refusal and (calls != 0 or turn.get("model_validated") is not False))
                or (
                    sampled
                    and not live_refusal
                    and (calls == 0 or turn.get("model_validated") is not True)
                )
                or turn.get("delivered_mode") != (None if live_refusal else "factual_fallback")
                or turn.get("refused") is not live_refusal
                or turn.get("state_committed") is not True
                or turn.get("replayed") is not False
                or turn.get("error") is not None
            ):
                raise ValueError("sampling/model execution/delivery")
        if not selected:
            raise ValueError("no sampled model executions")
    except (OSError, KeyError, TypeError, ValueError):
        return ["shadow_evaluation: missing valid bound staged execution evidence"]
    return []


def validate_record(record: dict[str, Any], root: Path) -> list[str]:
    """Deployment gate: readiness plus the existing owner launch sign-off."""
    failures = validate_readiness(record, root)
    approval = record.get("approvals", {}).get("launch", {})
    path = root / str(approval.get("path", ""))
    if (
        not approval.get("owner")
        or not approval.get("approved_at")
        or not path.is_file()
        or sha256(path) != approval.get("sha256")
    ):
        failures.append("launch: missing owner approval bound to content")
    return failures


def validate_deployment_authorization(
    record: dict[str, Any], root: Path, record_path: Path, owner_digest: str | None
) -> list[str]:
    failures = validate_record(record, root)
    if sha256(record_path) != owner_digest:
        failures.append("owner-controlled approval digest does not match record")
    return failures


def render(record: dict[str, Any], failures: list[str], *, readiness: bool = False) -> str:
    return "\n".join(
        [
            "# Release evidence",
            "",
            f"Record: `{record['id']}`",
            f"Tested commit: `{record.get('tested_commit') or 'unverified'}`",
            f"{'Readiness' if readiness else 'Deployment'} gate: **"
            + (
                "BLOCKED"
                if failures
                else (
                    "READY FOR PRODUCTION APPROVAL"
                    if readiness
                    else "eligible for manual deployment"
                )
            )
            + "**",
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
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Check pre-promotion readiness only; never authorizes deployment",
    )
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    failures = (validate_readiness if args.readiness else validate_record)(record, args.root)
    if args.render:
        args.record.with_suffix(".md").write_text(
            render(record, failures, readiness=args.readiness)
        )
    print(json.dumps({"eligible": not failures, "failures": failures}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
