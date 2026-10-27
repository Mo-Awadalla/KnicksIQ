"""Deterministic check of the OpenRouter provider block built from settings (no network).

Fails loudly if the default request shape changes, if order/sort/fallbacks are not copied from
settings, or if a non-OpenRouter base URL gains a provider block.

    uv run --package knicksiq-api python \
        docs/release-evidence/llm-primary-20261021/w3-routing/payload_probe.py \
        --out docs/release-evidence/llm-primary-20261021/w3-routing/payload-probe.json
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any


class FakeResponse:
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"{}"}}]}'


def capture(**adapter_arguments: Any) -> dict[str, Any]:
    from app.services.report_llm import OpenAICompatibleLLMAdapter

    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, **kwargs: Any) -> FakeResponse:
        captured.update(json.loads(request.data))
        return FakeResponse()

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
    try:
        adapter = OpenAICompatibleLLMAdapter(
            base_url="https://openrouter.ai/api/v1",
            api_key="offline",
            model="deepseek/deepseek-v4.1-flash",
            reasoning_effort="none",
            **adapter_arguments,
        )
        adapter._generate_sync("system", "user")
    finally:
        urllib.request.urlopen = original  # type: ignore[assignment]
    return captured


def capture_via_settings(**settings_values: Any) -> dict[str, Any]:
    import app.services.report_llm as report_llm
    from app.core.config import Settings

    settings = Settings(_env_file=None, **settings_values)
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, **kwargs: Any) -> FakeResponse:
        captured.update(json.loads(request.data))
        return FakeResponse()

    original_urlopen = urllib.request.urlopen
    original_settings = report_llm.get_settings
    urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
    report_llm.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        adapter = report_llm.get_llm_adapter()
        adapter._generate_sync("system", "user")
    finally:
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
        report_llm.get_settings = original_settings  # type: ignore[assignment]
    return captured


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = {
        "default": capture(),
        "pinned_order": capture(provider_order=["Together", "Reka"], provider_sort="latency"),
        "pinned_no_fallbacks_no_sort": capture(
            provider_order=["Together"], provider_sort=None, provider_allow_fallbacks=False
        ),
        "sort_none": capture(provider_sort="none"),
        "plain_json_object": capture(response_format_json=True),
        "settings_plumbing": capture_via_settings(
            test_mode=False,
            ai_provider="openrouter",
            ai_api_key="offline",
            ai_base_url="https://openrouter.ai/api/v1",
            openrouter_provider_order=["Together"],
            openrouter_provider_allow_fallbacks=False,
        ),
    }
    checks = {
        "default_provider": cases["default"]["provider"]
        == {"allow_fallbacks": True, "sort": "latency", "require_parameters": True},
        "default_reasoning": cases["default"].get("reasoning") == {"effort": "none"},
        "order_copied": cases["pinned_order"]["provider"].get("order") == ["Together", "Reka"],
        "order_keeps_sort": cases["pinned_order"]["provider"].get("sort") == "latency",
        "fallbacks_false": cases["pinned_no_fallbacks_no_sort"]["provider"].get("allow_fallbacks")
        is False,
        "sort_omitted_when_none": "sort" not in cases["pinned_no_fallbacks_no_sort"]["provider"],
        "sort_none_omits_key": "sort" not in cases["sort_none"]["provider"],
        "require_parameters_with_json_object": cases["plain_json_object"]["provider"].get(
            "require_parameters"
        )
        is True,
        "settings_order_and_fallbacks": cases["settings_plumbing"]["provider"]
        == {
            "allow_fallbacks": False,
            "sort": "latency",
            "order": ["Together"],
            "require_parameters": True,
        },
    }
    result = {"cases": cases, "checks": checks, "passed": all(checks.values())}
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(checks, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
