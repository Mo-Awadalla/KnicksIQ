# w4-docs: OpenCode Go documentation and preflight pass

Branch `codex/llm-w4-docs` from `codex/llmp-integration` at `536d12e`. No live model call was made:
the preflight's kill-switch probe is deterministic and its provider-failure probe injects an
adapter exception.

| File | What it is |
| --- | --- |
| `consistency-go.json` | `check_launch_mode_consistency.py` output: status `pass`, no mismatches. |
| `run-preflight-go.sh` | Repeatable in-process preflight with the Go configuration. |
| `../ops/preflight-go.json` | The recorded run: 25/25 checks pass, exit 0. |

## Commands and observed results

```sh
python3 tools/release/check_launch_mode_consistency.py \
  --json-out docs/release-evidence/llm-primary-20261021/w4-docs/consistency-go.json
# status: pass, mismatches: []

docker exec kiq-integrate-redis-1 redis-cli -n 5 flushdb
docker exec kiq-integrate-redis-1 redis-cli -n 5 set ai-budget:2026-10 0.07 NX
sh docs/release-evidence/llm-primary-20261021/w4-docs/run-preflight-go.sh
# exit 0, 25 pass / 0 fail / 0 skip
```

`render.yaml` and the release-checklist launch section agree on `ANALYSIS_ANSWER_MODE=llm_primary`,
`ANALYST_EVIDENCE_LOOP_ENABLED=true`, `ANALYSIS_SHADOW_SAMPLE_RATE=0.1`,
`OPENROUTER_MONTHLY_CUTOFF_USD=2`, `AI_PROVIDER=opencode-go`,
`AI_CHAT_MODEL=deepseek-v4.1-flash` and `ANALYST_REVIEW_MODEL=gpt-6-luna`.

The preflight needed the local restored release `2025-26.20260928.1` (active, validation passed)
and Redis database 5. `env.provider` recorded provider `opencode-go`, host `opencode.ai`, chat
model `deepseek-v4.1-flash`; `env.allowlist` recorded `deepseek-v4.1-flash` and `gpt-6-luna`, so
the review model resolved to the Go reviewer and not the writer. The ledger moved from $0.07 to
$0.09: two settled failed-call reservations from the provider-failure probe, with no provider
request. `secrets_printed` is false. Qdrant was disabled; the Sentry DSN and the IP hash secret
were the format-valid placeholders ReleaseOps used, so those checks prove presence and shape only.

## Documentation changes

- `README.md`, `docs/architecture.md`, `docs/render-deploy.md`, `docs/production-runbook.md`,
  `docs/analyst-evidence-loop.md`, `docs/release-checklist.md` and `docs/api.md` now name OpenCode
  Go as the model host: writer `deepseek-v4.1-flash` over Chat Completions, reviewer `gpt-6-luna`
  over the Responses API, `ANALYST_REVIEW_MODEL`, `AI_MODEL_PROTOCOLS`, `AI_MODEL_PRICES` and why
  (Go reports no per-call cost), and the per-turn `x-opencode-session` header.
- The terms risk is quoted from `opencode-go/README.md` in `docs/architecture.md`; the suspended
  account behaviour and the exact switch back to OpenRouter are in `docs/production-runbook.md`.
- Every latency and cost figure in the docs is marked as measured on OpenRouter.
- `docs/release-evidence/llm-primary-20261021/README.md` gained an `opencode-go` row and the `w4-*`
  placeholder sentence.

## Checks that still assumed OpenRouter

`tools/release/preflight/` already accepted `opencode-go` (`KNOWN_PROVIDERS`, and the allowlist
check covers the review model), so no check changed. Two stale labels were fixed: the
`env.provider` description in `tools/release/preflight_llm_primary.py` said the provider must be
OpenRouter, and `tools/release/measure_llm_latency.py` / `measure_llm_capacity.py` wrote "real
OpenRouter provider" into the `meta.scope` of any run. Both now follow the configured
`AI_PROVIDER`.

## Open items

- Go latency and capacity are unmeasured; the docs say so.
- `OPENROUTER_`-prefixed setting names remain; they apply to any host.
- The Go terms risk is owner-accepted, not eliminated.
