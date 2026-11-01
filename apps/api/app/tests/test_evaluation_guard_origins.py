from __future__ import annotations

import pytest
from app.evaluation.provider_guard import scope_for


@pytest.mark.parametrize("host", ["127.1", "2130706433", "0x7f000001", "0177.0.0.1"])
def test_numeric_loopback_cannot_claim_provider_quality(host):
    assert scope_for(f"http://{host}:18400/v1") == "local_fake"
