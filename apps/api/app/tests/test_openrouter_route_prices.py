"""Isolated payload boundary: route disclosure and financial limits travel together."""

import io
import json

import pytest
from app.core.config import Settings
from app.services.report_llm import OpenAICompatibleLLMAdapter, get_llm_adapter
from pydantic import ValidationError


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("base", ["https://openrouter.ai/api/v1", "https://compatible.invalid/v1"])
def test_actual_adapter_wire_payload_is_pinned(monkeypatch, base, structured):
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        test_mode=False,
        ai_provider="openrouter",
        ai_base_url=base,
        ai_api_key="synthetic-no-paid-call",
        ai_request_timeout_seconds=20,
        openrouter_provider_route="atlas-cloud/fp8",
        openrouter_max_prompt_price=0.141,
        openrouter_max_completion_price=0.564,
    )
    monkeypatch.setattr("app.services.report_llm.get_settings", lambda: settings)
    adapter = get_llm_adapter(response_format_json=structured)
    assert isinstance(adapter, OpenAICompatibleLLMAdapter)
    if structured:
        adapter.response_schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    attempts = []

    def isolated_urlopen(request, *, timeout, context):
        assert timeout == 20 and context.check_hostname
        payload = json.loads(request.data)
        attempts.append(payload)
        if "openrouter.ai" in base:
            assert payload["provider"] == {
                "only": ["atlas-cloud/fp8"],
                "order": ["atlas-cloud/fp8"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "quantizations": ["fp8"],
                "max_price": {"prompt": 0.141, "completion": 0.564, "request": 0},
            }
        else:
            assert "provider" not in payload
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", isolated_urlopen)
    assert adapter._generate_sync("system", "user") == "{}"
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "policy",
    [
        {"openrouter_provider_route": "atlas-cloud/fp8"},
        {"openrouter_max_prompt_price": 0.141, "openrouter_max_completion_price": 0.564},
        {"openrouter_provider_route": "atlas-cloud/fp8", "openrouter_max_prompt_price": 0.141},
        {"openrouter_provider_route": ""},
        {"openrouter_max_prompt_price": -0.1},
        {"openrouter_max_prompt_price": float("nan")},
        {"openrouter_max_completion_price": float("inf")},
    ],
)
def test_incomplete_or_nonfinite_route_policy_fails_startup(policy):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **policy)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("price", [None, -0.1, float("nan"), float("inf"), True, "0.141"])
def test_direct_adapter_cannot_bypass_policy_validation(price):
    with pytest.raises(ValueError):
        OpenAICompatibleLLMAdapter(
            base_url="https://openrouter.ai/api/v1",
            api_key="synthetic-no-paid-call",
            model="deepseek/deepseek-v4.1-flash",
            provider_route="atlas-cloud/fp8",
            max_prompt_price=price,
            max_completion_price=0.564,
        )
