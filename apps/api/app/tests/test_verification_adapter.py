"""Counted transport failure matrix, specified before implementation.

Reserve before sending, require a fresh verified bound per request, count nested
adapter instances against one journal, and never retry or follow redirects.
Missing/nonfinite/negative cost, wrong model, malformed content and cancellation
must retain the reservation and stop subsequent traffic. Production code/settings
must remain untouched; this is synthetic transport, not a compatibility pass.
"""

import json

import httpx
import pytest
from app.evaluation.verification_budget import VerificationBudget


def make_budget(tmp_path):
    path = tmp_path / "counted.sqlite"
    VerificationBudget.create(path, binding="synthetic", shadow_selected=1)
    return VerificationBudget(path, binding="synthetic")


async def test_transport_preserves_schema_and_reserves_before_send(tmp_path):
    from app.evaluation.verification_adapter import CountedVerificationAdapter

    budget = make_budget(tmp_path)
    seen = []

    async def verify(payload):
        assert payload["model"] == "deepseek/deepseek-v4.1-flash"
        assert payload["max_tokens"] == 600
        return 10_000_000

    def respond(request):
        assert budget.snapshot()["stages"]["smoke"]["requests"] == len(seen) + 1
        body = json.loads(request.content)
        seen.append(body)
        assert body["response_format"]["type"] == "json_schema"
        assert body["provider"]["require_parameters"] is True
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "usage": {"cost": 0.0000000001},
                "choices": [{"message": {"content": "{}"}}],
            },
        )

    for _ in range(2):
        adapter = CountedVerificationAdapter(
            api_key="synthetic",
            budget=budget,
            stage="smoke",
            verify_request=verify,
            transport=httpx.MockTransport(respond),
        )
        adapter.max_tokens = 600
        adapter.response_schema = {"type": "object"}
        assert await adapter.generate(system="synthetic", user="synthetic") == "{}"
        assert adapter.last_metadata["usage"]["cost"] == 0.0000000001
    assert budget.snapshot()["reserved_or_spent_nusd"] == 2  # round up, never down
    (tmp_path / "transport-evidence.json").write_text(
        json.dumps({"requests": seen, "journal": budget.snapshot()}, indent=2)
    )


@pytest.mark.parametrize(
    "fault",
    ["redirect", "http_error", "missing_cost", "nan", "negative", "missing_content", "wrong_model"],
)
async def test_transport_failure_stops_without_retry(tmp_path, fault):
    from app.evaluation.verification_adapter import CountedVerificationAdapter

    budget = make_budget(tmp_path)
    requests = []

    async def verify(payload):
        return 10_000_000

    def respond(request):
        requests.append(str(request.url))
        body = {
            "model": "deepseek/deepseek-v4.1-flash",
            "usage": {"cost": 0},
            "choices": [{"message": {"content": "{}"}}],
        }
        if fault == "redirect":
            return httpx.Response(307, headers={"location": "https://other.invalid/completions"})
        if fault == "http_error":
            return httpx.Response(429)
        if fault == "missing_cost":
            body["usage"] = {}
        elif fault == "nan":
            body["usage"]["cost"] = "NaN"
        elif fault == "negative":
            body["usage"]["cost"] = -1
        elif fault == "missing_content":
            body["choices"] = []
        elif fault == "wrong_model":
            body["model"] = "other-model"
        return httpx.Response(200, json=body)

    adapter = CountedVerificationAdapter(
        api_key="synthetic",
        budget=budget,
        stage="smoke",
        verify_request=verify,
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await adapter.generate(system="synthetic", user="synthetic")
    with pytest.raises(ValueError):
        await adapter.generate(system="synthetic", user="synthetic")
    assert len(requests) == 1
    assert budget.snapshot()["stopped"]
    assert budget.snapshot()["reserved_or_spent_nusd"] == 10_000_000


async def test_unverified_bound_never_transmits(tmp_path):
    from app.evaluation.verification_adapter import CountedVerificationAdapter

    budget = make_budget(tmp_path)

    async def unavailable(payload):
        raise ValueError("real ledger or price bound unavailable")

    def forbidden(request):
        pytest.fail("Unverified request transmitted")

    adapter = CountedVerificationAdapter(
        api_key="synthetic",
        budget=budget,
        stage="primary",
        verify_request=unavailable,
        transport=httpx.MockTransport(forbidden),
    )
    with pytest.raises(ValueError):
        await adapter.generate(system="synthetic", user="synthetic")
    assert budget.snapshot()["stages"]["primary"]["requests"] == 0
