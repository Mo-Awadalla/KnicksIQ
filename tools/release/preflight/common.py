"""Shared types and small helpers for the llm_primary preflight checks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_API_HOST = "api.knicksiq.win"
DEFAULT_PUBLIC_ORIGIN = "https://www.knicksiq.win"
DEFAULT_EXPECTED_MODE = "llm_primary"
DEFAULT_EXPECTED_CUTOFF = 2.0
DEFAULT_LEDGER_KEY = f"ai-budget:{datetime.now(UTC):%Y-%m}"
PRIMARY_QUESTION = "What was the Knicks record this season?"
OVERALL_QUESTION = "What was the Knicks record overall this season?"


@dataclass
class Check:
    id: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    args: Any
    checks: list[Check] = field(default_factory=list)
    settings: Any = None
    settings_error: str = ""
    db_record: tuple[int, int] | None = None
    db_overall_record: tuple[int, int] | None = None

    def add(self, check_id: str, ok: bool, detail: str, evidence: dict[str, Any] | None = None):
        self.checks.append(Check(check_id, "pass" if ok else "fail", detail, evidence or {}))

    def skip(self, check_id: str, detail: str):
        self.checks.append(Check(check_id, "skip", detail, {}))


def selected(ctx: Context, check_id: str) -> bool:
    return not ctx.args.only or check_id in ctx.args.only


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def json_list(raw: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("must be a JSON array of strings")
    return value


def summary(checks: list[Check]) -> dict[str, Any]:
    counts = {"pass": 0, "fail": 0, "skip": 0}
    for check in checks:
        counts[check.status] = counts.get(check.status, 0) + 1
    if counts["fail"]:
        status = "fail"
    elif counts["skip"]:
        status = "incomplete"
    else:
        status = "pass"
    return {**counts, "status": status}


def report_dict(ctx: Context, checks: list[Check]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "base-url" if ctx.args.base_url else "in-process",
        "target": ctx.args.base_url or f"in-process ASGI {ctx.args.api_host}",
        "expected_mode": ctx.args.expected_mode,
        "expected_cutoff_usd": ctx.args.expected_cutoff,
        "secrets_printed": False,
        "checks": [
            {
                "id": check.id,
                "status": check.status,
                "detail": check.detail,
                "evidence": check.evidence,
            }
            for check in checks
        ],
        "summary": summary(checks),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
