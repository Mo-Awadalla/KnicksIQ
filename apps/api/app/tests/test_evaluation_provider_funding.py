"""Unfunded or malformed provider accounting must not start a paid evaluation.

Failure modes are debt, an exactly empty balance, booleans mistaken for money,
missing amounts, negative counters, nonfinite amounts and wrong JSON types.
"""

from decimal import Decimal

import pytest
from app.evaluation.provider_funding import FundingError, positive_credit_balance


def test_available_credit_is_computed_without_binary_float_rounding():
    available = positive_credit_balance({"data": {"total_credits": 10, "total_usage": 4.75}})
    assert available == Decimal("5.25")


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {"total_credits": 35, "total_usage": 35.204531272}},
        {"data": {"total_credits": 10, "total_usage": 10}},
        {"data": {"total_credits": 0, "total_usage": 0}},
        {"data": {"total_credits": True, "total_usage": 0}},
        {"data": {"total_credits": 10, "total_usage": False}},
        {"data": {"total_credits": "10", "total_usage": 0}},
        {"data": {"total_credits": -1, "total_usage": 0}},
        {"data": {"total_credits": 10, "total_usage": -1}},
        {"data": {"total_credits": float("inf"), "total_usage": 0}},
        {"data": {"total_credits": 10, "total_usage": float("nan")}},
        {"data": {"total_credits": 10}},
        {"data": None},
        {},
    ],
)
def test_unfunded_or_unverifiable_accounting_cannot_authorize_a_run(payload):
    with pytest.raises(FundingError):
        positive_credit_balance(payload)
