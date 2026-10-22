# w4-failed: repair ValidationError and future-question fallback

Branch `codex/llmp-w4-failed`, Redis db 7, OpenCode Go production config. Two defects from
the w4-bench measurement (`../w4-bench/README.md`, 140 live turns):

1. 27/140 turns raised `failed:revise:ValidationError` and fell back.
2. `unsupported-008` ("How will Brunson play next season?") delivered Brunson's
   current-season average after the model path failed instead of declining.

## Reproduction (before the fixes)

Run against the local restore and Go config, with a disposable Redis db:

```sh
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/7
docker exec kiq-integrate-redis-1 redis-cli -n 7 flushdb
uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w4-failed/repro_repair.py \
  --trials 1 --out /tmp/w4-failed-before.json --raw-dir /tmp/w4-failed-raw
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
REDIS_URL=redis://localhost:56500/7 \
  uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w4-failed/fallback_future_repro.py \
  --out /tmp/fallback-before.json
```

`repro_repair.py` runs the 21 question ids that failed a repair in trial 1 or trial 2 of
the benchmark. It records each provider reply in `--raw-dir` only (never in the repo;
prompts are not committed) and writes a committed summary with the pydantic error, the
reply length, finish reason and completion tokens. Pre-fix output:
`before/repair-before.json` (16 repair calls, 8 ValidationErrors) and
`before/repair-failures.jsonl` (the 8 raw replies, classified).

`fallback_future_repro.py` makes every provider call raise, so each turn ends in the
factual fallback. Pre-fix output: `before/fallback-before.json`; `unsupported-008`
returns `Jalen Brunson: 26.0 points per appearance...` (one claim) instead of declining.

## Cause table, 8 captured pre-fix ValidationErrors

| Cause | Count | Evidence |
| --- | ---: | --- |
| Top-level `"type":"json_object"` echo: `extra_forbidden` | 7 | reply starts `{"type":"json_object","text":...}`; removing that one key makes all 7 parse |
| `follow_up_questions` had a garbage third entry (`"]}}"`); max 2 | 1 | same question later returned a clean two-item reply |
| Truncated JSON (`finish_reason=length`) | 0 | all 8 `finish_reason=stop`, completion tokens 93-538 of 1600 |
| `displayed_value` object drift | 0 | objects are allowed and equal the claim value; all 7 echo replies parse after key removal |
| Input budget / repair payload over limit | 0 | no `ValueError` in the run; the same payload succeeded later |

The echo is the host's JSON-mode artifact: Go rejects `json_schema` for this model
(HTTP 400 "This response_format type is unavailable now"), so the writer runs with
`response_format={"type":"json_object"}`. It occasionally copies that object's `type` key
into the answer. The artifact is not tied to a field or a question: the same question
(`unsupported-008`) produced the echo in one run and a clean reply in later runs, and
`comparisons-002` produced the echo in two separate runs. Temperature is 0, so the host
is not deterministic here. The one garbage-tail failure is also stochastic.

## Fixes

- `analyst_provider.without_json_mode_echo` removes exactly the top-level
  `"type":"json_object"` key before validation and records it as
  `provider_format_echo` in the call trace. No other unknown key is tolerated.
- `AnalystLoop.repair` retries a repair reply that is still off-schema once, when two
  calls remain free for the retry and its review; then the turn falls back with
  "Repair output did not pass schema validation." This is the residual layer for the
  stochastic garbage tail (1/8 captured failures), not the echo.
- `analyst_fallback` classifies future/prediction scopes as family `future`, returns no
  facts for them, and declines with the archive's last game date. `"will you"`/`"will I"`
  requests are not future scopes, so the benign archive corpus keeps its facts.
  `render_fallback` marks those turns refused and skips the recovery lookup.

## After the fixes

See `after/` and the table in the final report. (Updated after the live measurement.)
