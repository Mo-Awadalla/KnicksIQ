"""Budget scenarios: the approved run's cap, claim, seal and origin binding.

Every scenario drives the real guard and the real adapter boundary against a
loopback fake wire and a throwaway ledger under this scenario's directory. A
local fake proves boundary behaviour only; nothing here measures quality.

Run: uv run --package knicksiq-api python tools/release/eval_scenarios.py budget_concurrency_cap
"""

from __future__ import annotations

from pathlib import Path

from app.evaluation.attempt_ledger import read_records
from app.evaluation.provider_approval import ApprovalError, approval_payload, load_approval
from eval_scenario_support import expect
from eval_scenarios_budget_support import (
    APPROVED_AT,
    CASES,
    IDENTITY,
    LABELS,
    MODEL,
    PREAMBLE,
    approval_for,
    attempts,
    driver,
    dump,
    issue,
    kinds,
    load,
    reported,
    sealed,
    spend_for_scenarios,
    wire,
)


def scenario_budget_concurrency_cap(directory: Path) -> list[str]:
    """Concurrent provider calls cannot exceed the approved cap across threads."""
    problems: list[str] = []
    with wire() as (base_url, hits):
        _, binding = approval_for(directory, base_url=base_url, cap=8)
        config, announced = issue(directory, binding, "run")
        result = driver(
            directory,
            "parallel_calls",
            PREAMBLE
            + f"""
from concurrent.futures import ThreadPoolExecutor
from app.evaluation.attempt_ledger import ProviderBudgetExhausted

bind_run_guard()
client = adapter({binding.provider_base_url!r}, {binding.provider_model!r})
results = {{"ok": 0, "exhausted": 0, "other": []}}


def call():
    try:
        client._generate_sync("s", "u")
        return "ok"
    except ProviderBudgetExhausted:
        return "exhausted"
    except Exception as exc:
        return type(exc).__name__


with ThreadPoolExecutor(max_workers=24) as pool:
    for outcome in pool.map(lambda _: call(), range(24)):
        if outcome in ("ok", "exhausted"):
            results[outcome] += 1
        else:
            results["other"].append(outcome)
print(json.dumps(results))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
        outcome = reported(result, problems)
        expect(len(hits) == 8, f"the wire must see exactly the cap: {len(hits)}", problems)
        expect(outcome.get("ok") == 8, f"8 calls succeed: {outcome}", problems)
        expect(outcome.get("exhausted") == 16, f"16 calls refused: {outcome}", problems)
        expect(outcome.get("other") == [], f"no other failure: {outcome}", problems)
        counts = kinds(Path(binding.ledger_path))
        expect(counts.get("admitted") == 8, f"the ledger admitted the cap: {counts}", problems)
        expect(counts.get("refused") == 16, f"refusals are recorded: {counts}", problems)
        sequence = [record.seq for record in attempts(Path(binding.ledger_path))]
        expect(sequence == list(range(1, 9)), f"sequences are contiguous: {sequence}", problems)
        expect(
            all(record.request_sha256 for record in attempts(Path(binding.ledger_path))),
            "every admission digests the exact request body",
            problems,
        )
    return problems


def scenario_budget_failure_consumes_attempt(directory: Path) -> list[str]:
    """An HTTP failure spends its attempt: no refund, no retry for free."""
    problems: list[str] = []
    with wire(status=500) as (base_url, hits):
        _, binding = approval_for(directory, base_url=base_url, cap=2)
        config, announced = issue(directory, binding, "run")
        result = driver(
            directory,
            "failures",
            PREAMBLE
            + f"""
from app.evaluation.attempt_ledger import ProviderBudgetExhausted

bind_run_guard()
client = adapter({binding.provider_base_url!r}, {binding.provider_model!r})
failures, denied = [], 0
for _ in range(2):
    try:
        client._generate_sync("s", "u")
        failures.append("unexpected-success")
    except ProviderBudgetExhausted:
        failures.append("exhausted")
    except Exception as exc:
        failures.append(str(exc)[:40])
try:
    client._generate_sync("s", "u")
except ProviderBudgetExhausted:
    denied = 1
print(json.dumps({{"failures": failures, "denied": denied}}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
        outcome = reported(result, problems)
        expect(len(hits) == 2, f"two attempts reach the wire: {len(hits)}", problems)
        expect(
            outcome.get("denied") == 1,
            f"the third call is refused before the wire: {outcome}",
            problems,
        )
        expect(
            all("HTTP 500" in item or "failed" in item for item in outcome.get("failures", [])),
            f"both failed calls consumed their attempt: {outcome}",
            problems,
        )
        expect(
            kinds(Path(binding.ledger_path)).get("admitted") == 2,
            "failures are admitted, not refunded",
            problems,
        )
    return problems


def scenario_budget_unbound_and_tampered_config(directory: Path) -> list[str]:
    """An unbound, mismatched or raised configuration never reaches the wire."""
    problems: list[str] = []
    with wire() as (base_url, hits):
        _, binding = approval_for(directory, base_url=base_url, cap=4)
        config, announced = issue(directory, binding, "run")
        plain = driver(
            directory,
            "production",
            PREAMBLE
            + f"""
client = adapter({binding.provider_base_url!r}, {binding.provider_model!r})
print(json.dumps({{"guard": require_run_guard() is None, "body": client._generate_sync("s", "u")}}))
""",
        )
        outcome = reported(plain, problems)
        expect(outcome.get("guard") is True, f"no run binds no guard: {outcome}", problems)
        expect(len(hits) == 1, "ordinary production still reaches its provider", problems)

        unbound = driver(
            directory,
            "unbound",
            PREAMBLE
            + f"""
from app.evaluation.provider_guard import GuardNotBound
client = adapter({binding.provider_base_url!r}, {binding.provider_model!r})
try:
    client._generate_sync("s", "u")
    print(json.dumps({{"error": "sent"}}))
except GuardNotBound:
    print(json.dumps({{"error": "GuardNotBound"}}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
        outcome = reported(unbound, problems)
        expect(
            outcome.get("error") == "GuardNotBound",
            f"unbound fails closed: {outcome}",
            problems,
        )
        expect(len(hits) == 1, "an unbound run sends nothing", problems)

        tampered = driver(
            directory,
            "tampered",
            PREAMBLE
            + """
from app.evaluation.provider_approval import ApprovalError
try:
    bind_run_guard()
    print(json.dumps({"rejected": False}))
except ApprovalError:
    print(json.dumps({"rejected": True}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": "c" * 64},
        )
        outcome = reported(tampered, problems)
        expect(outcome.get("rejected") is True, f"tampered binding admitted: {outcome}", problems)

        raised = load(config)
        raised["max_provider_requests"] = 400
        dump(config, raised)
        refused = driver(
            directory,
            "raised",
            PREAMBLE
            + """
from app.evaluation.provider_approval import ApprovalError
try:
    bind_run_guard()
    print(json.dumps({"rejected": False}))
except ApprovalError:
    print(json.dumps({"rejected": True}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
        outcome = reported(refused, problems)
        expect(
            outcome.get("rejected") is True,
            f"a raised cap is refused: {outcome}",
            problems,
        )
        expect(len(hits) == 1, "no refused binding reaches the wire", problems)
    return problems


def scenario_budget_reused_approval_restart(directory: Path) -> list[str]:
    """A reused approval, a restart or a new output directory cannot reset the cap."""
    problems: list[str] = []
    with wire() as (base_url, hits):
        _, binding = approval_for(directory, base_url=base_url, cap=3)
        first, first_digest = issue(directory, binding, "first-output")
        second, second_digest = issue(directory, binding, "second-output")
        expect(first_digest == second_digest, "one approval issues one configuration", problems)
        expect(
            binding.ledger_path.endswith(f"{binding.run_id}.jsonl"),
            f"the ledger is keyed by the approval, not the output: {binding.ledger_path}",
            problems,
        )
        body = (
            PREAMBLE
            + f"""
from app.evaluation.attempt_ledger import ProviderBudgetExhausted

bind_run_guard()
client = adapter({binding.provider_base_url!r}, {binding.provider_model!r})
settled = {{"ok": 0, "exhausted": 0}}
for _ in range(CALLS):
    try:
        client._generate_sync("s", "u")
        settled["ok"] += 1
    except ProviderBudgetExhausted:
        settled["exhausted"] += 1
print(json.dumps(settled))
"""
        )
        spent = driver(
            directory,
            "spend",
            body.replace("CALLS", "2"),
            env={"EVAL_RUN_CONFIG": str(first), "EVAL_RUN_CONFIG_SHA256": first_digest},
        )
        outcome = reported(spent, problems)
        expect(outcome.get("ok") == 2, f"the first run spends two: {outcome}", problems)
        expect(len(hits) == 2, f"two wire hits: {len(hits)}", problems)

        again = driver(
            directory,
            "again",
            body.replace("CALLS", "3"),
            env={"EVAL_RUN_CONFIG": str(second), "EVAL_RUN_CONFIG_SHA256": second_digest},
        )
        outcome = reported(again, problems)
        expect(
            outcome.get("ok") == 1 and outcome.get("exhausted") == 2,
            f"a second output directory spends only what is left: {outcome}",
            problems,
        )
        expect(len(hits) == 3, f"the cap holds across runs: {len(hits)}", problems)
        claims = [
            record for record in read_records(Path(binding.ledger_path)) if record.kind == "claim"
        ]
        expect(
            all(claim.max_attempts == 3 for claim in claims),
            "the claim binds the approved cap",
            problems,
        )
    return problems


def scenario_budget_approval_rejections(directory: Path) -> list[str]:
    """No approval artifact shape can be manufactured into a budget."""
    problems: list[str] = []
    good = approval_payload(
        approved=True,
        approver="operator",
        approved_at=APPROVED_AT,
        identity_sha256=IDENTITY,
        labels_sha256=LABELS,
        case_count=CASES,
        provider_base_url="https://openrouter.ai/api/v1",
        provider_model=MODEL,
        max_provider_requests=40,
        reasoning_effort="none",
        spend_bound=spend_for_scenarios(),
        ledger_root=str(directory / "ledger"),
    )
    rejected = {
        "approval_not_approved": {**good, "approved": False},
        "approval_approver_missing": {**good, "approver": "  "},
        "approval_timestamp_invalid": {**good, "approved_at": "yesterday"},
        "approval_budget_invalid": {**good, "max_provider_requests": 0},
        "approval_budget_above_ceiling": {**good, "max_provider_requests": 100000},
        "approval_ledger_root_not_absolute": {**good, "ledger_root": "relative/ledger"},
        "approval_base_url_invalid": {**good, "provider_base_url": "not-a-url"},
        "approval_model_missing": {**good, "provider_model": ""},
        "approval_schema_invalid": {**good, "schema": "evaluation-approval-v1"},
        "approval_purpose_invalid": {**good, "purpose": "release"},
        "approval_digest_mismatch": {**good, "max_provider_requests": 41},
    }
    for expected, payload in rejected.items():
        path = dump(directory / "rejected.json", payload)
        try:
            load_approval(path, identity_sha256=IDENTITY, labels_sha256=LABELS, case_count=CASES)
        except ApprovalError as exc:
            expect(expected in str(exc), f"{expected} expected, got: {exc}", problems)
        else:
            problems.append(f"{expected}: a tampered approval was accepted")
    path = dump(directory / "foreign.json", good)
    try:
        load_approval(path, identity_sha256="d" * 64, labels_sha256=LABELS, case_count=CASES)
    except ApprovalError as exc:
        expect("approval_identity_mismatch" in str(exc), f"{exc}", problems)
    else:
        problems.append("a foreign identity was accepted")
    path = dump(directory / "good.json", good)
    load_approval(path, identity_sha256=IDENTITY, labels_sha256=LABELS, case_count=CASES)
    return problems


def scenario_budget_seal_fences_and_origin_denied(directory: Path) -> list[str]:
    """An unapproved origin or model never sends, and a seal fences later admission."""
    problems: list[str] = []
    with wire() as (base_url, hits):
        _, binding = approval_for(directory, base_url=base_url, cap=4)
        config, announced = issue(directory, binding, "run")
        result = driver(
            directory,
            "seal",
            PREAMBLE
            + f"""
from app.evaluation.attempt_ledger import LedgerSealed
from app.evaluation.provider_guard import GuardDenied

guard = bind_run_guard()
client = adapter({binding.provider_base_url!r}, {binding.provider_model!r})
denied = []
for bad in (
    adapter({binding.provider_base_url!r}, "some-other-model"),
    adapter("http://127.0.0.1:1/v1", {binding.provider_model!r}),
):
    try:
        bad._generate_sync("s", "u")
        denied.append("sent")
    except GuardDenied:
        denied.append("denied")
client._generate_sync("s", "u")
guard.ledger.seal()
after_seal = "sent"
try:
    client._generate_sync("s", "u")
except LedgerSealed:
    after_seal = "sealed"
print(json.dumps({{"denied": denied, "after_seal": after_seal}}))
""",
            env={"EVAL_RUN_CONFIG": str(config), "EVAL_RUN_CONFIG_SHA256": announced},
        )
        outcome = reported(result, problems)
        expect(outcome.get("denied") == ["denied", "denied"], f"{outcome}", problems)
        expect(outcome.get("after_seal") == "sealed", f"{outcome}", problems)
        expect(len(hits) == 1, f"only the approved call reached the wire: {len(hits)}", problems)
        counts = kinds(Path(binding.ledger_path))
        expect(counts.get("admitted") == 1, f"one admission: {counts}", problems)
        expect(counts.get("refused") == 2, f"both denials are recorded: {counts}", problems)
        expect(counts.get("sealed") == 1, f"the seal is durable: {counts}", problems)
        sealed(binding)
        expect(
            kinds(Path(binding.ledger_path)).get("sealed") == 1,
            "sealing twice keeps one fence",
            problems,
        )
    return problems
