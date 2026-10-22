# Reviewer model: gpt-6-luna vs deepseek-v4.1-flash

Status: measurement complete. Recommendation by the agreed rule: **keep `gpt-6-luna`**.
Branch `codex/llmp-w4-reviewer`, based on `536d12e` (`codex/llmp-integration`). Worktree
`~/.local/share/knicksiq/worktrees/w4-reviewer`, Redis db 1.

## Question and inputs

Which model should review analyst answers: the configured `gpt-6-luna` or the writer's
`deepseek-v4.1-flash`? Both arms used exactly the same inputs and code; only
`ANALYST_REVIEW_MODEL` changed. Provider was OpenCode Go (`. /tmp/go.env`), reviewer cap
3,000 tokens, `AI_REASONING_EFFORT=none`.

- False acceptance: `reviewer/head-units.jsonl` + `reviewer/labels.json`. 14 unmutated
  correct controls, 21 wrong-answer mutations (3 `coincident_percent` cases are now stopped
  by the deterministic gate, leaving 18 to the reviewer), 2 trials each. 64 reviewer calls
  per arm.
- Replay: the same recorded units. 14 correct + 3 wrong answers with review payloads (7
  `missed` units have no verdict and are excluded), 3 trials each, `--modes head` (the
  deployed reviewer path; base is the frozen pre-fix contract and is irrelevant to model
  choice). 51 reviewer calls per arm.

## Results

Intervals are Wilson 95%. "Wrong accepted" counts every wrong answer the pipeline accepted:
gate-passing mutations plus recorded wrong writer answers. "False rejects" and "true rejects"
are replay outcomes over correct and wrong recorded units.

| model | wrong accepted | controls accepted | false rejects | true rejects | malformed | p50 / p95 | cost/review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-luna | 7/45 (0.156) [0.077, 0.288]<br>mutated 4/36, recorded 3/9 | 25/28 (0.893) [0.728, 0.963] | 2/42 (0.048) [0.013, 0.158] | 6/9 (0.667) [0.354, 0.879] | 0/115 | 2960 / 4475 ms | $0.000310 |
| deepseek-v4.1-flash | 9/45 (0.200) [0.109, 0.338]<br>mutated 2/36, recorded 7/9 | 28/28 (1.000) [0.879, 1.000] | 0/42 (0.000) [0.000, 0.084] | 2/9 (0.222) [0.063, 0.547] | 0/115 | 2618 / 3879 ms | $0.000932 |

Machine-readable table and all per-call metadata: `decision.json`; generated Markdown:
`summary.md`.

Per-class mutation acceptance (2 trials per case):

| class | gpt-6-luna | deepseek-v4.1-flash |
| --- | --- | --- |
| number_swapped_other_metric | 0/6 | 0/6 |
| wrong_subject | 0/6 | 0/6 |
| wrong_phase_or_window | 0/6 | 0/6 |
| wins_losses_swapped | 4/6 [0.300, 0.903] | 2/6 [0.097, 0.700] |
| per_game_total_confusion | 0/6 | 0/6 |
| unsupported_causal_or_ranking | 0/6 | 0/6 |
| coincident_percent | gate-blocked (0 reachable) | gate-blocked (0 reachable) |

Deepseek's weaker recorded-wrong results are concentrated and repeatable: it accepted
`date_range_last_n-006` 3/3 and `date_range_last_n-008` 3/3, plus `exact_statistics-010` 1/3.
Luna rejected all nine of those trials. All three were labeled wrong by SQL audit notes
(wrong denominator/scope, non-answer plus unsupported ranking, player high instead of team
high). Luna's false rejects across both arms: `exact_statistics-008` (2/2 controls, 1/3 replay),
`exact_statistics-003` (1/2 controls), `date_range_last_n-004` (1/3 replay), caused by
`verdict_unsupported`, `unknown_claim_id` and `verdict_insufficient_evidence`. Deepseek
rejected no correct answer in either arm.

## Recommendation

The rule (fewest wrong acceptances, then fewest false rejects of correct answers, then
latency) selects **gpt-6-luna**: 7 versus 9 wrong acceptances out of 45 observations, which
takes priority over deepseek's better false-reject count and lower latency. Keeping luna
also preserves the owner's deliberate reviewer/writer model-family separation and is about
3x cheaper per review ($0.00031 vs $0.00093): Go prices DeepSeek 3x/2.4x higher per token,
and DeepSeek also produced about 16% more completion tokens (314 vs 270 mean).

Confidence: **low to moderate**. The total wrong-acceptance intervals overlap
([0.077, 0.288] vs [0.109, 0.338]) and the two suites point in opposite directions: the
synthetic mutation suite favors deepseek (2 vs 4 accepted), while the recorded wrong
answers favor luna (3 vs 7 accepted). The replay wrong set is only three answers. If the
rule were read as the mutation suite alone, deepseek would win; we applied it to all
measured wrong acceptances because accepting a real wrong answer is the failure the metric
exists to catch. Deepseek's perfect control acceptance is real and matters for fallback
rate, but the rule ranks it second.

## Harness defect found and fixed

The first live arm made 64 calls in 8.8 s; all returned HTTP 400 `MissingSessionID`:
OpenCode Go requires `x-opencode-session`, and the measurement harness never set it
(production sets the analyst loop's random per-conversation id). Reproduction:
`repro-missing-session-id.json` (64/64 `provider_error`). Fix in
`tools/release/analyst_review_replay.py::call_reviewer`: set a random `uuid4().hex` session
id per measurement call. `reviewer_false_acceptance.py` inherits the fix through the same
helper. No application code changed; production already sends the header.

The two tools were also extended additively to record what the decision needs:
`reviewer_max_tokens`, requested/served model, protocol, observed per-call cap, per-call
latency and cost. No validation or scoring behaviour changed.

## Cross-checks

| check | gpt-6-luna | deepseek-v4.1-flash |
| --- | --- | --- |
| `reviewer_max_tokens` (artifact) | 3000 both artifacts | 3000 both artifacts |
| observed `max_tokens` per call | 3000 on 64+51 calls | 3000 on 64+51 calls |
| served model (`last_metadata.model`) | `gpt-6-luna` 115/115 | `deepseek-v4.1-flash` 115/115 |
| protocol | `responses` 115/115 | `chat` 115/115 |
| malformed / retried | 0 / 0 | 0 / 0 |
| total arm cost | $0.0360 | $0.1074 |

Go replies carry no `provider` field, so `provider` is null in raw metadata; model and
protocol are the routing evidence. No fallback model appeared in any call.

## Commands

```bash
cd ~/.local/share/knicksiq/worktrees/w4-reviewer
. /tmp/go.env          # never printed; AI_API_KEY read from the repo .env
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

Observed wall time per arm: 200 s (false acceptance, 64 calls) and 155 s (replay, 51
calls) for luna; 176 s and 145 s for deepseek. Total Go spend across both arms: $0.1433.

## Artifacts

- `gate-proof.json` - 14 controls and 21 mutations with `review_issues`; 3 mutations are now
  gate-rejected, all controls pass.
- `false-acceptance-gpt-6-luna.json` / `.md`, `false-acceptance-deepseek-v4.1-flash.json` / `.md`
  - live mutation and control measurements with Wilson intervals and call metadata.
- `replay-gpt-6-luna.json`, `replay-deepseek-v4.1-flash.json` - live replay of correct and
  wrong recorded units, per-call metadata and rejection causes.
- `decision.json`, `summary.md` - combined table, rule and recommendation.
- `repro-missing-session-id.json` - the failing first run proving the harness defect.

## Limits

- 2 trials per mutation and 3 per replay unit; the wrong replay set has only 3 answers, so
  the true-reject comparison is the thinnest number here.
- Latency is one reviewer provider call on a shared subscription, measured in sequence, not
  end-to-end answer p95. Luna's call p95 in the false-acceptance arm (4475 ms) is above the
  4 s end-to-end target; deepseek's is 3879 ms. That matters if a review is on the critical
  path, and it did not move the decision because wrong acceptances rank first.
- Costs are computed from `AI_MODEL_PRICES` because Go reports no per-call cost.
- No held-out sets or production traffic were touched; no application behaviour was changed.
