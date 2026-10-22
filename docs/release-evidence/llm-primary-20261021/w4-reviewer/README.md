# Reviewer model: gpt-6-luna vs deepseek-v4.1-flash

Status: measurement complete on integration head `cacf474`. Recommendation by the agreed
rule: **keep `gpt-6-luna`**. Branch `codex/llmp-w4-reviewer`, fast-forwarded to `cacf474`
after the first run measured `536d12e`; the re-measure commit sits on top. Worktree
`~/.local/share/knicksiq/worktrees/w4-reviewer`, Redis db 1.

## Question and inputs

Which model should review analyst answers: the configured `gpt-6-luna` or the writer's
`deepseek-v4.1-flash`? Both arms used exactly the same inputs and code; only
`ANALYST_REVIEW_MODEL` changed. Provider was OpenCode Go (`. /tmp/go.env`), reviewer cap
3,000 tokens, `AI_REASONING_EFFORT=none`.

- False acceptance: `reviewer/head-units.jsonl` + `reviewer/labels.json`. 14 unmutated
  correct controls and 21 wrong-answer mutations, 2 trials each. On `cacf474` the
  deterministic gate rejects 6 mutations before the reviewer (3 `wins_losses_swapped`, 3
  `coincident_percent`), leaving 15 cases / 30 observations. 58 reviewer calls per arm.
- Replay: the same recorded units. 14 correct + 3 wrong answers with review payloads (7
  `missed` units have no verdict and are excluded), 3 trials each, `--modes head` (the
  deployed reviewer path; base is the frozen pre-fix contract and is irrelevant to model
  choice). 51 reviewer calls per arm.

The first run on `536d12e` found luna accepting 4/6 reversed record mutations. That result
caused the gate fix in `cacf474`; those cases now never reach the reviewer, so this page
reports fresh numbers from the fixed head. The earlier artifacts remain in git history.

## Results

Intervals are Wilson 95%. "Wrong accepted" counts every wrong answer the pipeline accepted:
gate-passing mutations plus recorded wrong writer answers. "False rejects" and "true rejects"
are replay outcomes over correct and wrong recorded units.

| model | wrong accepted | controls accepted | false rejects | true rejects | malformed | p50 / p95 | cost/review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-luna | 3/39 (0.077) [0.026, 0.203]<br>mutated 0/30, recorded 3/9 | 26/28 (0.929) [0.773, 0.980] | 4/42 (0.095) [0.038, 0.221] | 6/9 (0.667) [0.354, 0.879] | 0/109 | 2829 / 4898 ms | $0.000310 |
| deepseek-v4.1-flash | 7/39 (0.179) [0.090, 0.327]<br>mutated 0/30, recorded 7/9 | 28/28 (1.000) [0.879, 1.000] | 0/42 (0.000) [0.000, 0.084] | 2/9 (0.222) [0.063, 0.547] | 0/109 | 2556 / 4750 ms | $0.000924 |

Machine-readable table and all per-call metadata: `decision.json`; generated Markdown:
`summary.md`.

Per-class mutation acceptance (2 trials per case):

| class | gpt-6-luna | deepseek-v4.1-flash |
| --- | --- | --- |
| number_swapped_other_metric | 0/6 | 0/6 |
| wrong_subject | 0/6 | 0/6 |
| wrong_phase_or_window | 0/6 | 0/6 |
| wins_losses_swapped | gate-blocked (0 reachable) | gate-blocked (0 reachable) |
| per_game_total_confusion | 0/6 | 0/6 |
| unsupported_causal_or_ranking | 0/6 | 0/6 |
| coincident_percent | gate-blocked (0 reachable) | gate-blocked (0 reachable) |

Both models now reject every mutation that reaches the reviewer, so the decision turns on
recorded wrong answers. Deepseek accepted `date_range_last_n-006` 3/3,
`date_range_last_n-008` 2/3 and `exact_statistics-010` 2/3 (7/9). Luna rejected all nine of
those trials. The labels are SQL-audited: wrong denominator/scope, a non-answer plus
unsupported ranking, and a player high instead of the team high. Luna's false rejects are
`exact_statistics-008` (2/2 controls, 2/3 replay), `exact_statistics-003` (1/3 replay),
`date_range_last_n-003` (1/3 replay), caused by `verdict_unsupported`,
`unknown_claim_id`, `verdict_insufficient_evidence` and `missing_ids`. Deepseek rejected no
correct answer in either arm.

## Recommendation

The rule (fewest wrong acceptances, then fewest false rejects of correct answers, then
latency) selects **gpt-6-luna**: 3 versus 7 wrong acceptances out of 39 observations, which
takes priority over deepseek's better false-reject count and lower latency. Keeping luna
also preserves the owner's deliberate reviewer/writer model-family separation and is about
3x cheaper per review ($0.00031 vs $0.00092): Go prices DeepSeek 3x/2.4x higher per token,
and DeepSeek also used more review tokens.

Confidence: **moderate**. With the gate fix both models reject all 30 reachable mutation
observations, so the rule's first criterion rests on the 3 recorded wrong units (9 trials
each). The total intervals still overlap at the margin ([0.026, 0.203] vs [0.090, 0.327]),
and luna's false rejects moved from 2/42 in the `536d12e` run to 4/42 here, so the
false-reject gap is real in direction but not tight. Deepseek's perfect control acceptance
is a genuine advantage for fallback rate, but the rule ranks wrong acceptances first.

## Harness defect found and fixed

The first live arm on `536d12e` made 64 calls in 8.8 s; all returned HTTP 400
`MissingSessionID` because no `x-opencode-session` header was sent. Reproduction:
`repro-missing-session-id.json` (64/64 `provider_error`). Integration fixed it at the
adapter (`b000e5a`: every adapter starts with a random id) and the replay harness now relies
on that; the temporary duplicate assignment in `analyst_review_replay.py` was removed at the
merge. The failed run is never scored. No application code is changed by this branch.

The two measurement tools were extended additively to record `reviewer_max_tokens`,
requested/served model, protocol, observed per-call cap, per-call latency and cost in their
artifacts. No validation or scoring behaviour changed.

## Cross-checks

| check | gpt-6-luna | deepseek-v4.1-flash |
| --- | --- | --- |
| `reviewer_max_tokens` (artifact) | 3000 both artifacts | 3000 both artifacts |
| observed `max_tokens` per call | 3000 on 58+51 calls | 3000 on 58+51 calls |
| served model (`last_metadata.model`) | `gpt-6-luna` 109/109 | `deepseek-v4.1-flash` 109/109 |
| protocol | `responses` 109/109 | `chat` 109/109 |
| malformed / retried | 0 / 0 | 0 / 0 |
| total arm cost | $0.0338 | $0.1017 |

Go replies carry no `provider` field, so `provider` is null in raw metadata; model and
protocol are the routing evidence. No fallback model appeared in any call.

## Commands

```bash
cd ~/.local/share/knicksiq/worktrees/w4-reviewer
git merge --ff-only cacf474        # first run was 536d12e
. /tmp/go.env                      # never printed; AI_API_KEY read from the repo .env
export REDIS_URL=redis://localhost:56500/1
export PUBLIC_CHAT_RATE_LIMIT_PER_MINUTE=100000 PUBLIC_CHAT_RATE_LIMIT_PER_DAY=100000
docker exec kiq-integrate-redis-1 redis-cli -n 1 flushdb

# offline gate proof (no calls)
uv run --package knicksiq-api python tools/release/reviewer_false_acceptance.py \
  --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
  --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
  --gate-only --out .../w4-reviewer/gate-proof.json

# per arm: ANALYST_REVIEW_MODEL from go.env (gpt-6-luna) or overridden to deepseek-v4.1-flash
uv run --package knicksiq-api python tools/release/reviewer_false_acceptance.py \
  --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
  --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
  --trials 2 --out .../w4-reviewer/false-acceptance-<model>.json \
  --markdown .../w4-reviewer/false-acceptance-<model>.md

uv run --package knicksiq-api python tools/release/analyst_review_replay.py \
  --records docs/release-evidence/llm-primary-20261021/reviewer/head-units.jsonl \
  --labels docs/release-evidence/llm-primary-20261021/reviewer/labels.json \
  --trials 3 --modes head --out .../w4-reviewer/replay-<model>.json

uv run --package knicksiq-api python tools/release/reviewer_model_decision.py \
  --arm gpt-6-luna:.../false-acceptance-gpt-6-luna.json:.../replay-gpt-6-luna.json \
  --arm deepseek-v4.1-flash:.../false-acceptance-deepseek-v4.1-flash.json:.../replay-deepseek-v4.1-flash.json \
  --out .../w4-reviewer/decision.json --markdown .../w4-reviewer/summary.md
```

Observed wall time per arm on `cacf474`: 181 s (false acceptance, 58 calls) and 157 s
(replay, 51 calls) for luna; 161 s and 155 s for deepseek. Total Go spend for the current
head: $0.1355 (the superseded `536d12e` run cost $0.1433). No HTTP 429 or account errors.

## Artifacts

- `gate-proof.json` - 14 controls and 21 mutations with `review_issues` on `cacf474`; 6
  mutations are gate-rejected, all controls pass.
- `false-acceptance-gpt-6-luna.json` / `.md`, `false-acceptance-deepseek-v4.1-flash.json` / `.md`
  - live mutation and control measurements with Wilson intervals and call metadata.
- `replay-gpt-6-luna.json`, `replay-deepseek-v4.1-flash.json` - live replay of correct and
  wrong recorded units, per-call metadata and rejection causes.
- `decision.json`, `summary.md` - combined table, rule and recommendation.
- `repro-missing-session-id.json` - the failing `536d12e` run proving the harness defect.

## Limits

- 2 trials per mutation and 3 per replay unit; the wrong replay set has only 3 answers, so
  the true-reject comparison is the thinnest number here.
- Latency is one reviewer provider call on a shared subscription, measured in sequence, not
  end-to-end answer p95. Both models' call p95 in the false-acceptance arm is near or above
  the 4 s end-to-end target (luna 4898 ms, deepseek 4750 ms); that matters if a review sits
  on the critical path, and it did not move the decision because wrong acceptances rank
  first.
- Costs are computed from `AI_MODEL_PRICES` because Go reports no per-call cost.
- No held-out sets or production traffic were touched; no application behaviour was changed.
