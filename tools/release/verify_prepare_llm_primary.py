"""Exercise release preparation through its CLI and preserve a repeatable receipt.

Failure inventory written before verifier implementation.
A blocked historical record must not become ready for a newer candidate.
The source record and its approvals must remain byte-for-byte unchanged.
A blocked result must name failures and never authorize production promotion.
A nonempty output, symlink output, malformed record, or non-repository root must
fail without modifying existing artifacts or creating a partial package.
The selected checkout must own validation even when invoked from another directory.
Launch configuration drift and changed evidence content must remain visible.
A tracked deletion inside the output directory must remain a dirty-source blocker.
Agreeing documentation and blueprint must not hide a mode mismatch with the release record.
A Git repository missing project files must never import a different installed checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARCHIVE_PATHS = (
    "apps/api/app",
    "packages/basketball-core/src",
    "tools/release/check_launch_mode_consistency.py",
    "render.yaml",
    "docs/release-checklist.md",
    "docs/analyst-evidence-loop.md",
    "docs/release-evidence/release-record.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def make_fixture(root: Path, fixture: Path) -> None:
    fixture.mkdir()
    archive = subprocess.check_output(["git", "archive", "HEAD", *ARCHIVE_PATHS], cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(fixture, filter="data")
    for relative in ARCHIVE_PATHS:
        source = root / relative
        if source.is_file():
            shutil.copyfile(source, fixture / relative)
    source_record = root / "docs/release-evidence/release-record.json"
    shutil.copyfile(source_record, fixture / "docs/release-evidence/release-record.json")
    record = json.loads(source_record.read_text())
    for section in ("checks", "approvals"):
        for item in record.get(section, {}).values():
            if not isinstance(item, dict) or not item.get("path"):
                continue
            relative = Path(item["path"])
            source = root / relative
            if not relative.is_absolute() and ".." not in relative.parts and source.is_file():
                destination = fixture / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
    shutil.copyfile(
        root / "tools/release/prepare_llm_primary.py",
        fixture / "tools/release/prepare_llm_primary.py",
    )
    command(["git", "init", "-q"], fixture)
    command(["git", "add", "."], fixture)
    command(
        [
            "git",
            "-c",
            "user.name=Release gate verifier",
            "-c",
            "user.email=release-gate-verifier@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "Isolated CLI fixture",
        ],
        fixture,
    )


def invoke(
    cases: list[dict[str, Any]],
    name: str,
    script: Path,
    root: Path,
    output: Path,
    cwd: Path,
    record: Path | None = None,
) -> dict[str, Any]:
    argv = [sys.executable, str(script), "--root", str(root), "--output-dir", str(output)]
    if record is not None:
        argv.extend(["--record", str(record)])
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "apps/api"), str(root / "packages/basketball-core/src")]
    )
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    case = {
        "name": name,
        "command": argv,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "assertions": [],
    }
    cases.append(case)
    return case


def expect(case: dict[str, Any], name: str, passed: bool) -> None:
    case["assertions"].append({"name": name, "passed": bool(passed)})


def package(output: Path) -> dict[str, Any]:
    path = output / "gates.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def reject(
    cases: list[dict[str, Any]],
    name: str,
    script: Path,
    root: Path,
    output: Path,
    cwd: Path,
    record: Path | None = None,
) -> None:
    case = invoke(cases, name, script, root, output, cwd, record)
    expect(case, "invalid input exits with code 2", case["exit_code"] == 2)
    expect(case, "no partial output directory", not output.exists())


def run(root: Path, output: Path) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    script = root / "tools/release/prepare_llm_primary.py"
    report: dict[str, Any] = {
        "schema_version": 1,
        "observed_at": datetime.now(UTC).isoformat(),
        "source_commit": command(["git", "rev-parse", "HEAD"], root),
        "verifier_sha256": digest(Path(__file__)),
        "preparation_cli_sha256": digest(script),
        "scope": "Local CLI end-to-end checks. No provider evaluation or release approval.",
        "rerun_command": [
            sys.executable,
            str(Path(__file__).resolve()),
            "--root",
            str(root),
            "--output",
            str(output),
        ],
        "cases": cases,
        "passed": False,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="knicksiq-release-gate-e2e-") as temporary:
            workspace = Path(temporary).resolve()
            source = root / "docs/release-evidence/release-record.json"
            source_before = source.read_bytes()
            actual_output = workspace / "actual-package"
            case = invoke(cases, "actual_candidate", script, root, actual_output, workspace)
            actual = package(actual_output)
            expect(case, "historical incomplete record blocks readiness", case["exit_code"] == 1)
            expect(
                case,
                "package binds current source commit",
                actual.get("source_commit") == report["source_commit"],
            )
            expect(case, "source record is unchanged", source.read_bytes() == source_before)
            expect(
                case,
                "snapshot preserves source bytes",
                (actual_output / "source-record.json").read_bytes() == source_before,
            )
            expect(
                case,
                "production authorization is false",
                actual.get("production_promotion_authorized") is False,
            )
            expect(case, "review guide exists", (actual_output / "README.md").is_file())
            expect(
                case,
                "deterministic rollback example does not contradict the launch statement",
                "ANALYSIS_ANSWER_MODE=deterministic"
                in (root / "docs/analyst-evidence-loop.md").read_text()
                and actual.get("launch_consistency", {}).get("exit_code") == 0,
            )
            expect(
                case,
                "historical record commit remains attributed to its source",
                actual.get("source_record", {}).get("tested_commit")
                == json.loads(source_before)["tested_commit"],
            )
            expect(
                case,
                "historical candidate mismatch is an explicit blocker",
                any(
                    "tested_commit does not match source HEAD" in failure
                    for failure in actual.get("readiness", {}).get("failures", [])
                ),
            )
            historical_checks = json.loads(source_before).get("checks", {})
            expect(
                case,
                "every reported check retains its original commit",
                bool(actual.get("required_checks"))
                and all(
                    item.get("tested_commit")
                    == historical_checks.get(item["name"], {}).get("tested_commit")
                    for item in actual.get("required_checks", [])
                ),
            )
            expect(
                case, "readiness names failures", bool(actual.get("readiness", {}).get("failures"))
            )
            baseline = {
                path.name: digest(path) for path in actual_output.iterdir() if path.is_file()
            }
            case = invoke(cases, "existing_package", script, root, actual_output, workspace)
            expect(case, "existing package is rejected", case["exit_code"] == 2)
            expect(
                case,
                "existing artifact hashes are unchanged",
                baseline
                == {path.name: digest(path) for path in actual_output.iterdir() if path.is_file()},
            )

            for name, raw in (
                ("malformed_json", "{"),
                ("non_object_record", "[]"),
                ("invalid_nested_shape", '{"checks": []}'),
            ):
                invalid_record = workspace / f"{name}.json"
                invalid_record.write_text(raw)
                reject(cases, name, script, root, workspace / name, workspace, invalid_record)
            reject(
                cases,
                "missing_record",
                script,
                root,
                workspace / "missing",
                workspace,
                workspace / "absent.json",
            )
            reject(cases, "non_repository", script, workspace, workspace / "not-repo", workspace)
            empty_git = workspace / "empty-git"
            empty_git.mkdir()
            command(["git", "init", "-q"], empty_git)
            command(
                [
                    "git",
                    "-c",
                    "user.name=Release gate verifier",
                    "-c",
                    "user.email=release-gate-verifier@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "Missing project fixture",
                ],
                empty_git,
            )
            reject(
                cases,
                "missing_project_files",
                script,
                empty_git,
                workspace / "missing-project",
                workspace,
                source,
            )
            target = workspace / "symlink-target"
            target.mkdir()
            link = workspace / "output-link"
            link.symlink_to(target, target_is_directory=True)
            case = invoke(cases, "symlink_output", script, root, link, workspace)
            expect(case, "symlink destination is rejected", case["exit_code"] == 2)
            expect(case, "symlink target is untouched", not list(target.iterdir()))

            fixture = workspace / "fixture"
            make_fixture(root, fixture)
            fixture_script = fixture / "tools/release/prepare_llm_primary.py"
            fixture_record = fixture / "docs/release-evidence/release-record.json"
            fixture_before = fixture_record.read_bytes()
            fixture_output = workspace / "fixture-package"
            case = invoke(
                cases,
                "external_working_directory",
                fixture_script,
                fixture,
                fixture_output,
                workspace,
            )
            observed = package(fixture_output)
            expect(case, "selected checkout remains blocked", case["exit_code"] == 1)
            expect(
                case,
                "selected checkout commit is reported",
                observed.get("source_commit") == command(["git", "rev-parse", "HEAD"], fixture),
            )
            expect(
                case,
                "historical source commit is not rewritten",
                (fixture_output / "source-record.json").read_bytes() == fixture_before,
            )
            expect(
                case,
                "launch configuration checks pass before mutation",
                observed.get("launch_consistency", {}).get("exit_code") == 0,
            )

            launch_files = (
                fixture / "render.yaml",
                fixture / "docs/release-checklist.md",
                fixture / "docs/analyst-evidence-loop.md",
            )
            original_launch_files = {path: path.read_text() for path in launch_files}
            for path, text in original_launch_files.items():
                path.write_text(
                    text.replace("value: llm_primary", "value: shadow").replace(
                        "ANALYSIS_ANSWER_MODE=llm_primary", "ANALYSIS_ANSWER_MODE=shadow"
                    )
                )
            agreed_shadow_output = workspace / "agreed-shadow-package"
            case = invoke(
                cases,
                "agreeing_shadow_mismatches_primary_record",
                fixture_script,
                fixture,
                agreed_shadow_output,
                workspace,
            )
            agreed_shadow = package(agreed_shadow_output)
            expect(case, "agreeing shadow still blocks readiness", case["exit_code"] == 1)
            expect(
                case,
                "documentation and blueprint agree on shadow",
                agreed_shadow.get("launch_consistency", {}).get("exit_code") == 0,
            )
            expect(
                case,
                "release record and blueprint mismatch is explicit",
                "launch record answer mode does not match deployment blueprint"
                in agreed_shadow.get("readiness", {}).get("failures", []),
            )
            for path, text in original_launch_files.items():
                path.write_text(text)

            deleted_source = fixture / "candidate-source/source.py"
            deleted_source.parent.mkdir()
            deleted_source.write_text("CANDIDATE = True\n")
            command(["git", "add", str(deleted_source.relative_to(fixture))], fixture)
            command(
                [
                    "git",
                    "-c",
                    "user.name=Release gate verifier",
                    "-c",
                    "user.email=release-gate-verifier@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "Track candidate source before deletion",
                ],
                fixture,
            )
            deleted_source.unlink()
            deletion_output = deleted_source.parent
            case = invoke(
                cases,
                "tracked_deletion_in_output",
                fixture_script,
                fixture,
                deletion_output,
                workspace,
            )
            deletion = package(deletion_output)
            expect(case, "tracked deletion blocks readiness", case["exit_code"] == 1)
            expect(
                case,
                "tracked deletion remains in dirty-source paths",
                "candidate-source/source.py" in deletion.get("source_dirty_paths", []),
            )
            expect(
                case,
                "tracked deletion keeps the dirty-source blocker",
                "source checkout has uncommitted changes"
                in deletion.get("readiness", {}).get("failures", []),
            )

            blueprint = fixture / "render.yaml"
            blueprint.write_text(
                blueprint.read_text().replace("value: llm_primary", "value: shadow")
            )
            drift_output = workspace / "drift-package"
            case = invoke(
                cases,
                "launch_configuration_drift",
                fixture_script,
                fixture,
                drift_output,
                workspace,
            )
            drift = package(drift_output)
            expect(case, "launch drift blocks readiness", case["exit_code"] == 1)
            expect(
                case,
                "launch consistency failure is retained",
                drift.get("launch_consistency", {}).get("exit_code") == 1,
            )

            source_item = json.loads(fixture_before)["checks"]["backend"]
            evidence = fixture / source_item["path"]
            evidence.write_text(evidence.read_text() + "\nchanged evidence\n")
            tamper_output = workspace / "tamper-package"
            case = invoke(
                cases, "evidence_content_tamper", fixture_script, fixture, tamper_output, workspace
            )
            tamper = package(tamper_output)
            failures = tamper.get("readiness", {}).get("failures", [])
            expect(case, "changed evidence blocks readiness", case["exit_code"] == 1)
            expect(
                case,
                "hash mismatch identifies backend evidence",
                any("backend" in value and "hash" in value for value in failures),
            )
            expect(
                case,
                "source record remains unchanged after all fixture checks",
                fixture_record.read_bytes() == fixture_before,
            )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["passed"] = (
        bool(cases)
        and "error" not in report
        and all(assertion["passed"] for case in cases for assertion in case["assertions"])
    )
    report["case_count"] = len(cases)
    report["assertion_count"] = sum(len(case["assertions"]) for case in cases)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.root.resolve(), args.output.resolve())
    print(json.dumps({key: report[key] for key in ("passed", "case_count", "assertion_count")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
