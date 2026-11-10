"""Service-profile scenarios: guard proof, run stamps, attestation and driver inputs.

Every scenario drives the real evaluation CLI or the real release driver against
a loopback fake candidate and a throwaway ledger. No provider, Redis, Qdrant or
PostgreSQL is contacted, and nothing here measures answer quality. The shared
fixtures live in ``eval_scenarios_service_support``.

Run: uv run --package knicksiq-api python tools/release/eval_scenarios.py collect_service_run_stamp
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.evaluation.candidate_identity import candidate_identity  # noqa: E402
from app.evaluation.labels import (  # noqa: E402
    evaluation_identity,
    identity_digest,
    load_labels,
)
from app.evaluation.mapping import load_mapping  # noqa: E402
from app.evaluation.provider_approval import approval_payload  # noqa: E402
from eval_scenario_fixtures import dump, load, write_dataset
from eval_scenario_records import disposition_response, observation, write_observations
from eval_scenario_support import (
    REAL_EXPECTATIONS,
    REAL_MAPPING,
    REAL_QUESTIONS,
    clean_env,
    expect,
    metric,
    run_cli,
)
from eval_scenarios_budget_support import (
    APPROVED_AT,
    CASES,
    LABELS,
    MODEL,
    PREAMBLE,
    approval_for,
    driver,
    issue,
    reported,
    sealed,
    spend_for_scenarios,
    wire,
)
from eval_scenarios_service_support import candidate, service_collect, synthetic_identity

TOOLS = Path(__file__).resolve().parent
DB_URL = "postgresql+asyncpg://knicksiq:local@127.0.0.1:18430/knicksiq"


def scenario_collect_service_needs_guard_proof(directory: Path) -> list[str]:
    """A service collection refuses without a binding and without a durable claim."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    responses = directory / "responses.jsonl"
    with candidate() as (base_url, requests_seen):
        refused = run_cli(
            [
                "collect",
                "--questions",
                str(questions),
                "--expectations",
                str(expectations),
                "--base-url",
                base_url,
                "--profile",
                "service",
                "--responses",
                str(responses),
            ],
            cwd=directory,
        )
        expect(refused.returncode != 0, "a service collect needs a run configuration", problems)
        expect("run-config" in refused.stderr, f"{refused.stderr[-300:]}", problems)
        expect(requests_seen == [], "no candidate request without a binding", problems)

        identity, labels_sha256, _ = synthetic_identity(directory, questions, expectations)
        _, binding = approval_for(
            directory,
            base_url=base_url,
            cap=8,
            identity=identity,
            labels=labels_sha256,
        )
        config, announced = issue(directory, binding, "run")
        unclaimed = service_collect(
            directory, base_url, questions, expectations, responses, config, announced
        )
        expect(unclaimed.returncode != 0, "an unclaimed ledger refuses collection", problems)
        expect("claimed" in unclaimed.stderr, f"{unclaimed.stderr[-300:]}", problems)
        expect(requests_seen == [], "guard proof precedes the first POST", problems)
        expect(not responses.exists(), "a refused collection writes no responses", problems)
    return problems


def scenario_collect_service_run_stamp(directory: Path) -> list[str]:
    """A guarded collection stamps the run and scores only against its sealed ledger."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    identity, labels_sha256, mapping = synthetic_identity(directory, questions, expectations)
    responses = directory / "responses.jsonl"
    _, binding = approval_for(
        directory,
        base_url="http://127.0.0.1:9/v1",
        cap=8,
        identity=identity,
        labels=labels_sha256,
    )
    config, announced = issue(directory, binding, "run")
    claimed = driver(
        directory,
        "claim",
        PREAMBLE + "bind_run_guard()\nprint(json.dumps({'claimed': True}))\n",
        env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
    )
    expect(reported(claimed, problems).get("claimed") is True, "the claim is written", problems)
    with candidate(binding) as (base_url, requests_seen):
        collected = service_collect(
            directory, base_url, questions, expectations, responses, config, announced
        )
        expect(collected.returncode == 0, f"collect failed: {collected.stderr[-800:]}", problems)
        expect(len(requests_seen) == CASES, "every approved case is collected", problems)
        rows = (
            [json.loads(line) for line in responses.read_text().splitlines() if line.strip()]
            if responses.exists()
            else []
        )
        expect(len(rows) == CASES, f"one record per case: {len(rows)}", problems)
        expect(
            all(row.get("run", {}).get("run_id") == binding.run_id for row in rows),
            "every response carries the run identity",
            problems,
        )
        expect(
            all(row.get("proof") is not None for row in rows),
            "every response carries the candidate's own proof",
            problems,
        )
        if collected.returncode == 0:
            summary = json.loads(collected.stdout)
            expect(summary["provider_attempts"] == 0, f"no attempts: {summary}", problems)
            expect(summary["provider_stages"] == CASES, f"stages are separate: {summary}", problems)
            expect(
                summary.get("proofs_verified") == CASES,
                f"every proof verifies before acceptance: {summary}",
                problems,
            )
    sealed(binding)
    report_path = directory / "report.json"
    scored = run_cli(
        [
            "score",
            "--questions",
            str(questions),
            "--expectations",
            str(expectations),
            "--mapping",
            str(mapping),
            "--responses",
            str(responses),
            "--profile",
            "service",
            "--run-config",
            str(config),
            "--run-config-sha256",
            announced,
            "--output",
            str(report_path),
        ],
        cwd=directory,
    )
    expect(scored.returncode == 0, f"score failed: {scored.stderr[-800:]}", problems)
    if report_path.exists():
        report = load(report_path)
        expect(
            report["profile"].get("candidate") == binding.candidate,
            "service report identifies the bound candidate",
            problems,
        )
        codes = [item["code"] for item in report["blockers"]]
        expect(
            "service_guard_unattested" in codes,
            f"a run with no admitted attempt is not service evidence: {codes}",
            problems,
        )
        expect(
            "provider_requests_observed" not in codes,
            f"a bound service run is not judged as provider-free: {codes}",
            problems,
        )
        expect(
            report["profile"]["provider_attempts"] == 0
            and report["profile"]["provider_requests"] == CASES,
            f"attempts and stages stay separate: {report['profile']}",
            problems,
        )
        expect(
            metric(report, "disposition_accuracy")["denominator"] == CASES,
            "the fixed denominator survives the service profile",
            problems,
        )
    relabelled = directory / "relabelled.json"
    run_cli(
        [
            "score",
            "--questions",
            str(questions),
            "--expectations",
            str(expectations),
            "--mapping",
            str(mapping),
            "--responses",
            str(responses),
            "--profile",
            "disabled",
            "--output",
            str(relabelled),
        ],
        cwd=directory,
    )
    if relabelled.exists():
        codes = [item["code"] for item in load(relabelled)["blockers"]]
        expect(
            "run_stamp_under_disabled_profile" in codes,
            f"a stamped run cannot be relabelled provider-free: {codes}",
            problems,
        )
    return problems


def scenario_score_service_requires_attestation(directory: Path) -> list[str]:
    """A fresh scorer needs the binding and the meter, not a profile flag."""
    problems: list[str] = []
    questions, expectations = write_dataset(directory)
    identity, labels_sha256, mapping = synthetic_identity(directory, questions, expectations)
    responses = write_observations(
        directory / "responses.jsonl",
        [observation("answer-001", disposition_response("clarify"))],
    )
    refused = run_cli(
        [
            "score",
            "--questions",
            str(questions),
            "--expectations",
            str(expectations),
            "--mapping",
            str(mapping),
            "--responses",
            str(responses),
            "--profile",
            "service",
        ],
        cwd=directory,
    )
    expect(refused.returncode != 0, "service scoring needs a run configuration", problems)
    expect("run-config" in refused.stderr, f"{refused.stderr[-300:]}", problems)

    with wire() as (base_url, hits):
        _, binding = approval_for(
            directory, base_url=base_url, cap=4, identity=identity, labels=labels_sha256
        )
        config, announced = issue(directory, binding, "run")
        spent = driver(
            directory,
            "spend",
            PREAMBLE
            + f"""
bind_run_guard()
adapter({binding.provider_base_url!r}, {binding.provider_model!r})._generate_sync("s", "u")
print(json.dumps({{"ok": True}}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
        expect(reported(spent, problems).get("ok") is True, "one attempt is admitted", problems)
        expect(len(hits) == 1, "one wire hit", problems)
    sealed(binding)
    report_path = directory / "unbound.json"
    result = run_cli(
        [
            "score",
            "--questions",
            str(questions),
            "--expectations",
            str(expectations),
            "--mapping",
            str(mapping),
            "--responses",
            str(responses),
            "--profile",
            "service",
            "--run-config",
            str(config),
            "--run-config-sha256",
            announced,
            "--output",
            str(report_path),
        ],
        cwd=directory,
    )
    expect(result.returncode == 0, f"an attested ledger scores: {result.stderr[-600:]}", problems)
    if report_path.exists():
        report = load(report_path)
        codes = [item["code"] for item in report["blockers"]]
        expect(
            "service_proof_missing" in codes,
            f"an unproven response cannot borrow a meter: {codes}",
            problems,
        )
        expect(
            "service_run_binding_missing" in codes,
            f"an unstamped response cannot borrow a meter: {codes}",
            problems,
        )
        expect(
            report["profile"]["attested"] is True,
            "the ledger itself attests: the blocker is the responses, not the meter",
            problems,
        )
    return problems


def scenario_runner_service_refuses_without_inputs(directory: Path) -> list[str]:
    """The release driver refuses before starting a candidate when an input is missing."""
    problems: list[str] = []
    missing = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "eval_runner.py"),
            "--db-url",
            DB_URL,
            "--output",
            str(directory / "run"),
            "--profile",
            "service",
        ],
        cwd=directory,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    expect(missing.returncode != 0, "a service run without an approval is refused", problems)
    expect("--approval" in missing.stderr, f"{missing.stderr[-300:]}", problems)
    expect(not (directory / "run" / "api.log").exists(), "no candidate was started", problems)

    foreign = dump(
        directory / "foreign.json",
        approval_payload(
            approved=True,
            approver="operator",
            approved_at=APPROVED_AT,
            identity_sha256="e" * 64,
            candidate=candidate_identity(),
            labels_sha256=LABELS,
            case_count=CASES,
            provider_base_url="http://127.0.0.1:9/v1",
            provider_model=MODEL,
            max_provider_requests=4,
            reasoning_effort="none",
            spend_bound=spend_for_scenarios(),
            ledger_root=str(directory / "ledger"),
        ),
    )
    refused = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "eval_runner.py"),
            "--db-url",
            DB_URL,
            "--output",
            str(directory / "foreign-run"),
            "--profile",
            "service",
            "--approval",
            str(foreign),
        ],
        cwd=directory,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    expect(refused.returncode != 0, "an approval for another identity is refused", problems)
    expect("identity" in refused.stderr, f"{refused.stderr[-300:]}", problems)
    expect(not (directory / "foreign-run" / "api.log").exists(), "nothing started", problems)

    identity_sha256, labels_sha256, case_count = real_identity()
    approval = dump(
        directory / "valid.json",
        approval_payload(
            approved=True,
            approver="operator",
            approved_at=APPROVED_AT,
            identity_sha256=identity_sha256,
            candidate=candidate_identity(),
            labels_sha256=labels_sha256,
            case_count=case_count,
            provider_base_url="http://127.0.0.1:9/v1",
            provider_model=MODEL,
            max_provider_requests=4,
            reasoning_effort="none",
            spend_bound=spend_for_scenarios(),
            ledger_root=str(directory / "ledger"),
        ),
    )
    no_key = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "eval_runner.py"),
            "--db-url",
            DB_URL,
            "--output",
            str(directory / "keyless"),
            "--profile",
            "service",
            "--approval",
            str(approval),
        ],
        cwd=directory,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    expect(no_key.returncode != 0, "a service run without the operator key is refused", problems)
    expect("KNICKSIQ_EVAL_PROVIDER_KEY" in no_key.stderr, f"{no_key.stderr[-300:]}", problems)
    expect(
        not (directory / "keyless" / "run-config.json").exists(),
        "no run configuration is issued without the operator key",
        problems,
    )
    return problems


def real_identity() -> tuple[str, str, int]:
    labels = load_labels(REAL_QUESTIONS, REAL_EXPECTATIONS)
    mapping = load_mapping(REAL_MAPPING)
    identity = evaluation_identity(
        labels, mapping_sha256=mapping.file_sha256, documents_sha256=None
    )
    return identity_digest(identity), labels.labels_sha256, labels.case_count
