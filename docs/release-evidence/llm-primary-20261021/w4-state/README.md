# Follow-up state, aggregation, warning and commit fixes (w4-state)

Status: VERIFIED for the four defects: every reproduction fails before its fix and passes after,
the offline suites are unchanged, and the live re-run of the affected sessions shows each
defect's symptom gone. The live session pass rate is limited by a separate repair-call cause
owned by the w4-failed branch (see the live section). Branch `codex/llmp-w4-state`, created
from `codex/llmp-integration` at `ee630be`; the code head measured live is `8ccf210` (the
report itself is the last commit). The live follow-up benchmark on `536d12e` (w4-followups)
filed the four defects; the affected sessions were re-run twice on OpenCode Go.

Environment: worktree `~/.local/share/knicksiq/worktrees/w4-state`, local restored release
`2025-26.20260928.1`, `DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq`,
`REDIS_URL=redis://localhost:56500/6` (flushed before the live run), `. /tmp/go.env`.

## Defect 1: a refusal that cites facts became the next turn's topic

A `decline` or `explain_coverage` that recited archive facts was a valid model answer, so
delivery marked it accepted (`declined=false`). `prepare` then copied its resolved scope into
`last_topic`/`last_scope`; the next elliptical turn inherited the refusal question and a
phase-only scope. `injury_decline` t3 answered 74 regular-season games instead of Brunson's
December window, and `decline_then_overall` t3 repeated that pattern. A refusal whose answer
failed validation hit the same problem through the factual fallback: `injury_decline` t1t2
delivered 74-game points and replaced the December topic.

Fix (`analyst_delivery.render`, `analyst_loop`): a refused turn is never the accepted topic,
whether it was delivered directly or as a fallback. The loop records the writer's refusal
action (`model_refused`) before validation, and `render` keeps `state["declined"]` true for
`refused or model_refused or (no claims and no evidence)`.

Repro cases 13 and 17 in `tools/release/followup_scope_repros.py`:

```
REPRODUCED refusal that cites facts overwrites the prior topic and month
  want declined=True, date_start=2025-12-02, 14 games
  got  declined=False, date_start=None, games=82
REPRODUCED refused turn's factual fallback overwrites the prior month
  want declined=True, date_start=2025-12-02, 14 games
  got  declined=False, answer='Jalen Brunson: 26.0 points per appearance across 74 observed', date_start=None, games=82
```

After: both print `NOT REPRODUCED` with `declined=True, date_start=2025-12-02, games=14`.

## Defect 2: "And per game?" after a total returned the total

`AnalystLoop.prefetch` returned early whenever any committed claim was present, so the turn
that asked for an average never ran `get_team_stats` with `aggregation=average`; the payload
carried only the December total (1,710 points), and the writer answered it. The offline audit
could not see this because it calls `prefetch_calls` directly and never exercised the guard.

Fix (`analyst_prefetch.covers_planned_shape`, `analyst_loop.prefetch`): a committed claim
stands in for the plan only when it matches the planned metric and aggregation over exactly
the turn's population. A stale total with the right games but the wrong aggregation, or the
right aggregation over a subset, now runs the lookup. The payload builder already prioritizes
new results, so the writer sees only the average claims on that turn.

Repro case 14:

```
REPRODUCED per game after a total never runs the average lookup
  want prefetched points_per_game, date_start=2025-12-02, 14 games
  got  prefetch=[], date_start=2025-12-02, games=14
```

After: `prefetch=['wins', 'losses', 'points_per_game', 'margin_per_game']`.

## Defect 3: a failed repair call was reported as a model or budget outage

Every investigation exception fell through to the same fallback warning,
`Model or budget unavailable.`, so a repair call that returned malformed structured output
(ValidationError) told the user the model or budget was down.

Fix (`analyst_loop.fallback_warning`): the warning follows the failure. A validation failure
says `Proposed wording did not pass evidence review.`; a deadline says the answer could not be
verified within the turn's time limit; anything else says it could not be verified. The
disabled-model and genuine reservation-failure paths keep the budget wording that
`docs/production-runbook.md` and `tools/release/preflight/runtime_checks.py` assert.

Repro case 15:

```
REPRODUCED a failed repair call claims the model or budget was unavailable
  want a warning that names neither model nor budget
  got  warning='Model or budget unavailable.'
```

After: `warning='Proposed wording did not pass evidence review.'`

## Defect 4: a completed turn could lose its commit

`reverse_switch_topic` t2t1 returned a validated answer with `revision=null` and
`state_committed=false`. The commit script returned 0 whenever the 35 s lease key no longer
held this turn's owner, so a turn that outlived its lease (or whose first eval lost its
reply) discarded an answer it had already produced; the route cleared the token and the next
turn started a fresh session without the December scope. Session authority also used the
fail-fast 0.2 s Redis socket timeout meant for rate limiting.

Fix (`analyst_sessions`): the lease serializes turns, not commits. Commit fails only when a
different owner holds the lease or the revision moved; an absent lease with the same read
revision commits atomically. The script is idempotent by turn digest, so a retry after a lost
reply reports the stored turn instead of failing twice, and the commit retries once on a
transient error. Session authority uses a 2 s socket timeout. When a commit still fails (a
competing turn or Redis unavailable) the route returns `state_committed=false`, no token and
`Conversation state could not be committed. Retry the same turn.`, which the web client shows
as a retry prompt; no path discards a completed answer silently.

Repro case 16 (lease deleted, equivalent to expiry, and the same commit repeated):

```
REPRODUCED an expired lease discards a completed turn and misreports a replay
  want commit=True after lease expiry, repeat commit=True
  got  commit=False, repeat=False
```

After: `commit=True, repeat=True`. The exact 36 s probe from the w4-followups report now
prints `True` after `asyncio.sleep(36)`; before the fix it printed `False`. A lease held by a
different owner still returns 0 (`test_analyst_contracts.py` covers it).

## Deterministic acceptance

```
DB_URL=... REDIS_URL=redis://localhost:56500/6 uv run --package knicksiq-api \
  python tools/release/followup_scope_repros.py
```
Before (pre-fix sources, same case list): `REPRODUCED 5 of 17` (`repro-before.txt`).
After: `REPRODUCED 0 of 17`; its exit status is nonzero when the recorded defects no longer
reproduce (`repro-after.txt`).

```
DB_URL=... uv run --package knicksiq-api python tools/release/followup_scope_audit.py \
  --out docs/release-evidence/llm-primary-20261021/w4-state/offline_scope_audit.json
```
Observed: 27/27 sessions pass, 27/27 scope clean, 64/64 turns pass, 64/64 scope clean, no
causes (`offline_scope_audit.json`).

```
for f in about_subject_repro.py first_n_followup_repro.py followup_dispatch_repro.py \
         followup_fallback_repro.py overall_followup_repro.py playin_repro.py; do
  DB_URL=... uv run --package knicksiq-api \
    python docs/release-evidence/llm-primary-20261021/correctness/$f
done
```
Observed: `FAILURES 0` from all six.

```
DB_URL=... REDIS_URL=... uv run --package knicksiq-api \
  python docs/release-evidence/llm-primary-20261021/w3-declines/reproduce_declines.py
```
Observed: `73/73 checks passed`.

Backend gate: `TEST_MODE=true uv run pytest apps packages tools/report_audit` observed
`439 passed`; `uv run ruff check apps packages migrations` all checks passed;
`uv run ruff format --check apps packages migrations` 251 files already formatted;
`uv run pyright apps packages migrations` 0 errors, 0 warnings, 0 informations.

## Live re-run on OpenCode Go

```
. /tmp/go.env; export REDIS_URL=redis://localhost:56500/6
docker exec kiq-integrate-redis-1 redis-cli -n 6 flushdb
BENCH_BASE=$(git rev-parse --short HEAD) uv run --package knicksiq-api \
  python tools/release/followup_bench.py --trials 2 \
  --session injury_decline --session decline_then_overall \
  --session team_total_average --session reverse_switch_topic \
  --out docs/release-evidence/llm-primary-20261021/w4-state/followup_sessions.json
```

Measured code head `8ccf210` (this report is the only later commit). Observed:
`{"turns": 20, "turn_passes": 12, "session_passes": 2, "session_runs": 8}`, causes
`{"pipeline:degraded": 7, "answer:value": 1}`. Provider calls: 50 (23 writer, 9 repair,
18 review) — 32 served by `deepseek-v4.1-flash` over `chat`, 18 by `gpt-6-luna` over
`responses`; 13 reviews accepted, 5 rejected. No HTTP 429 or account error. Turn stage-sum
latency: median 8.2 s, p95 13.3 s (repair/review turns included); single model call median
3.1 s, p95 6.2 s.

Per defect, on these 8 session runs:

1. **Refusal state:** every refusal was followed by the prior scope. `injury_decline` t3
   answered Brunson's December assists (7.1 over 13 observed appearances) on both trials;
   `decline_then_overall` t3 answered the all-phase 69-32 record on both trials (trial 2 as a
   correct degraded fallback). Zero scope issues on any turn; every run kept one token and
   consecutive revisions.
2. **Aggregation:** "And per game?" never returned the 1,710 total. Trial 1 delivered 122.14
   points per game from the model (validated); trial 2 delivered 122.14 through the
   deterministic fallback after a malformed repair. The prefetched average claim was in the
   payload on both.
3. **Warning:** every degraded turn reports `Proposed wording did not pass evidence review.`;
   `Model or budget unavailable.` appears on no turn.
4. **Commit:** 20/20 turns committed (`state_committed=true`, revisions 1..3 per run,
   `single_token=true`); no commit warning and no lost answer. `reverse_switch_topic` passed
   both trials, including the trial whose first turn had needed a repair.

The 8 failed turns are outside these four causes. Seven are `pipeline:degraded` after an
`analyst_execution_failed ... error_type=ValidationError stage=revise` (the malformed repair
call owned by the w4-failed branch); their delivered fallback text still carried the correct
value and scope. One is the known harness rounding false negative: `team_total_average` t1t2
answered `+5.21` against a full-precision `+5.214285714285714` claim
(`analyst_checks._same_number` with an empty raw right operand), first recorded as defect 6 in
the w4-followups report. Session marks: `injury_decline` 1/2, `reverse_switch_topic` 1/2,
`team_total_average` 0/2, `decline_then_overall` 0/2.

## Files

- `apps/api/app/services/analyst_delivery.py`: refusal never becomes the accepted topic.
- `apps/api/app/services/analyst_loop.py`: `model_refused`, cause-based fallback warning,
  prefetch guard.
- `apps/api/app/services/analyst_prefetch.py`: `covers_planned_shape`.
- `apps/api/app/services/analyst_sessions.py`: lease-tolerant idempotent commit, retry,
  session Redis timeout.
- `tools/release/followup_scope_repros.py` + `followup_repro_support.py`: cases 13-17.
- `apps/api/app/tests/*`: the frozen session commit contract follows the new behavior (a
  competing lease still blocks, an expired own lease commits, a replay reports success).

## Open risks

- The live run of the four affected sessions is 2 trials per session; per-turn model and
  reviewer stochasticity can still reject an otherwise correct turn, as in the original run.
- `covers_planned_shape` matches a committed claim's population exactly for team stats and by
  observed appearances for player stats. A claim whose game list was narrowed by another
  filter runs the lookup again; the cost is one backend query, not a provider call.
- Concurrent turns on one session are still resolved by the revision CAS: the first commit
  wins and the other client is told to retry. This is deliberate and unchanged.
