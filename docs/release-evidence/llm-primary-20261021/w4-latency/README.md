# Wave 4 latency: where the 7.5 s / 15.0 s on OpenCode Go comes from

Branch `codex/llmp-w4-latency`. Every live number below was measured on `ee630be` +
this branch's reviewer patch; the branch was then merged with `7f1a05f` (FailedTurn's repair
echo strip/retry and FollowupState's state work) **without re-running live turns**, so the
measured SHA stays `ee630be` + the patch. Worktree
`~/.local/share/knicksiq/worktrees/w4-latency`, Redis db 8. Status: **measurement VERIFIED**;
p95 < 4 s **NOT VERIFIED** (15,272 ms); the review-output cut is **VERIFIED as a 25.8% output
reduction**, its wall-clock effect is **INCONCLUSIVE** inside host variance.

## Sample and method

The 30 questions are a deterministic round-robin of the benchmark's 10-per-category sample:
5 each from `aliases_typos` and `comparisons`, 4 each from the other five categories
(`questions.jsonl` has the ids). `latency_ab.py` imports the committed `w4-bench/bench_runner.py`
so the scorer, stage bucket, ledger and honest verdicts are the same code; it adds a UTC
timestamp per provider call and captures the exact provider payload once per schema.

Both arms ran at integration head `ee630be` + this branch's reviewer change only, on the same
30 questions x 2 trials, Redis db 8 flushed before each arm, `. /tmp/go.env`, writer
`deepseek-v4.1-flash` (chat), reviewer `gpt-6-luna` (Responses), reasoning off, 16,000-byte
input budget. Before: 15:21:32-15:30:58 UTC. After: 15:36:19-15:45:33 UTC. Both are off-peak
for Go's DeepSeek price windows (01:00-04:00 and 06:00-10:00 UTC, weekdays); the peak window
was **not sampled** (next one is 01:00 UTC).

## 1. The latency table by stage and UTC hour

Before arm (151 calls, 60 questions). Stage values are the trace's own `latency_ms`; shares are
of summed stage time. `ms/tok` is the median call latency divided by its output tokens.

| stage | calls | p50 ms | p95 ms | mean ms | share | output tokens p50 | ms/tok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| answer | 62 | 2,940 | 5,408 | 3,202.2 | 36.8% | 284 | 10.6 |
| review | 47 | 4,789 | 9,602 | 5,081.7 | 44.2% | 449 | 10.4 |
| repair | 32 | 2,437 | 4,476 | 2,682.2 | 15.9% | 237 | 9.7 |
| plan | 10 | 1,674 | 2,734 | 1,702.4 | 3.2% | 46 | 33.3 |
| tool | 49 | 65 | 155 | 102.7 | 0.9% | - | - |
| query_resolution | 60 | 58 | 78 | 58.2 | 0.6% | - | - |
| archive_records | 60 | 21 | 67 | 28.0 | 0.3% | - | - |
| session_and_release | 60 | 5 | 9 | 6.9 | 0.1% | - | - |

Hour view (only one hour was reachable in this run; the w4-bench row is the same host earlier):

| UTC hour | sample | calls | p50 ms | p95 ms | answer p50 | review p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 14:00Z (14:48-15:06) | w4-bench, 70q x2 | 354 | 7,453 | 14,958 | 2,712 | 3,880 |
| 15:00Z (15:21-15:31) | this, before | 151 | 3,162 | 6,788 | 2,940 | 4,789 |
| 15:00Z (15:36-15:45) | this, after | 147 | 3,050 | 6,519 | 2,579 | 5,088 |

The per-call p50/p95 in the hour row are over calls, not questions. No within-hour trend is
visible: the two 15:00Z arms differ by less than the trial spread, and the same-payload probe
at 15:32 and 15:46 returned the same shape (below).

## 2. Named limiter

**The independent reviewer's output generation on Go is the limiter, and every extra serial
call is the tail.** Three independent measurements say the same thing:

1. **Output tokens, not prompt bytes.** Regressing call latency on prompt and completion tokens
   over the w4-bench 354 calls gives `1,600 ms + 0.0 x prompt + 5.52 x completion` (R² 0.62;
   the prompt coefficient is not distinguishable from zero). On this sample the review stage is
   `1,941 ms + 6.54 x completion` with R² 0.95. The 30-question before arm: review 44.2% of
   stage time, answer 36.8%, repair 15.9%, plan 3.2%.
2. **The same code on OpenRouter was ~3x cheaper per call.** Regressing the recorded
   OpenRouter final (`final/budget-16000.rows.jsonl`, 384 calls, same
   `deepseek-v4.1-flash`) gives `550 ms + 1.91 x completion` (R² 0.54). Go is ~1.0 s slower
   fixed and ~2.9x slower per output token for the same model and code. Host and reviewer both
   changed between those runs; the per-stage shape (review first, answer second) did not.
3. **The reviewer emits more tokens than the writer.** Review completion p50 449 vs answer 284
   in the before arm; review completion p95 1,715 in w4-bench. Luna is also slower per output
   token than DeepSeek on the same host (review 6.5-9.1 ms vs answer 2.8-4.5 ms).

Payload size is **not** the limiter. The identical reviewer request was padded from 9,962 to
34,868 input bytes (3.5x) with the same task: p50 stayed 4.1-5.2 s and followed output tokens,
not input bytes (probe, `reviewer-size-*`). The regression's prompt coefficient is ~0.

Connection setup is **not** the limiter either. TCP+TLS handshake to `opencode.ai` measured on
8 fresh connections: median 27.9 ms TCP + 43.3 ms TLS = **71.1 ms**, about 2% of a median call.
A fixed-output ping (5-12 tokens) gave new-connection p50 1,181 ms vs keep-alive 1,216 ms for
DeepSeek (no gain) and 1,222 ms vs 998 ms for Luna (~224 ms, n=6, within spread). A pooled
httpx transport was implemented, measured, and **reverted**: the probe does not justify it.
The OpenRouter request body is unchanged (`payload-probe.json`, all nine assertions pass,
byte-identical to `w3-routing/payload-probe.json`).

The tail is call count: every extra serial call costs its fixed ~1.5-2.3 s plus output tokens.
In w4-bench, questions with 2 calls had p50 6.4 s, 3 calls 8.0 s, 4 calls 12.5 s, 5 calls 14.5 s
(p95 up to 19.9 s). Repair and plan are the avoidable calls; both are owned by other workers.

## 3. What was tried and measured

### 3a. Shorter reviewer output (landed on this branch)

`reviewer_system_prompt(span_indices=True)` asks the reviewer to name each ordered span by its
1-based number instead of echoing its words; `request_model` restores the exact span text
positionally before any deterministic check, so `review_checks`, citations and validation still
see the whole answer. The default `reviewer_system_prompt()` keeps the old wording, so the
replay/false-acceptance tools are unchanged. Measured, same 30 questions x 2 trials:

| metric | before | after | change |
| --- | ---: | ---: | ---: |
| review output tokens, mean | 488.5 | 362.4 | -25.8% |
| review output tokens, p50 | 449 | 359 | -20.0% |
| review response bytes, p50 | 1,501 | 1,118 | -25.5% |
| review latency p50 | 4,789 | 5,088 | +299 ms |
| review fixed cost (regression) | 1,941 ms | 2,315 ms | host drift |
| review ms/output token | 6.54 | 9.13 | host drift |
| end-to-end p50 / p95 | 8,032.6 / 15,809.2 | 7,828.0 / 15,272.2 | -204.6 / -537.0 ms |
| mean | 9,253.9 | 8,580.3 | -673.6 ms |
| provider calls | 151 | 147 | -4 |
| honest / 60 | 32 | 33 | +1 |
| validated / 60 | 36 | 40 | +4 |

At the before arm's 6.54 ms/token, 87 fewer output tokens is 0.57 s per review; with 44 reviews
over 60 questions that is ~0.42 s of end-to-end p50. The measured -0.20 s is smaller because
the host's review fixed cost and per-token rate rose between the arms; the paired review
latency median is +385 ms while the paired token count is -76. The token cut is real; the
wall-clock gain is inside host variance. Best measured run on the sample: **p50 7,367.0 /
p95 13,395.4 ms** (after trial 1). Trial 2 was 8,625.5 / 16,872.2; before trials were
7,703.8 / 15,809.2 and 8,032.6 / 20,171.8. p50 spread is 330 ms before and 1,258 ms after.

### 3b. Levers measured but not landed (owned by other workers)

From the w4-bench 140-question trace, subtracting the measured call times from each question
(counterfactual p50/p95 of the question wall time):

| lever | p50 | p95 | quality cost | owner |
| --- | ---: | ---: | --- | --- |
| none (measured) | 7,453 | 14,958 | - | - |
| no plan calls (all prefetched) | 7,016 | 14,727 | none observed; prefetch is deterministic | FollowupState |
| no repair (stop at first failed review) | 5,423 | 11,300 | loses 18 validated + 7 declined turns | FailedTurn |
| both | 4,700 | 10,790 | same as above | - |

Repair calls in the before arm: 32 calls (15.9% of stage time), 11 of them a
`failed:revise:ValidationError` that bought nothing. In w4-bench: 79 calls, 27 failed
ValidationErrors (34.2%). FailedTurn's repair fix targets exactly those wasted calls; the
numbers above are the ceiling for removing the stage, not a recommendation to remove it.

## 4. Owner option table (measured latency; model switching not done)

| option | role | measured per-call latency | quality | note |
| --- | --- | --- | --- | --- |
| `deepseek-v4.1-flash` writer (current) | writer | answer p50 2,940 / p95 5,408 ms | 32/60 honest on this sample; w4-bench 71/140 | keep |
| `gpt-6-luna` (current) | reviewer | review p50 4,789 / p95 9,602 ms; w4-reviewer 2,960 / 4,475 ms | wrong accept 7/45; controls 25/28; false rejects 2/42 | independent family; keep unless latency dominates |
| `deepseek-v4.1-flash` | reviewer | w4-reviewer 2,618 / 3,879 ms (109 calls); same payload 2,249-2,598 ms, 427-471 tokens | wrong accept 9/45; controls 28/28; false rejects 0/42; ~3x cost/review | loses writer/reviewer family separation |
| `deepseek-v4-flash` | reviewer | same payload 2,992-3,393 ms, 461-477 tokens (4 calls) | **not measured** | available on Go via chat; quality gate would need the reviewer suite |
| shorter review output (landed) | reviewer format | -25.8% review tokens; -0.2 s end-to-end p50 measured | honest 33/60 (+1) | no model change; replay tools keep the old prompt |

The prose answers and review verdicts are the same shape in all rows; only the reviewer's span
identity changed in the landed row. The reviewer model was not switched.

## Calls spent and artifacts

Go requests: 151 (before) + 147 (after) + 17 + 17 (two probe rounds, four model-option calls
each) + 48 ping requests (24 first attempts returned HTTP 400 for a missing "json" keyword and
were fixed; those billed no tokens) + 2 smoke calls = 382 requests, of which 358 returned 200,
over 120 analyst turns (30 x 2 before + 30 x 2 after). No 429 and no account error; no call was
retried in a loop.

- `before/`, `after/` - `metrics.json`, `trial{1,2}.json`, `.scored.jsonl`, `.responses.jsonl`,
  `calls.jsonl` (with `started_utc`), `ledger.jsonl`, `questions.jsonl`, `payloads.json`
- `probe.jsonl` (15:32-15:33Z), `probe-1600.jsonl` (15:45-15:46Z) - identical-payload transport,
  session and input-size probe; `ping.jsonl` - fixed-output transport probe
- `summary.json` - machine-readable tables; `analyze.py`, `latency_ab.py`, `probe.py`, `ping.py`
- `payload-probe.json` - OpenRouter body unchanged

Reproduce:

```sh
. /tmp/go.env && export REDIS_URL=redis://localhost:56500/8
docker exec kiq-integrate-redis-1 redis-cli -n 8 flushdb
uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/w4-latency/latency_ab.py --out-dir .../before
uv run --package knicksiq-api python docs/release-evidence/llm-primary-20261021/w4-latency/analyze.py
```

## Verification

`env -i HOME=$HOME PATH=$PATH TEST_MODE=true uv run pytest apps packages tools/report_audit -q`
-> **439 passed** in 36.44 s. `ruff check apps packages tools/report_audit` -> passed;
`ruff format --check` -> 254 files already formatted; `pyright
apps/api/app/services/analyst_provider.py` -> 0 errors. `w3-routing/payload_probe.py` -> all
nine assertions pass and `payload-probe.json` is byte-identical to the committed one (run with
`AI_CHAT_MODEL` unset, because `/tmp/go.env` overrides that one probe case).

## Open risks

- Peak-window latency is unsampled: every Go number here is off-peak. Go's own pricing calls
  01:00-04:00 and 06:00-10:00 UTC peak; if that window throttles decode, the 7.5 s p50 may be a
  floor, not a ceiling.
- The after-arm wall-clock gain is inside the 1.3 s trial spread and a host fixed-cost drift;
  the token reduction is the defensible result. A second after pair at a quieter hour would
  settle it.
- `deepseek-v4-flash` as reviewer is latency-only; no quality arm was run.
- The review-output change alters the reviewer's output contract. ReviewerSwap's measured
  quality/latency table used the old echoed-text prompt and should be marked stale or rerun.
- The branch now contains FailedTurn's repair fix and FollowupState's state change, merged after
  the live arms; the measured after is `ee630be` + the reviewer patch only. Their effect (the 3b
  counterfactual) is not in the measured after and would need a fresh 30 x 2 to quantify.
