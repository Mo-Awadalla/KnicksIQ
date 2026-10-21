"""Command line runner for the llm_primary preflight."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from preflight import env_checks
from preflight.common import (
    DEFAULT_API_HOST,
    DEFAULT_EXPECTED_CUTOFF,
    DEFAULT_EXPECTED_MODE,
    DEFAULT_LEDGER_KEY,
    Context,
    report_dict,
    selected,
    write_report,
)
from preflight.ledger_checks import LEDGER_CHECKS, check_ledger
from preflight.runtime_checks import (
    in_process_client,
    remote_client,
    run_kill_switch,
    run_target_checks,
)

TARGET_CHECKS = {
    "target.live",
    "target.ready",
    "target.cors",
    "target.trusted_host",
    "provider_failure",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only llm_primary readiness preflight.")
    parser.add_argument("--base-url", help="probe this API instead of the in-process ASGI app")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--expected-mode", default=DEFAULT_EXPECTED_MODE)
    parser.add_argument("--expected-cutoff", type=float, default=DEFAULT_EXPECTED_CUTOFF)
    parser.add_argument("--api-host", default=DEFAULT_API_HOST)
    parser.add_argument("--ledger-key", default=DEFAULT_LEDGER_KEY)
    parser.add_argument("--only", default="", help="comma-separated check ids; empty runs all")
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="do not report configuration checks for a remote target",
    )
    args = parser.parse_args(argv)
    args.only = {item.strip() for item in args.only.split(",") if item.strip()}
    return args


async def run(args: argparse.Namespace) -> dict[str, Any]:
    ctx = Context(args=args)

    if not args.skip_env and selected(ctx, "env.required"):
        env_checks.check_required_env(ctx)
    env_checks.check_settings(ctx)
    if args.skip_env:
        ctx.checks = [check for check in ctx.checks if check.id != "env.parse"]
    elif not selected(ctx, "env.parse"):
        ctx.checks = [check for check in ctx.checks if check.id != "env.parse"]
    for check_id, fn in env_checks.ENV_CHECKS:
        if selected(ctx, check_id):
            fn(ctx)

    if any(selected(ctx, check_id) for check_id in LEDGER_CHECKS):
        await check_ledger(ctx)

    needs_target = not args.only or bool(args.only & TARGET_CHECKS)
    if needs_target:
        in_process = not args.base_url
        try:
            manager = in_process_client(ctx, None) if in_process else remote_client(ctx)
            async with manager as client:
                await run_target_checks(ctx, client, in_process=in_process)
        except Exception as exc:  # noqa: BLE001
            for check_id in TARGET_CHECKS - {"provider_failure"}:
                if selected(ctx, check_id):
                    ctx.add(check_id, False, f"target unavailable: {type(exc).__name__}", {})

    await run_kill_switch(ctx)

    checks = [check for check in ctx.checks if selected(ctx, check.id)]
    report = report_dict(ctx, checks)
    write_report(args.json_out, report)
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = asyncio.run(run(args))
    print(json.dumps(report["summary"], indent=2))
    for check in report["checks"]:
        if check["status"] != "pass":
            print(f"{check['status']}: {check['id']}: {check['detail']}")
    return {"pass": 0, "fail": 1, "incomplete": 2}[report["summary"]["status"]]
