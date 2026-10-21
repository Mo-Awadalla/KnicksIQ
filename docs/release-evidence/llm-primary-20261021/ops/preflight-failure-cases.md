# Preflight failure cases and observed results

`tools/release/preflight_llm_primary.py` and `tools/release/preflight/` implement the checks. The
expected failure behavior was written before any observed run and is repeated in the entrypoint
docstring.

Method: every case is one invocation with exactly one input broken and `--only <check>` so the run
isolates that check. The unmodified environment produced `preflight.json` with 25/25 checks
`pass` and exit code 0. Each case below exited 1 with the named check `fail`. Raw observations are
in `preflight-failures.json`.

| Check | Broken input | Observed detail |
| --- | --- | --- |
| env.required | `AI_API_KEY` unset | missing or blank variables: AI_API_KEY |
| env.parse | `ANALYSIS_SHADOW_SAMPLE_RATE=1.5` | settings rejected: analysis_shadow_sample_rate above 1 |
| env.mode | `ANALYSIS_ANSWER_MODE=shadow` | configured shadow, expected llm_primary |
| env.evidence_loop | `ANALYST_EVIDENCE_LOOP_ENABLED=false` | evidence loop is disabled |
| env.provider | `AI_PROVIDER=mock` | AI_PROVIDER is not openrouter |
| env.allowlist | allowlist set to `["other/model"]` | chat and summary models not allowlisted |
| env.timeouts | `AI_REQUEST_TIMEOUT_SECONDS=45` | request timeout exceeds the analyst deadline |
| env.cutoff | `OPENROUTER_MONTHLY_CUTOFF_USD=8` | configured 8, expected 2 |
| env.shadow_rate | `ANALYSIS_SHADOW_SAMPLE_RATE=1.5` | settings unavailable because settings rejected the rate |
| env.cors | `CORS_ORIGINS=["https://evil.example"]` | PUBLIC_WEB_ORIGIN is not in CORS_ORIGINS |
| env.trusted_hosts | `TRUSTED_HOSTS=["*"]` | wildcard trusted host; api host not trusted |
| env.sentry | `SENTRY_DSN` empty | absent or not a valid HTTPS DSN |
| env.ip_hash_secret | development default | development default; shorter than 32 characters |
| env.environment | `ENVIRONMENT=development` | not a production environment |
| env.require_release | `REQUIRE_ACTIVE_RELEASE=false` | active release is not required |
| target.live | `--base-url http://127.0.0.1:9 --skip-env` | probe crashed: ConnectError |
| target.ready | `DB_URL=sqlite+aiosqlite:///:memory:` | HTTP 503, not_ready, postgres and active_release failures |
| target.cors | `CORS_ORIGINS=["https://evil.example"]` | HTTP 400, no allow-origin for the public origin |
| target.trusted_host | `TRUSTED_HOSTS=["*"]` | untrusted host returned HTTP 200 |
| ledger.present | `--ledger-key ai-budget:2099-01` | key is absent |
| ledger.month | `--ledger-key ai-budget:2099-01` | key is not the current month |
| ledger.consistent | temp key total 0.01 with a 0.05 reservation | reservations exceed the ledger total |
| ledger.capacity | temp key total 3.0, cutoff 2.0 | spend 3.0 of cutoff 2 USD |
| kill_switch | no active release (empty SQLite database) | probe crashed: OperationalError |
| provider_failure | `ANALYSIS_ANSWER_MODE=deterministic` | provider was never exercised, assertions failed |

All 25 cases met the expected `fail` status. There were no unexpected passes or missing checks.

The temporary ledger keys lived in Redis database 6, the worker's own index, and were deleted after
the case. No other worker index was read or written. The provider-failure negative case ran in
deterministic mode, made no live call, and charged nothing.
