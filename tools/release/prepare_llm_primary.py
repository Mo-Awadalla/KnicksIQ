"""Prepare a local review package without authorizing or executing a release.

Failure inventory, recorded before implementation.
Missing or malformed records and non-repository roots must fail before writes.
Existing output files or symlink destinations must never be overwritten.
Historical checks must retain their original commit and content hashes.
A record for another commit or a dirty candidate must not report readiness.
Missing evidence, failed launch consistency, and invalid validator input must block.
A readiness pass must never imply owner approval or production authorization.
The command must not contact providers, deploy services, or read secret values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict


class PreparationReport(TypedDict):
    schema_version: int
    generated_at: str
    source_commit: str
    source_tree: str
    source_record: dict[str, Any]
    source_dirty_paths: list[str]
    launch_consistency: dict[str, Any]
    readiness: dict[str, Any]
    deployment: dict[str, Any]
    required_checks: list[dict[str, Any]]
    actions: list[str]
    production_promotion_authorized: bool
    artifacts: dict[str, str]


ACTIONS = [
    "Bind every required check to the final clean candidate commit. Preserve historical evidence.",
    "Resolve the 120-case evaluation contract, retain all 50 semantic cases, and bind or obtain "
    "owner approval of the frozen contract hash and scoring rubric.",
    "Run and review primary and services-disabled evaluations against that approved contract.",
    "Verify the intended OpenCode Go runtime, archive identity, dependency recovery, "
    "warm-load limits and coordinated rollback targets on the candidate.",
    "Bind or obtain the required content-bound report approvals. Real-provider evaluation needs "
    "its own authorized budget.",
    "After readiness passes, obtain launch approval and the owner-controlled digest of "
    "the completed release record. Deployment and the pending cutoff change remain separate.",
]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def check_output_directory(path: Path) -> Path:
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("output directory and its ancestors must not be symlinks")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("output directory must be new or empty")
    return path


def dirty_paths(root: Path, output: Path) -> list[str]:
    raw = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        text=True,
        stderr=subprocess.PIPE,
    )
    entries = iter(raw.split("\0"))
    paths = []
    for entry in entries:
        if not entry:
            continue
        names = [entry[3:]]
        if "R" in entry[:2] or "C" in entry[:2]:
            names.append(next(entries))
        for name in names:
            if entry[:2] != "??" or not (root / name).absolute().is_relative_to(output):
                paths.append(name)
    return sorted(set(paths))


def launch_consistency(root: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(root / "tools/release/check_launch_mode_consistency.py"),
        "--root",
        str(root),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        observation = json.loads(result.stdout)
        if not isinstance(observation, dict):
            raise ValueError("checker output must be an object")
        return {"command": command, "exit_code": result.returncode, "observation": observation}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {
            "command": command,
            "exit_code": None,
            "observation": {"status": "fail", "mismatches": [type(exc).__name__]},
        }


def prepare(root: Path, record_path: Path, output: Path) -> tuple[PreparationReport, bytes]:
    root = root.resolve(strict=True)
    if not root.is_dir() or Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("root must be the repository root")
    validator_path = root / "apps/api/app/services/release_evidence.py"
    checker_path = root / "tools/release/check_launch_mode_consistency.py"
    for required in (validator_path, checker_path):
        if not required.is_file() or not required.resolve().is_relative_to(root):
            raise ValueError("root must contain the release validator and launch checker")
    output = check_output_directory(output)
    record_path = record_path if record_path.is_absolute() else root / record_path
    record_bytes = record_path.read_bytes()
    record = json.loads(record_bytes)
    if not isinstance(record, dict):
        raise ValueError("release record must be a JSON object")

    sys.path[:0] = [str(root / "apps/api"), str(root / "packages/basketball-core/src")]
    from app.services import release_evidence

    if Path(release_evidence.__file__).resolve() != validator_path.resolve():
        raise ValueError("release validator must come from the selected checkout")
    readiness_failures = release_evidence.validate_readiness(record, root)
    deployment_failures = release_evidence.validate_record(record, root)
    commit = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    changed = dirty_paths(root, output)
    identity_failures = []
    if record.get("tested_commit") != commit:
        identity_failures.append("release record tested_commit does not match source HEAD")
    if changed:
        identity_failures.append("source checkout has uncommitted changes")
    consistency = launch_consistency(root)
    if consistency["exit_code"] != 0 or consistency["observation"].get("status") != "pass":
        identity_failures.append("launch configuration consistency check failed")
    declared = consistency["observation"].get("render_yaml", {})
    intended = record.get("launch_configuration", {})
    if not intended.get("answer_mode") or declared.get("ANALYSIS_ANSWER_MODE") != intended.get(
        "answer_mode"
    ):
        identity_failures.append("launch record answer mode does not match deployment blueprint")
    if (
        intended.get("analyst_evidence_loop_enabled") is not True
        or declared.get("ANALYST_EVIDENCE_LOOP_ENABLED") != "true"
    ):
        identity_failures.append("launch record evidence loop does not match deployment blueprint")

    checks = []
    for name in release_evidence.REQUIRED_CHECKS:
        item = record.get("checks", {}).get(name, {})
        path = root / str(item.get("path", ""))
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        checks.append(
            {
                "name": name,
                "recorded_status": item.get("status", "missing"),
                "tested_commit": item.get("tested_commit"),
                "matches_source_commit": item.get("tested_commit") == commit,
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "observed_sha256": actual_hash,
                "artifact_matches": actual_hash is not None and actual_hash == item.get("sha256"),
            }
        )
    readiness_failures = [*identity_failures, *readiness_failures]
    deployment_failures = [*identity_failures, *deployment_failures]
    report: PreparationReport = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": commit,
        "source_tree": tree,
        "source_record": {
            "path": str(record_path.resolve()),
            "sha256": hashlib.sha256(record_bytes).hexdigest(),
            "tested_commit": record.get("tested_commit"),
        },
        "source_dirty_paths": changed,
        "launch_consistency": consistency,
        "readiness": {"ready": not readiness_failures, "failures": readiness_failures},
        "deployment": {
            "record_gate_passed": not deployment_failures,
            "failures": deployment_failures,
            "owner_digest_checked": False,
            "live_preflight_checked": False,
        },
        "required_checks": checks,
        "actions": ACTIONS,
        "production_promotion_authorized": False,
        "artifacts": {
            "record": "source-record.json",
            "gates": "gates.json",
            "launch_consistency": "launch-consistency.json",
            "review": "README.md",
        },
    }
    return report, record_bytes


def render_review(report: PreparationReport, root: Path) -> str:
    status = "READY FOR OWNER REVIEW" if report["readiness"]["ready"] else "BLOCKED"
    record = report["source_record"]
    prepare_command = shlex.join(
        [
            "uv",
            "run",
            "--package",
            "knicksiq-api",
            "python",
            "tools/release/prepare_llm_primary.py",
            "--root",
            str(root),
            "--record",
            record["path"],
            "--output-dir",
        ]
    )
    gate_command = shlex.join(
        [
            "uv",
            "run",
            "--package",
            "knicksiq-api",
            "python",
            "-m",
            "app.services.release_evidence",
            record["path"],
            "--root",
            str(root),
            "--readiness",
        ]
    )
    rows = [
        "| Check | Recorded status | Original commit | Current commit | Artifact hash |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in report["required_checks"]:
        values = [
            check["name"],
            check["recorded_status"],
            check["tested_commit"] or "missing",
            "matches" if check["matches_source_commit"] else "does not match",
            "matches" if check["artifact_matches"] else "missing or changed",
        ]
        rows.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    return "\n".join(
        [
            "# LLM-primary release preparation",
            "",
            status,
            "",
            f"The source candidate is `{report['source_commit']}`.",
            f"Its committed tree is `{report['source_tree']}`.",
            f"The source record still names `{record['tested_commit']}`.",
            f"Its SHA-256 is `{record['sha256']}`.",
            "",
            "This package preserves the source record byte-for-byte. Historical evidence keeps",
            "its original identity. No provider evaluation, deployment, approval or cutoff change",
            "runs during preparation. Production promotion is not authorized by this package.",
            "",
            "## Readiness blockers",
            "",
            *[f"- {failure}" for failure in report["readiness"]["failures"]],
            *(
                []
                if report["readiness"]["failures"]
                else ["The preparation readiness checks passed."]
            ),
            "",
            "## Required evidence",
            "",
            *rows,
            "",
            "The table checks artifact identity. The readiness verdict also applies the existing",
            "validator's quality thresholds, frozen contract and approval requirements.",
            "",
            "## Source changes",
            "",
            *(
                [f"- `{path}`" for path in report["source_dirty_paths"]]
                or ["The checkout is clean."]
            ),
            "",
            "## Remaining actions",
            "",
            *[f"{index}. {action}" for index, action in enumerate(report["actions"], 1)],
            "",
            "## Repeat the preparation",
            "",
            "Run from the repository root. Each run needs a new or empty output directory.",
            "",
            "```sh",
            f"cd {shlex.quote(str(root))}",
            'mkdir -p "$PWD/release-artifacts"',
            f"{prepare_command} "
            '"$(mktemp -d "$PWD/release-artifacts/llm-primary-preparation.XXXXXX")"',
            "```",
            "",
            "The command exits 1 when readiness is blocked and 2 for invalid input.",
            "Exit 0 establishes preparation readiness only. The deployment coordinator still",
            "requires the owner-controlled record digest and its live preflight.",
            "",
            "Run the underlying record gate separately with the command below. It evaluates the",
            "record's original commit. The preparation command also checks the current candidate.",
            "",
            "```sh",
            gate_command,
            "```",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--record", type=Path, default=Path("docs/release-evidence/release-record.json")
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report, record_bytes = prepare(args.root, args.record, args.output_dir)
        review = render_review(report, args.root.resolve())
        output = check_output_directory(args.output_dir)
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        subprocess.CalledProcessError,
    ):
        parser.error("invalid repository, release record, or output directory; no package written")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "source-record.json").open("xb") as stream:
        stream.write(record_bytes)
    for name, value in (
        ("gates.json", report),
        ("launch-consistency.json", report["launch_consistency"]),
    ):
        with (output / name).open("x") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
    with (output / "README.md").open("x") as stream:
        stream.write(review)
    print(json.dumps({"ready": report["readiness"]["ready"], "package": str(output)}))
    return 0 if report["readiness"]["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
