"""Paid verification must reject unfunded origins and close interrupted authority.

Failure modes are trailing-slash funding bypass, a foreign-origin exemption,
insufficient account credit and a collector failure leaving admissions open.
"""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.evaluation import provider_funding
from app.evaluation.spend_bound import PROVIDER_BASE_URL


@pytest.mark.parametrize("origin", [PROVIDER_BASE_URL, PROVIDER_BASE_URL + "/"])
def test_unfunded_provider_is_blocked_for_both_supported_url_forms(monkeypatch, origin):
    def response(*_args, **_kwargs):
        return io.BytesIO(b'{"data":{"total_credits":1,"total_usage":2}}')

    monkeypatch.setattr(provider_funding, "_guarded_opener", lambda: SimpleNamespace(open=response))
    with pytest.raises(provider_funding.FundingError):
        provider_funding.verify_provider_funding(origin, "synthetic-no-key")


def test_foreign_origin_cannot_silently_skip_funding():
    with pytest.raises(provider_funding.FundingError):
        provider_funding.verify_provider_funding("https://example.invalid/v1", "synthetic-no-key")


@pytest.mark.parametrize("interrupt", [False, True])
def test_failed_collection_seals_and_attests_existing_admission(tmp_path, monkeypatch, interrupt):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "tools/release"))
    driver = importlib.import_module("eval_runner")
    fixtures = importlib.import_module("eval_scenarios_budget_support")
    approval, binding = fixtures.approval_for(tmp_path, base_url="http://127.0.0.1:9/v1")
    ledger = binding.ledger()
    ledger.claim()
    ledger.admit(
        stage="synthetic",
        model=binding.provider_model,
        base_url=binding.provider_base_url,
        request_sha256="f" * 64,
        output_limit=1200,
    )
    service = SimpleNamespace(binding=binding, config_path=tmp_path / "config.json")

    def fail_collection(*_args, **_kwargs):
        if interrupt:
            raise KeyboardInterrupt("controlled interruption")
        raise driver.RunnerFailure("controlled collection failure")

    monkeypatch.setattr(
        driver,
        "service_settings",
        lambda *_args, **_kwargs: (service, approval, fixtures.proof_key_for(binding)),
    )
    monkeypatch.setattr(driver, "clean_env", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(driver, "_start_candidate", lambda **_kwargs: object())
    monkeypatch.setattr(driver, "wait_ready", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(driver, "stop_process", lambda *_args: [])
    monkeypatch.setattr(driver, "run_cli", fail_collection)
    output = tmp_path / "output"
    code = driver.main(
        [
            "--profile",
            "service",
            "--db-url",
            "postgresql://fixture:fixture@127.0.0.1:9/fixture",
            "--output",
            str(output),
            "--approval",
            str(tmp_path / "approval.json"),
        ]
    )
    summary = json.loads((output / "run-summary.json").read_text())
    state = ledger.snapshot()
    assert code == 1
    assert state.sealed is True
    assert state.upper_cost_nano_usd == binding.spend_bound.reservation_nano_usd
    assert summary["provider_guard"]["attestation"]["sealed"] is True
    assert "controlled" in summary["error"]
