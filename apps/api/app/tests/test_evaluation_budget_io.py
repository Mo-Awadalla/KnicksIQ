from __future__ import annotations

import os

import pytest
from app.evaluation.attempt_ledger import AttemptLedger, LedgerError, ProviderBudgetExhausted
from app.evaluation.ledger_state import LedgerBinding
from app.evaluation.spend_bound import SpendBound


def ledger_at(tmp_path):
    spend = SpendBound.from_dict(
        {
            "max_total_nano_usd": 2_000_000_000,
            "model_context_tokens": 1_048_576,
            "max_completion_tokens": 1200,
            "prompt_nano_usd_per_token": 45,
            "completion_nano_usd_per_token": 500,
            "provider_tags": ["open-inference/fp4", "morph/fp8", "baidu/fp8", "wafer/us"],
            "pricing_sha256": "1" * 64,
            "endpoints_sha256": "2" * 64,
        }
    )
    ledger = AttemptLedger(
        tmp_path / "attempts.jsonl",
        binding=LedgerBinding(
            run_id="io-proof",
            config_sha256="a" * 64,
            approval_sha256="b" * 64,
            max_attempts=1,
            model="local-fake",
            base_url="http://127.0.0.1:1/v1",
            spend_bound=spend,
        ),
    )
    ledger.claim()
    return ledger


def reserve(ledger):
    return ledger.admit(
        stage="orchestrate",
        model="local-fake",
        base_url="http://127.0.0.1:1/v1",
        request_sha256="c" * 64,
        output_limit=1200,
    )


def test_short_writes_still_persist_one_complete_admission(tmp_path, monkeypatch):
    ledger = ledger_at(tmp_path)
    original = os.write
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda fd, data: original(fd, data[:7]))
        assert reserve(ledger) == 1
    assert ledger.used == 1
    with pytest.raises(ProviderBudgetExhausted):
        reserve(ledger)
    assert ledger.used == 1


def test_zero_write_refuses_admission_without_spending_or_resetting(tmp_path, monkeypatch):
    ledger = ledger_at(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda fd, data: 0)
        with pytest.raises((OSError, LedgerError)):
            reserve(ledger)
    assert ledger.used == 0
    assert reserve(ledger) == 1
    assert ledger.used == 1


def test_failed_partial_write_cannot_reopen_budget(tmp_path, monkeypatch):
    ledger = ledger_at(tmp_path)
    original = os.write
    calls = 0

    def interrupted(fd, data):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("synthetic disk failure")
        return original(fd, data[:7])

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", interrupted)
        with pytest.raises(OSError):
            reserve(ledger)
    with pytest.raises(LedgerError):
        reserve(ledger)
