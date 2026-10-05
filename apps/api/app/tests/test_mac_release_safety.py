"""Release safety failure modes specified before the Mac candidate fixes.

Synthetic only: concurrent admission must include inherited and pending exposure,
owner directions cannot lift $6, malformed usage must retain reservations, and
restoration must verify the acknowledged deployment and prior commit while
continuing to restore other services. No provider or deployment calls occur.
"""

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.evaluation.verification_budget import VerificationBudget
from app.services import analyst_budget
from app.services.deploy_release import deploy


def test_shared_cap_includes_inherited_and_concurrent_pending(tmp_path):
    path = tmp_path / "goal.sqlite"
    VerificationBudget.create(
        path,
        binding="synthetic",
        shadow_selected=120,
        inherited_calls=[
            {
                "id": 1,
                "stage": "primary",
                "amount_nusd": 5_900_000_000,
                "status": "failed",
                "error": "retained_unknown",
            }
        ],
    )
    budget = VerificationBudget(path, binding="synthetic")
    direction = Path(__file__).resolve().parents[4] / (
        "docs/release-evidence/implementation-20261001/confirmed-spending-direction.json"
    )
    budget.apply_spending_direction(direction)

    def reserve(_):
        try:
            return budget.reserve("shadow", 60_000_000)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        tickets = list(executor.map(reserve, range(3)))
    snapshot = budget.snapshot()
    assert sum(ticket is not None for ticket in tickets) == 1
    assert snapshot["reserved_or_spent_nusd"] == 5_960_000_000
    assert snapshot["aggregate_hard_cap_nusd"] == 6_000_000_000
    (tmp_path / "shared-cap-proof.json").write_text(json.dumps(snapshot, indent=2))


@pytest.mark.parametrize("cost", [None, True, "0.01", -1, math.nan, math.inf, 10**400])
async def test_invalid_cost_never_releases_reservation(monkeypatch, cost):
    touched = []

    async def connection():
        touched.append(True)
        raise AssertionError("Malformed cost reached Redis")

    monkeypatch.setattr(analyst_budget, "_redis", connection)
    reservation = analyst_budget.BudgetReservation("ai-budget:synthetic", "held", 0.03)
    await reservation.settle(cost)
    assert not touched


def release_record():
    return {
        "tested_commit": "a" * 40,
        "services": {
            name: {"id": name, "url": "https://" + name + ".example"} for name in ("api", "web")
        },
        "rollback": {
            "api_deployment": "old-api",
            "web_deployment": "old-web",
            "data_version": "v1",
            "qdrant_aliases": {"games": "v1"},
        },
        "deployments": {},
    }


@pytest.mark.parametrize("mismatch", ["id", "commit", "missing"])
def test_rollback_mismatch_restores_remaining_service(mismatch, tmp_path):
    record = release_record()
    restored = []

    def request(path, payload):
        if path.endswith("/old-api") or path.endswith("/old-web"):
            name = "api" if path.endswith("/old-api") else "web"
            return {"id": "old-" + name, "status": "live", "commit": {"id": "b" * 40}}
        if "?limit=" in path:
            return []
        if path.endswith("/rollback"):
            name = path.split("/")[1]
            restored.append(name)
            return {"id": "restored-" + name}
        return {"id": "candidate-" + path.split("/")[1]}

    def wait(service, identity):
        if identity.startswith("candidate-"):
            return {"id": identity, "commit": {"id": "a" * 40}}
        result = {"id": identity, "commit": {"id": "b" * 40}}
        if service == "web":
            if mismatch == "missing":
                return {}
            if mismatch == "id":
                result["id"] = "unrelated"
            else:
                result["commit"]["id"] = "c" * 40
        return result

    def fail_smoke(*_):
        raise RuntimeError("synthetic smoke failure")

    with pytest.raises(RuntimeError, match="Promotion stopped"):
        deploy(record, lambda _: None, request=request, wait=wait, smoke_check=fail_smoke)
    assert restored == ["web", "api"]
    assert record["rollout"]["status"] == "restoration_failed"
    (tmp_path / "rollback-proof.json").write_text(json.dumps(record, indent=2))


def test_unverifiable_prior_deployment_prevents_mutation():
    calls = []

    def request(path, payload):
        calls.append(payload)
        return {"id": "wrong", "commit": {"id": "b" * 40}}

    with pytest.raises(RuntimeError):
        deploy(
            release_record(),
            lambda _: None,
            request=request,
            wait=lambda *_: {},
            smoke_check=lambda *_: None,
        )
    assert calls and all(payload is None for payload in calls)
