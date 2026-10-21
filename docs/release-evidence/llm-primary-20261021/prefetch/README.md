# Prefetch contract fixes, 2026-10-21

Branch `codex/llmp-prefetch`, merged from `codex/llmp-integration` at `a5b09fb`; the later
integration merge `304895a` changed no prefetch, payload, delivery or analyst test file.
Scope: the 12 failing contracts after the quarters merge, plus a live check that
prefetch still runs and its claims respect the input budget.

## Failures after merging `a5b09fb`: classification and fix

| Test | Observed | Class | Fix |
| --- | --- | --- | --- |
| `test_analyst_loop_contracts.py::test_bounded_loop_and_revalidated_explanation` | `calls 2 == 3` | (a) incidental count; prefetch removed the planning call | Bound restated to `calls <= 3`, `rounds <= 1`, `tool_count == 1`; follow-up stays `calls <= 2`, `rounds == 0` |
| `test_analyst_loop_contracts.py::test_ten_short_prior_messages_still_reach_writer` | fallback `Model or budget unavailable`, `TimeoutError stage=orchestrate` | (b) real contract: prior context reached the writer but prefetch's 18-byte hint crowded every claim out of the payload, so the model re-planned and hit the tool-round limit | Payload drops `preplanned_tools` before dropping claims; measured below |
| `test_analyst_loop_contracts.py::test_intermittent_bad_action_is_retried[3 params]` | `calls 3 == 4` | (a) incidental count; retry still happens (answer validated) | Bound restated to `calls <= 4` (bad action, one retry, answer, review) |
| `test_analyst_loop_contracts.py::test_repair_is_rechecked_and_never_investigates[1.0, 20.0]` | `calls 4 == 5` | (a) incidental count; repair and recheck still run | Bound restated to `calls <= 5`, `rounds <= 1`, `tool_count == 1`; tail schema order kept |
| `test_analyst_route_contracts.py::test_route_commits_replays_and_ignores_client_authority` | `prompts 2 == 3` | (a) incidental count; replay identity unchanged | First turn `<= 3`; replay does not add a call; second turn adds at least one and total `<= 5` |
| `test_analyst_shadow.py::test_evidence_loop_shadow_http[3 params]` | answer was a game log (`Brunson 30 points ... BOS`) or the discovery message, never the average `25` | (b) prefetch selected `discover_facts` for a single-player average with no metric word; the scripted model picks `get_player_stats`, and only that claim matches the deterministic population filter | Prefetch now selects `get_player_stats` with `metric or "points"` for single-player averages |
| `test_analyst_refusal.py::test_decline_with_partial_facts_is_refused` | `citations == []` | (b) the loop already held a `discover_facts` result; prefetch ran the same tool again and the overlapping claim/candidate groups could not fit, so no claims reached the model | Prefetch skips when `self.results` or committed `tools.claims` already exist |
| `test_analyst_loop_contracts.py::test_provider_schema_growth_uses_factual_fallback` | passed after the quarters merge | n/a | Lead changed the canary; json_object remains the protected production format |

Two code gaps surfaced while fixing the above and are part of this branch:

- Prefetched tools bypassed `tool_count`, so they did not count toward the six-tool limit.
  They now increment it.
- `build_payload` silently dropped all claims when the prompt hint alone crossed the
  limit. It now retries claim selection without `preplanned_tools`.

## Measured payload sizes for the ten-message contract

Same fixtures as the test: 10 short prior messages, 9-tool registry, `analyst_input_tokens=8000`.

| Shape | System bytes | Payload bytes | Sum | Claims retained |
| --- | ---: | ---: | ---: | ---: |
| Base second action (no prefetch), 8-tool-era prompt | 2,461 | 5,526 | 7,987 | 1 |
| Prefetch with hint, 9-tool prompt | 2,297 | 5,544 (would fit) | 8,025 | 0 (dropped) |
| Prefetch with hint dropped, 9-tool prompt | 2,297 | 5,687 | 7,984 | 1 |
| Reviewer after the fix | 1,957 | 4,300 | 6,257 | 1 |

At the failing point the hint was 18 bytes and the payload limit was `8000 - 2297 = 5703`.
The claim group needed 5,544, which was over by 21 bytes with the hint. Dropping the hint
fits it with 16 bytes to spare. The cap itself was not changed; the lead is sizing it.

## Prefetch scope audit

Offline over all 110 non-follow-up questions in `questions.jsonl`, against the restored
release and without provider calls: 60 questions prefetch, split 35 `discover_facts`,
19 `get_team_stats`, 6 `get_player_stats`. No prefetch ran a player tool without a
resolved player, and every team aggregate was the implicit Knicks scope or an explicitly
resolved window. Prefetch cannot widen scope: it passes only a question and aggregation,
while `AnalystTools.execute` applies the backend `ResolvedQuery`.

## Live smoke, 10 questions, 2026-10-21

Settings: real provider, `AI_REASONING_EFFORT=none`, `ANALYSIS_ANSWER_MODE=llm_primary`,
`TEST_MODE=false`, Redis db 3, `OPENROUTER_MONTHLY_CUTOFF_USD=2`.
Sampling: `--per-category 2 --limit 10` (5 hard categories, 2 each).

| Question | Prefetch ran | Validated | Outcome |
| --- | --- | --- | --- |
| exact_statistics-001 | yes | yes | validated |
| exact_statistics-002 | yes | no | fallback:review_rejected |
| date_range_last_n-001 | yes | yes | validated |
| date_range_last_n-002 | yes | no | fallback:review_rejected |
| comparisons-001 | no | yes | validated_declined |
| comparisons-002 | no | no | fallback:review_rejected |
| single_game_narrative-001 | yes | no | failed:review:ValueError |
| single_game_narrative-002 | no | yes | validated (clarification) |
| turning_points-001 | yes | no | fallback:review_rejected |
| turning_points-002 | no | no | fallback:review_rejected |

Prefetch ran on 6/10 turns; 4/10 answers passed the independent reviewer. Ten live
questions were spent here.

Control: the same two turns with `ANALYST_PREFETCH_ENABLED=false`:

| Question | Prefetch off | Prefetch on |
| --- | --- | --- |
| single_game_narrative-001 | validated | fallback: review ValueError after the repair payload overflowed |
| exact_statistics-002 | validated (declined wording) | fallback:review_rejected |

The repair overflow is the same 8,000-byte issue measured above: prefetch leaves two tool
results in `results`, and the repair payload then exceeds the cap. This is reported for
the cap sizing instead of raising the constant here. The prefetch-on run of
`single_game_narrative-001` also shows a stochastic mismatch: the model planned
`get_game_flow`, while prefetch had chosen `discover_facts`. The rule claimed no wrong-tool
matches on the latency 40-question run; this turn is a counterexample on a new run.

## Commands

- `TEST_MODE=true uv run pytest apps packages tools/report_audit`
- `uv run ruff check apps packages migrations`
- `uv run ruff format --check apps packages migrations`
- `uv run pyright apps packages migrations`
- `uv run --package knicksiq-api python /tmp/run_smoke.py` (dotenv wrapper; the repo
  `.env` is not shell sourceable because of the user-agent line)
- `uv run --package knicksiq-api python /tmp/run_control.py`

## Artifacts

- `smoke10.json`, `smoke10.scored.jsonl`, `smoke10.responses.jsonl`
- `prefetch-off-control.json`, `.scored.jsonl`, `.responses.jsonl`
