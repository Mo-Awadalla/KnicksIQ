"""Run the real evaluation collect+score cycle against a local candidate.

``--profile disabled`` is provider-free: ``AI_PROVIDER=mock``, no key, and the
summary refuses to publish a result if any response reports a model stage.

``--profile service`` is the enabled path and needs an operator approval. The
approval binds the loaded evaluation identity, the exact provider origin and
model, and an exact maximum number of upstream attempts. The driver derives the
run configuration, starts ``app.evaluation.service_entrypoint`` so the candidate
binds it before answering readiness, proves the candidate left its durable claim
before the first POST, starts with loopback Redis and the provider key from the
operator's own environment, then stops the child, seals the attempt ledger and
scores against the sealed ledger. The ledger lives under the approval's ledger
root, never in the output directory. Restarts and new output directories cannot
reset either the upstream attempt cap or the durable aggregate dollar bound.

Local-only by construction: the database and Redis must be loopback, the child
gets a fully explicit environment that never inherits ``.env`` or an ambient
proxy, the listening socket is bound here and handed to the child, and cleanup
stops the child's whole process group without aborting the evidence.

Run:
  uv run --package knicksiq-api python tools/release/eval_runner.py \
    --db-url postgresql+asyncpg://user:pass@127.0.0.1:55432/knicksiq \
    --output release-artifacts/evaluation-run-local
"""

from __future__ import annotations

import argparse
import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "apps/api"
QUESTIONS = API_ROOT / "app/evaluation/questions.jsonl"
EXPECTATIONS = REPO / "docs/release-evidence/reconciliation-20260928/expectation-review.json"
MAPPING = REPO / "docs/release-evidence/reconciliation-20260928/runtime-mapping.json"

TOOLS = Path(__file__).resolve().parent
for _entry in (str(API_ROOT), str(TOOLS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from app.evaluation import narrative_cli  # noqa: E402
from app.evaluation.attempt_ledger import Attestation, LedgerError  # noqa: E402
from app.evaluation.provider_approval import ApprovalError  # noqa: E402
from eval_approval import (  # noqa: E402
    prepare_approval,
    require_claim,
    seal_and_attest,
    service_settings,
)
from eval_process import (  # noqa: E402
    ARTIFACTS,
    DEFAULT_REDIS_URL,
    PROVIDER_KEY_ENV,
    RunnerFailure,
    ServiceSettings,
    bind_listener,
    clean_env,
    interrupt,
    redact_url,
    relative_artifacts,
    run_cli,
    stop_process,
    validate_db_url,
    wait_ready,
)

DISABLED_ENTRYPOINT = "app.main:app"
SERVICE_ENTRYPOINT = "app.evaluation.service_entrypoint:app"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", required=True, help="disposable local PostgreSQL only")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--expectations", type=Path, default=EXPECTATIONS)
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--startup-seconds", type=float, default=90)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument(
        "--profile",
        choices=("disabled", "service"),
        default="disabled",
        help="disabled is provider-free; service runs under an operator approval",
    )
    parser.add_argument("--approval", type=Path, help="service profile: issued approval artifact")
    parser.add_argument(
        "--prepare-approval",
        type=Path,
        help="service profile: seal an operator intent into --approval and stop",
    )
    parser.add_argument(
        "--provider-key-env",
        default=PROVIDER_KEY_ENV,
        help="environment variable holding the operator's provider key",
    )
    parser.add_argument("--redis-url", default=DEFAULT_REDIS_URL)
    narrative_cli.add_arguments(parser)
    parser.add_argument(
        "--evidence-loop",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="exercise the evidence-loop route (provider-free proxy stages when disabled)",
    )
    return parser


def _start_candidate(
    *, entrypoint: str, listener: socket.socket, working: Path, env: dict[str, str], log: Any
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            entrypoint,
            "--fd",
            str(listener.fileno()),
            "--log-level",
            "warning",
        ],
        cwd=working,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        pass_fds=(listener.fileno(),),
        start_new_session=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_url = validate_db_url(args.db_url)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    if args.prepare_approval is not None:
        if args.profile != "service":
            print("--prepare-approval belongs to --profile service", file=sys.stderr)
            return 2
        if args.approval is None:
            print("--prepare-approval needs --approval to name the artifact", file=sys.stderr)
            return 2
        try:
            return prepare_approval(
                args, args.approval, questions=QUESTIONS, expectations=args.expectations
            )
        except (RunnerFailure, ApprovalError) as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    responses = output / ARTIFACTS["responses"]
    report_path = output / ARTIFACTS["report"]
    log_path = output / ARTIFACTS["api_log"]

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGINT)}
    failure: str | None = None
    cleanup_problems: list[str] = []
    readiness: dict[str, Any] | None = None
    started_at = datetime.now(UTC).isoformat()
    listener: socket.socket | None = None
    base_url: str | None = None
    service: ServiceSettings | None = None
    proof_key = ""
    attestation: Attestation | None = None
    env: dict[str, str] = {}
    candidate_env: dict[str, str] = {}
    try:
        if args.profile == "service":
            if args.approval is None:
                raise RunnerFailure(
                    "the service profile needs --approval: without an operator approval no "
                    "provider request is authorized"
                )
            if args.limit is not None:
                raise RunnerFailure(
                    "an approved run collects its whole identity; --limit is not a bounded run"
                )
            if not args.evidence_loop:
                raise RunnerFailure(
                    "a service run needs the evidence loop: it is the route that reaches the "
                    "approved model"
                )
            service, _, key = service_settings(
                args,
                approval_path=args.approval,
                output=output,
                questions=QUESTIONS,
                expectations=args.expectations,
            )
            proof_key = key.private_key
        env = clean_env(db_url, loop_enabled=args.evidence_loop, service=service)
        # Only the candidate child receives the private key in its environment.
        # The collector and scorer receive public verification material.
        candidate_env = (
            clean_env(
                db_url,
                loop_enabled=args.evidence_loop,
                service=service,
                proof_key=proof_key,
            )
            if service is not None
            else env
        )
        entrypoint = SERVICE_ENTRYPOINT if service is not None else DISABLED_ENTRYPOINT

        listener = bind_listener()
        base_url = f"http://127.0.0.1:{int(listener.getsockname()[1])}"
        with tempfile.TemporaryDirectory(prefix="eval-run-") as work:
            working = Path(work)
            with log_path.open("w", encoding="utf-8") as log:
                process = _start_candidate(
                    entrypoint=entrypoint,
                    listener=listener,
                    working=working,
                    env=candidate_env,
                    log=log,
                )
                listener.close()
                try:
                    readiness = wait_ready(
                        base_url, process, time.monotonic() + args.startup_seconds
                    )
                    if service is not None:
                        require_claim(service.binding)
                    collect_arguments = [
                        "collect",
                        "--questions",
                        str(QUESTIONS),
                        "--expectations",
                        str(args.expectations.expanduser().resolve()),
                        "--base-url",
                        base_url,
                        "--profile",
                        args.profile,
                        "--responses",
                        str(responses),
                        "--timeout",
                        str(args.timeout),
                    ]
                    if args.limit:
                        collect_arguments.extend(["--limit", str(args.limit)])
                    if service is not None:
                        collect_arguments.extend(
                            [
                                "--run-config",
                                str(service.config_path),
                                "--run-config-sha256",
                                service.binding.config_sha256,
                            ]
                        )
                    run_cli(collect_arguments, cwd=working, env=env)
                finally:
                    cleanup_problems = stop_process(process)
                    log.flush()
                if service is not None:
                    attestation = seal_and_attest(service.binding)
                score_arguments = [
                    "score",
                    "--questions",
                    str(QUESTIONS),
                    "--expectations",
                    str(args.expectations.expanduser().resolve()),
                    "--mapping",
                    str(args.mapping.expanduser().resolve()),
                    "--responses",
                    str(responses),
                    "--profile",
                    args.profile,
                    "--output",
                    str(report_path),
                ]
                if args.documents is not None:
                    score_arguments.extend(
                        ["--documents", str(args.documents.expanduser().resolve())]
                    )
                for field in narrative_cli.FIELDS:
                    value = getattr(args, field)
                    if value is not None:
                        score_arguments.extend(
                            ["--" + field.replace("_", "-"), str(value.expanduser().resolve())]
                        )
                if service is not None:
                    score_arguments.extend(
                        [
                            "--run-config",
                            str(service.config_path),
                            "--run-config-sha256",
                            service.binding.config_sha256,
                        ]
                    )
                run_cli(score_arguments, cwd=working, env=env)
    except RunnerFailure as exc:
        failure = f"{type(exc).__name__}: {exc}"
    except KeyboardInterrupt as exc:
        failure = f"interrupted: {exc}"
    except (OSError, subprocess.SubprocessError) as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if service is not None and attestation is None:
            try:
                ledger = service.binding.ledger()
                if ledger.path.is_file() and ledger.snapshot().claim is not None:
                    attestation = seal_and_attest(service.binding)
            except (LedgerError, OSError, RunnerFailure) as exc:
                cleanup_problems.append(f"provider ledger finalization: {exc}")
                failure = failure or f"provider ledger finalization failed: {exc}"
        if listener is not None:
            try:
                listener.close()
            except OSError as exc:  # pragma: no cover - close of a bound socket
                cleanup_problems.append(f"listener close: {exc}")
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    guard_block: dict[str, Any] | None = None
    if service is not None:
        guard_block = {
            "run_id": service.binding.run_id,
            "approval_sha256": service.binding.approval_sha256,
            "config_sha256": service.binding.config_sha256,
            "ledger_file": Path(service.binding.ledger_path).name,
            "attempt_budget": service.binding.max_provider_requests,
            "spend_budget_nano_usd": service.binding.spend_bound.max_total_nano_usd,
            "scope": service.binding.scope,
            "proof_public_key_sha256": service.binding.proof_fingerprint(),
            "attestation": None if attestation is None else attestation.as_dict(),
        }
        if attestation is not None and not attestation.ok:
            failure = failure or "provider guard attestation failed: " + "; ".join(
                attestation.problems
            )

    summary: dict[str, Any] = {
        "schema": "evaluation-run-v1",
        "status": "failed" if failure else "completed",
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Local candidate evaluation with providers disabled. Not a label approval, not a "
            "deployment decision and not a provider measurement."
            if service is None
            else "Local candidate evaluation under one approved bounded run. Upstream attempts "
            "come from that run's durable ledger. Not a label approval and not a deployment "
            "decision."
        ),
        "profile": args.profile,
        "base_url": base_url,
        "database": redact_url(db_url),
        "environment": {
            key: env[key]
            for key in (
                "RAG_QDRANT_ENABLED",
                "RAG_QDRANT_CLOUD_INFERENCE",
                "AI_PROVIDER",
                "ANALYSIS_ANSWER_MODE",
                "ANALYST_EVIDENCE_LOOP_ENABLED",
            )
            if key in env
        },
        "provider_guard": guard_block,
        "readiness": readiness,
        "artifacts": relative_artifacts(output),
        "cleanup_failures": cleanup_problems,
    }
    if failure:
        summary["error"] = failure
    else:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            records = [
                json.loads(line)
                for line in responses.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            summary.update(
                {
                    "cases_recorded": len(records),
                    "provider_requests": report["profile"]["provider_requests"],
                    "provider_attempts": report["profile"].get("provider_attempts"),
                    "proofs_verified": report["profile"].get("proofs_verified"),
                    "http_errors": sum(1 for record in records if record.get("http_status") != 200),
                    "release_blocked": report["release_blocked"],
                    "blockers": [item["code"] for item in report["blockers"]],
                    "gates": {name: gate["status"] for name, gate in report["gates"].items()},
                }
            )
            if report["profile"]["name"] != args.profile:
                summary["status"] = "failed"
                summary["error"] = (
                    f"the report is scored as {report['profile']['name']}, not {args.profile}"
                )
            elif service is None and report["profile"]["provider_requests"]:
                summary["status"] = "failed"
                summary["error"] = (
                    f"{report['profile']['provider_requests']} model stages were reported under "
                    "the disabled profile; zero provider requests cannot be claimed"
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            summary["status"] = "failed"
            summary["error"] = f"invalid evaluation artifacts: {type(exc).__name__}: {exc}"
    summary_path = output / "run-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] != "completed":
        print(f"evaluation run failed: {summary['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
