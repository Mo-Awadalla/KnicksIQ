"""Conservative context reservations and durable dollar accounting.

Failure modes are underestimated context charges, refund on malformed usage,
completion overrun, unpriced addons, expensive routing, concurrent overdraft,
restart resets, duplicate refunds and settlement of an unknown attempt.
These cases precede the ledger-spend implementation.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from app.evaluation.attempt_ledger import AttemptLedger, LedgerError, ProviderBudgetExhausted
from app.evaluation.ledger_state import LedgerBinding
from app.evaluation.spend_bound import PROVIDER_BASE_URL, PROVIDER_MODEL, SpendBound, SpendError


def _bound() -> SpendBound:
    return SpendBound.from_dict(
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


def _request() -> dict:
    return {
        "model": PROVIDER_MODEL,
        "messages": [
            {"role": "system", "content": "Use the archive."},
            {"role": "user", "content": "Record?"},
        ],
        "max_tokens": 1200,
        "temperature": 0,
    }


def _ledger(path, bound: SpendBound | None = None) -> AttemptLedger:
    return AttemptLedger(
        path,
        binding=LedgerBinding(
            run_id="usd-proof",
            config_sha256="a" * 64,
            approval_sha256="b" * 64,
            max_attempts=720,
            model=PROVIDER_MODEL,
            base_url=PROVIDER_BASE_URL,
            spend_bound=bound or replace(_bound(), max_total_nano_usd=60_000_000),
        ),
    )


def _admit(ledger: AttemptLedger) -> int:
    return ledger.admit(
        stage="proof",
        model=PROVIDER_MODEL,
        base_url=PROVIDER_BASE_URL,
        request_sha256="c" * 64,
        output_limit=1200,
    )


def test_reservation_covers_the_entire_published_context_and_output():
    bound = _bound()
    assert bound.reservation_nano_usd == 47_785_920
    usage = bound.usage({"prompt_tokens": 8000, "completion_tokens": 1200}, output_limit=1200)
    assert usage is not None
    assert bound.charge(usage) == 960_000
    full = bound.usage({"prompt_tokens": 1_048_576, "completion_tokens": 1200}, output_limit=1200)
    assert full is not None
    assert bound.charge(full) == bound.reservation_nano_usd


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": -1, "completion_tokens": 1},
        {"prompt_tokens": True, "completion_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": 1201},
        {"prompt_tokens": 1_048_577, "completion_tokens": 1},
        {"prompt_tokens": 1.5, "completion_tokens": 1},
        {"cost": 0},
    ],
)
def test_unverified_usage_never_refunds_a_durable_reservation(tmp_path, usage):
    ledger = _ledger(tmp_path / "budget.jsonl")
    ledger.claim()
    seq = _admit(ledger)
    assert ledger.settle(seq, usage) is False
    restarted = _ledger(ledger.path)
    assert restarted.snapshot().upper_cost_nano_usd == 47_785_920
    with pytest.raises(ProviderBudgetExhausted):
        _admit(restarted)


def test_validated_usage_refunds_once_and_cannot_reopen_spent_headroom(tmp_path):
    ledger = _ledger(tmp_path / "budget.jsonl")
    ledger.claim()
    seq = _admit(ledger)
    with pytest.raises(ProviderBudgetExhausted):
        _admit(ledger)
    usage = {"prompt_tokens": 8000, "completion_tokens": 1200}
    assert ledger.settle(seq, usage) is True
    assert ledger.snapshot().upper_cost_nano_usd == 960_000
    assert ledger.settle(seq, usage) is False
    assert _admit(ledger) == 2
    assert ledger.snapshot().upper_cost_nano_usd == 48_745_920
    with pytest.raises(ProviderBudgetExhausted):
        _admit(ledger)
    with pytest.raises(LedgerError):
        ledger.settle(seq, {"prompt_tokens": 1, "completion_tokens": 1})


def test_concurrent_attempts_cannot_overdraw_the_dollar_cap(tmp_path):
    ledger = _ledger(tmp_path / "budget.jsonl")
    ledger.claim()

    def attempt(_):
        try:
            return _admit(ledger)
        except ProviderBudgetExhausted:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(attempt, range(8)))
    assert [seq for seq in admitted if seq is not None] == [1]
    assert ledger.snapshot().upper_cost_nano_usd == 47_785_920
    assert _ledger(ledger.path).used == 1


def test_unknown_settlement_never_creates_spendable_credit(tmp_path):
    ledger = _ledger(tmp_path / "budget.jsonl")
    ledger.claim()
    with pytest.raises(LedgerError):
        ledger.settle(1, {"prompt_tokens": 1, "completion_tokens": 1})
    assert ledger.snapshot().upper_cost_nano_usd == 0
    assert _admit(ledger) == 1


def test_prepared_wire_pins_prices_provider_set_and_reasoning():
    bound = _bound()
    body = _request()
    bound.prepare(body)
    assert bound.validate_request(json.dumps(body).encode(), model=PROVIDER_MODEL) == 1200
    assert body["provider"]["max_price"] == {"prompt": 0.045, "completion": 0.5, "request": 0}
    assert body["provider"]["allow_fallbacks"] is False
    assert body["reasoning"]["effort"] == "none"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body.update(max_tokens=1201),
        lambda body: body.update(plugins=[{"id": "web"}]),
        lambda body: body.update(models=["another-model"]),
        lambda body: body["reasoning"].update(effort="high"),
        lambda body: body["provider"]["max_price"].update(prompt=0.046),
        lambda body: body["provider"].update(only=["unapproved"]),
        lambda body: body["provider"].update(allow_fallbacks=True),
    ],
)
def test_cost_bypasses_are_refused_before_the_wire(mutation):
    bound = _bound()
    body = _request()
    bound.prepare(body)
    mutation(body)
    with pytest.raises(SpendError):
        bound.validate_request(json.dumps(body).encode(), model=PROVIDER_MODEL)
