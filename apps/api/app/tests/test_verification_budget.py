"""Failure matrix written before the isolated verification accounting module.

Do not send before durable reservation; never reset across attempts; count errors
and nested calls; reject stage/aggregate overspend, invalid bounds, missing usage,
wrong identity and stale in-flight work. Exact cents use integers, not floats.
This goal journal supplements, never replaces, the real monthly Redis ledger.
"""

import asyncio
import json

import pytest


def ledger(tmp_path, selected=1):
    from app.evaluation.verification_budget import VerificationBudget

    path = tmp_path / "goal.sqlite"
    VerificationBudget.create(path, binding="synthetic-bound-preflight", shadow_selected=selected)
    return VerificationBudget(path, binding="synthetic-bound-preflight")


def test_cumulative_stage_limits_survive_reopen(tmp_path):
    from app.evaluation.verification_budget import VerificationBudget

    budget = ledger(tmp_path)
    for _ in range(9):
        ticket = budget.reserve("smoke", 1)
        budget.settle(ticket, 0)
    reopened = VerificationBudget(tmp_path / "goal.sqlite", binding="synthetic-bound-preflight")
    with pytest.raises(ValueError):
        reopened.reserve("smoke", 1)
    with pytest.raises(FileExistsError):
        VerificationBudget.create(tmp_path / "goal.sqlite", binding="new", shadow_selected=1)
    with pytest.raises(ValueError):
        VerificationBudget(tmp_path / "goal.sqlite", binding="wrong")
    assert reopened.snapshot()["stages"]["smoke"]["requests"] == 9


def test_caps_reserve_before_spend_and_keep_unknown_cost(tmp_path):
    budget = ledger(tmp_path)
    ticket = budget.reserve("primary", 500_000_000)
    with pytest.raises(ValueError):
        budget.reserve("primary", 1)
    with pytest.raises(ValueError):
        budget.settle(ticket, None)
    assert budget.snapshot()["reserved_or_spent_nusd"] == 500_000_000
    assert budget.snapshot()["stopped"]
    with pytest.raises(ValueError):
        budget.reserve("shadow", 1)


@pytest.mark.parametrize("amount", [-1, 0, True, 1.5])
def test_invalid_bounds_never_create_requests(tmp_path, amount):
    budget = ledger(tmp_path)
    with pytest.raises(ValueError):
        budget.reserve("primary", amount)
    assert budget.snapshot()["reserved_or_spent_nusd"] == 0


async def test_counted_call_stops_after_failure_and_retains_evidence(tmp_path):
    budget = ledger(tmp_path)
    sent = []

    async def fails():
        sent.append(1)
        raise TimeoutError("synthetic")

    with pytest.raises(TimeoutError):
        await budget.call("smoke", 10_000_000, fails)
    with pytest.raises(ValueError):
        await budget.call("smoke", 10_000_000, fails)
    assert sent == [1]
    snapshot = budget.snapshot()
    assert snapshot["stages"]["smoke"]["requests"] == 1
    assert snapshot["reserved_or_spent_nusd"] == 10_000_000
    (tmp_path / "failure-accounting.json").write_text(json.dumps(snapshot, indent=2))


async def test_nested_and_concurrent_calls_share_shadow_cap(tmp_path):
    budget = ledger(tmp_path, selected=1)

    async def zero():
        await asyncio.sleep(0)
        return {"cost_nusd": 0, "result": "synthetic"}

    results = await asyncio.gather(
        *(budget.call("shadow", 1, zero) for _ in range(7)), return_exceptions=True
    )
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert budget.snapshot()["stages"]["shadow"]["requests"] == 6


def test_inflight_reopen_and_overbound_cost_fail_closed(tmp_path):
    from app.evaluation.verification_budget import VerificationBudget

    budget = ledger(tmp_path)
    ticket = budget.reserve("primary", 10)
    with pytest.raises(ValueError):
        VerificationBudget(tmp_path / "goal.sqlite", binding="synthetic-bound-preflight")
    with pytest.raises(ValueError):
        budget.settle(ticket, 11)
    assert budget.snapshot()["stopped"]
    assert budget.snapshot()["reserved_or_spent_nusd"] == 11
