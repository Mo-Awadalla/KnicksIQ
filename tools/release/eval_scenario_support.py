"""Shared plumbing for the evaluation regression scenarios.

Repository paths, isolated subprocess environments, digests and the small
report accessors every scenario uses. Nothing here talks to a provider, Redis,
Qdrant or PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "apps/api"
REAL_QUESTIONS = API_ROOT / "app/evaluation/questions.jsonl"
REAL_EXPECTATIONS = REPO / "docs/release-evidence/reconciliation-20260928/expectation-review.json"
REAL_MAPPING = REPO / "docs/release-evidence/reconciliation-20260928/runtime-mapping.json"

RELEASE = "scenario.1"
ANSWER_CASES = 58
CLARIFY_CASES = 53
REFUSE_CASES = 9
SEMANTIC_CASES = 50


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def dump(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_env() -> dict[str, str]:
    """Never inherit .env values: only PATH/HOME plus an explicit package root."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(API_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def run_cli(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.evaluation.cli", *args],
        cwd=cwd,
        env=clean_env() if env is None else env,
        capture_output=True,
        text=True,
        check=False,
    )


def metric(report: dict[str, Any], name: str) -> dict[str, Any]:
    if name not in report["metrics"]:
        raise AssertionError(f"metric {name} missing from report")
    return report["metrics"][name]


def failures(report: dict[str, Any], case_id: str) -> list[str]:
    for case in report["cases"]:
        if case["id"] == case_id:
            return [item["code"] for item in case["failures"]]
    raise AssertionError(f"case {case_id} missing from report")


def expect(condition: bool, message: str, problems: list[str]) -> bool:
    if not condition:
        problems.append(message)
    return condition
