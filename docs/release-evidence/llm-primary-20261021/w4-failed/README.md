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

## Repair validation failure rate, same 21 questions

"Before" is the recorded two-trial benchmark restricted to the 21 ids
(`../w4-bench/calls.jsonl` and `trial{1,2}.responses.jsonl`); the fresh pre-fix
reproduction is one trial (`before/repair-before.json`). "After" is two fresh trials on
the fixed head (`after/repair-after.json`). A repair call is one repair request; a turn
fails when that request raises and the fallback runs.

| Run | Repair calls | ValidationErrors | Per-call rate | Turns with a schema failure |
| --- | ---: | ---: | ---: | ---: |
| Bench trial 1 (before) | 19 | 15 | 78.9% | 15/21 |
| Bench trial 2 (before) | 15 | 12 | 80.0% | 12/21 |
| Bench both (before) | 34 | 27 | 79.4% | 27/42 |
| Fresh pre-fix, 1 trial | 16 | 8 | 50.0% | 8/21 |
| After, trial 1 | 19 | 2 | 10.5% | 0/21 |
| After, trial 2 | 19 | 3 | 15.8% | 0/21 |
| After, both | 38 | 5 | 13.2% | 0/42 |

Seventeen of the 38 after repair calls carried the top-level `"type":"json_object"`
echo and were parsed after removal (`provider_format_echo` in the trace); pre-fix those
would have raised `extra_forbidden`. The five remaining first-attempt failures are the
other stochastic shapes: `{"type":"answer",...}`, `{"type":"answer_from_available_evidence",
...}`, an answer wrapped under `proposed_answer`/`answer`, and one reply containing only
`{"type":"json_object"}`. Each was retried successfully, so no after turn failed a repair.
Turn outcomes on the same 42 turns: before, 7 validated/declined, 27 schema failures,
7 review-rejected fallbacks and 1 orchestrate timeout; after, 21 validated/declined,
0 schema failures, 20 review-rejected fallbacks and the same 1 timeout. The repair fix
therefore moves turns out of the schema-failure bucket without inventing answers.

## Future-question fallback

`after/fallback-after.json` replays the same forced-failure harness. The future cases now
decline (`I can't answer questions about future games or seasons. The archive's most recent
game is 2026-06-13.`) with zero claims; the ten benign `will you`/`will I` archive requests
produce byte-identical answers to the pre-fix run (seven with facts, three with the
pre-existing generic decline). The live head run also declined `unsupported-008` through
the model path in one trial (`validated_declined`) and through the fallback in another.

## Factual audit of new head responses

Eight questions whose answers changed from schema failure to validated were re-run on the
fixed head; `after/head-responses.responses.jsonl` is that set (5 validated, 3 fallbacks)
and `after/audit/` is the full SQL audit. The audit reports 4 wrong atoms out of 62 checked;
all four are scope false positives, verified against the raw tables:

| Atom | Audit expectation | SQL |
| --- | --- | --- |
| `27` and `113.26` in `date_range_last_n-005` | full 82-game season | post-All-Star games 56-82: 27 games, 18-9, 113.26 for, 106.59 against, +6.67 |
| `75` in `comparisons-008` | 82 team games | Towns appeared in 75 regular-season games; 11.853 rebounds/appearance rounds to 11.9 |
| `15-0` in `turning_points-007` | no matching run | game 42: PHX scored 15 unanswered (68-69-72-74-77-79-80-82) from Q3 03:57 to Q4 11:39, 77-67 to 77-82 |

The remaining 32 atoms were unverified (the audit could not bind them), not wrong.
