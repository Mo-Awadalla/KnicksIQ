"""Candidate source-binding approval scenario."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from app.evaluation.provider_approval import approval_payload
from eval_scenario_fixtures import dump
from eval_scenario_support import clean_env, expect
from eval_scenarios_budget_support import (
    APPROVED_AT,
    CASES,
    IDENTITY,
    LABELS,
    MODEL,
    spend_for_scenarios,
)

TOOLS = Path(__file__).resolve().parent
DB_URL = "postgresql+asyncpg://knicksiq:local@127.0.0.1:18430/knicksiq"


def scenario_candidate_approval_source_binding(directory: Path) -> list[str]:
    """Approval follows source content, including untracked modules, but not evidence."""
    from app.evaluation.candidate_identity import candidate_identity
    from app.evaluation.provider_approval import ApprovalError, load_approval

    repo = directory / "candidate"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    source = repo / "apps/api/app/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "candidate",
        ],
        check=True,
    )
    original = candidate_identity(repo)
    payload = approval_payload(
        approved=True,
        approver="operator",
        approved_at=APPROVED_AT,
        identity_sha256=IDENTITY,
        labels_sha256=LABELS,
        case_count=CASES,
        candidate=original,
        provider_base_url="http://127.0.0.1:9/v1",
        provider_model=MODEL,
        max_provider_requests=4,
        reasoning_effort="none",
        spend_bound=spend_for_scenarios(),
        ledger_root=str(directory / "ledger"),
    )
    path = dump(directory / "approval.json", payload)
    problems: list[str] = []

    def accepts(candidate: dict) -> bool:
        try:
            load_approval(
                path,
                identity_sha256=IDENTITY,
                labels_sha256=LABELS,
                case_count=CASES,
                candidate=candidate,
            )
            return True
        except ApprovalError:
            return False

    expect(accepts(original), "unchanged candidate is accepted", problems)
    expect(
        len(original["commit"]) == 40 and len(original["source_sha256"]) == 64,
        "identity reports commit and source digest",
        problems,
    )
    source.write_text("value = 2\n")
    expect(not accepts(candidate_identity(repo)), "modified source is rejected", problems)
    source.write_text("value = 1\n")
    added = source.parent / "added.py"
    added.write_text("value = 3\n")
    expect(not accepts(candidate_identity(repo)), "untracked module is rejected", problems)
    added.unlink()
    for relative in (
        "apps/api/secrets.py",
        "apps/api/app/credentials.py",
        "apps/web/index.html",
        "apps/web/tsconfig.app.json",
        "deploy/nginx.conf",
    ):
        item = repo / relative
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("candidate implementation\n")
        expect(not accepts(candidate_identity(repo)), f"{relative} changes identity", problems)
        item.unlink()
    (repo / ".git/info/exclude").write_text("*.so\n*.pyd\n*.pyc\n")
    for relative in (
        "apps/api/app/analyst_render.so",
        "apps/api/app/analyst_render.pyd",
        "apps/api/secrets.pyc",
    ):
        native = repo / relative
        native.write_bytes(b"native module")
        try:
            native_identity = candidate_identity(repo)
        except RuntimeError:
            pass
        else:
            expect(not accepts(native_identity), f"{relative} changes identity", problems)
        native.unlink()
    secret = source.parent / ".env"
    secret.write_text("PRIVATE_KEY=secret\n")
    expect(accepts(candidate_identity(repo)), "credentials do not enter identity", problems)
    secret.unlink()
    target = directory / "outside.py"
    target.write_text("value = 4\n")
    link = source.parent / "linked.py"
    link.symlink_to(target)
    for value in ("value = 4\n", "value = 5\n"):
        target.write_text(value)
        try:
            candidate_identity(repo)
        except RuntimeError:
            pass
        else:
            problems.append("source symlink must fail closed")
    link.unlink()
    evidence = repo / "graphify-out" / "graph.json"
    evidence.parent.mkdir()
    evidence.write_text("{}")
    expect(accepts(candidate_identity(repo)), "generated evidence does not invalidate", problems)
    payload.pop("candidate")
    # Exercise the operator-facing prepare/run boundary in an isolated candidate checkout.
    checkout = directory / "checkout"
    subprocess.run(
        ["git", "clone", "-q", "--shared", str(TOOLS.parents[1]), str(checkout)], check=True
    )
    shutil.copytree(
        TOOLS.parents[1] / "apps/api/app",
        checkout / "apps/api/app",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(
        TOOLS,
        checkout / "tools/release",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    intent = dump(
        directory / "intent.json",
        {
            "approved": True,
            "approver": "operator",
            "approved_at": APPROVED_AT,
            "provider_base_url": "http://127.0.0.1:9/v1",
            "provider_model": MODEL,
            "max_provider_requests": 4,
            "reasoning_effort": "none",
            "spend_bound": spend_for_scenarios().payload(),
            "ledger_root": str(directory / "ledger"),
        },
    )
    cli_approval = directory / "cli-approval.json"
    command = [
        sys.executable,
        str(checkout / "tools/release/eval_runner.py"),
        "--db-url",
        DB_URL,
        "--profile",
        "service",
        "--approval",
        str(cli_approval),
    ]
    environment = {**clean_env(), "PYTHONPATH": str(checkout / "apps/api")}
    prepared = subprocess.run(
        command + ["--output", str(directory / "prepare"), "--prepare-approval", str(intent)],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    expect(prepared.returncode == 0, f"prepare failed: {prepared.stderr[-500:]}", problems)
    if prepared.returncode == 0:

        def run(name: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command + ["--output", str(directory / name)],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        unchanged = run("unchanged")
        expect(
            "KNICKSIQ_EVAL_PROVIDER_KEY" in unchanged.stderr,
            "unchanged CLI candidate reaches key admission",
            problems,
        )
        changed = checkout / "apps/api/app/main.py"
        changed.write_text(changed.read_text() + "\n# changed candidate\n")
        drift = run("drift")
        expect(
            "approval_candidate_mismatch" in drift.stderr,
            "CLI rejects source drift before provider admission",
            problems,
        )
        expect(
            not (directory / "drift" / "api.log").exists(), "drift never starts candidate", problems
        )
    dump(path, payload)
    expect(not accepts(original), "old approval without candidate is rejected", problems)
    return problems
