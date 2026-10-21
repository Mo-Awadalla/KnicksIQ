"""Read-only readiness check for a release candidate that will serve llm_primary.

Checks, and the failure each one must catch, were written before the probes:

env.required
    A required variable is absent, blank, or whitespace only. Secrets are never printed.
env.parse
    pydantic rejects a parsed value, for example a shadow rate above 1. The report names the field
    and message only, never the rejected input.
env.mode
    ANALYSIS_ANSWER_MODE is not the intended launch mode. A still-shadow deployment fails before a
    flip, which keeps the check honest about deployed state.
env.evidence_loop
    ANALYST_EVIDENCE_LOOP_ENABLED is false. llm_primary would then bypass the evidence loop.
env.provider
    The provider is not OpenRouter, the base URL is not HTTPS, the model name is blank, or the API
    key is absent. Presence only; the key is never copied into the report.
env.allowlist
    The allowlist is empty, has a wildcard or duplicates, or omits the configured chat or summary
    model. A typo would send requests to an unapproved model.
env.timeouts
    A timeout is zero, negative, above the analyst deadline, or the deadline exceeds 30 seconds.
env.cutoff
    The monthly cutoff is absent, non-positive, or different from the documented launch value.
env.shadow_rate
    The rate is outside 0..1, or a shadow deployment disables sampling entirely.
env.cors
    The origin list is empty, has a wildcard, a non-HTTPS origin, a trailing slash, or omits
    PUBLIC_WEB_ORIGIN. The browser path would be blocked while the API still looks healthy.
env.trusted_hosts
    The list is empty, has a wildcard or scheme, or omits the public API host.
env.sentry
    SENTRY_DSN is absent or does not parse as an HTTPS DSN. Presence and shape only.
env.ip_hash_secret
    The value is the development default or shorter than 32 characters.
env.environment
    The process is not configured for production, so production-only readiness checks are skipped.
env.require_release
    REQUIRE_ACTIVE_RELEASE is false and an empty database could still report ready.
target.live
    The target is unreachable, non-200, or does not return {"status": "ok"}.
target.ready
    The target returns 503 / not_ready, reports required failures, omits an active release, or its
    data_version does not match the database.
target.cors
    The preflight OPTIONS request does not return the exact public origin.
target.trusted_host
    An unknown Host header is accepted, so host filtering is misconfigured or disabled.
ledger.present
    Redis is unreachable or ai-budget:YYYY-MM is absent. Code starts a missing ledger at zero, but
    launch readiness needs an observed ledger so spend cannot be mistaken for zero.
ledger.month
    The selected ledger key belongs to another UTC month.
ledger.consistent
    The total is not numeric, a reservation is non-numeric or non-positive, reservations exceed the
    total, or the key has a TTL. reserve() and settle() would then disagree about spend.
ledger.capacity
    The recorded total already exceeds the configured cutoff. Every further model call degrades.
kill_switch
    A season-level record probe fails when the response is non-200, still reports a validated
    model answer, has no citations, or the answer does not match the regular-season record, does
    not state that phase, or leaks the overall record. A second question that names "overall" must
    return all-phase wins/losses instead.
provider_failure
    A provider exception escapes the request, or the fallback has no citations or the same wrong
    record scope. Degradation would then be unsafe.

The script is read-only except for Redis session/rate-limit keys created by ordinary requests and
one settled failed-call reservation during the provider-failure probe.

Usage:
    uv run --package knicksiq-api python tools/release/preflight_llm_primary.py \
        --json-out docs/release-evidence/llm-primary-20261021/ops/preflight.json

With --base-url the script probes that API and reports its own configuration checks from the
current process environment unless --skip-env is set. The kill-switch and provider-failure probes
need control of the target process, so they are skipped for a remote target.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
