"""Read-only provider funding checks before an evaluation acquires its authority."""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from app.evaluation.spend_bound import PROVIDER_BASE_URL
from app.services.report_llm import _guarded_opener


class FundingError(ValueError):
    pass


def positive_credit_balance(payload: Any) -> Decimal:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise FundingError("Provider credit accounting has no usable data")
    amounts = []
    for name in ("total_credits", "total_usage"):
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise FundingError("Provider credit accounting has an invalid amount")
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise FundingError("Provider credit accounting has an invalid amount")
        amounts.append(amount)
    balance = amounts[0] - amounts[1]
    if balance <= 0:
        raise FundingError("Provider credit balance is not positive; funding is required")
    return balance


def verify_provider_funding(provider_base_url: str, api_key: str) -> None:
    origin = provider_base_url.strip().rstrip("/")
    if origin != PROVIDER_BASE_URL:
        try:
            parts = urlsplit(origin)
            host = parts.hostname or ""
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError as exc:
            raise FundingError("Provider funding origin is invalid or not a local fake") from exc
        if local and parts.scheme in {"http", "https"}:
            return
        raise FundingError("Only the approved provider or a local fake may pass funding checks")
    request = urllib.request.Request(
        PROVIDER_BASE_URL + "/credits",
        headers={"Authorization": "Bearer " + api_key},
        method="GET",
    )
    try:
        with _guarded_opener().open(request, timeout=10) as response:
            payload = json.loads(response.read(), parse_float=Decimal)
    except urllib.error.HTTPError as exc:
        raise FundingError(f"Read-only provider funding check failed with HTTP {exc.code}") from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise FundingError("Read-only provider funding check could not be verified") from exc
    positive_credit_balance(payload)
