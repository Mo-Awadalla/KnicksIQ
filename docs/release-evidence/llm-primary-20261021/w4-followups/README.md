# Live multi-turn follow-up benchmark (w4-followups)

Status: VERIFIED. The two live trials ran to completion on OpenCode Go. Measured base
`536d12e` on `codex/llmp-integration`; branch `codex/llmp-w4-followups`, evidence commit
`9e95686` (later commits touch only this report). Integration HEAD
(`cacf474`) was not merged during measurement: `b000e5a` only changes non-analyst adapters
(the analyst loop already sent `x-opencode-session`, and no MissingSessionID row appears),
and `cacf474` adds a record-order gate. No delivered answer in this run stated a reversed
W-L record, so neither change would alter a row.

Offline baseline re-run on the same base: 27/27 sessions, 64/64 turns, 64/64 scope clean
(`offline_scope_audit.json`). Every live failure below therefore comes from the live path
(model, review or session state) or from the benchmark's own scoring, not from offline scope.

## Headline (27 sessions, 64 turns, 2 trials = 128 turns)

| Metric | Trial 1 | Trial 2 | Both |
| --- | --- | --- | --- |
| Turns pass | 46/64 (71.9%) | 44/64 (68.8%) | 90/128 (70.3%) |
| Session runs pass | 13/27 | 11/27 | 24/54 (44.4%) |
| Model path (`llm_validated=true`) | 53/64 | 53/64 | 106/128 (82.8%) |
| Fallback (`llm_validated=false`) | 11/64 | 11/64 | 22/128 (17.2%) |
| Degraded responses | 11/64 | 12/64 | 23/128 (18.0%) |
| Scope-clean session runs | 26/27 | 25/27 | 51/54 |

Session spread: 9 sessions pass both trials, 6 pass exactly one, 12 pass neither. The
23 degraded turns are the 22 fallbacks plus one turn whose LLM answer was correct but whose
state commit failed.

Model path by turn position: turn 1 45/54, turn 2 44/54, turn 3 17/20. Fallback is evenly
spread across the conversation, not a first-turn effect.

A session passes only when every turn is `ok` and session integrity holds (one token,
consecutive revisions, every 200 settled). A turn is `ok` only when the honest scorer, the
oracle's expected value and the committed scope all pass. The harness labels every fallback
`pipeline:degraded`, even when the fallback text is correct: 19 of the 23 degraded turns did
deliver the expected value or decline. Only 4 fallback turns were also wrong.

## Per-session results

`.` pass, `F` fail, one mark per trial. `turns` and `model` are per trial; `scope` means every
turn's committed scope matched on both trials (injury_decline and reverse_switch_topic each
lost it on one trial).

| Session | Category | Marks | Pass | Turns t1/t2 | Model t1/t2 | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| phase_regular_overall_playoffs | phase_change | .F | 1/2 | 3/3, 2/3 | 3/3, 2/3 | yes |
| record_home_road | home_road | .. | 2/2 | 3/3, 3/3 | 3/3, 3/3 | yes |
| phase_all_then_regular | phase_change | .F | 1/2 | 2/2, 1/2 | 2/2, 2/2 | yes |
| phase_playoffs_then_overall | phase_change | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| including_playoffs | phase_change | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| home_phase_change | phase_change | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| team_ppg_home_away_playoffs | home_road | FF | 0/2 | 2/2, 2/2 | 3/3, 3/3 | yes |
| opponent_switch_record | opponent_switch | F. | 1/2 | 1/2, 2/2 | 1/2, 2/2 | yes |
| opponent_phase_switch | phase_change | FF | 0/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| opponent_home_road | opponent_switch | FF | 0/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| player_switch | player_switch | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| player_pronoun_metric | pronoun | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| player_phase_change | phase_change | .F | 1/2 | 2/2, 1/2 | 2/2, 1/2 | yes |
| player_month_switch | window_change | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| player_last5_to_month | window_change | .. | 2/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| team_total_average | aggregation | FF | 0/2 | 1/2, 0/2 | 2/2, 1/2 | yes |
| game_reference_chain | game_reference | F. | 1/2 | 2/3, 3/3 | 2/3, 3/3 | yes |
| game_why | explanation | FF | 0/2 | 1/2, 1/2 | 2/2, 2/2 | yes |
| betting_decline | decline | FF | 0/2 | 2/2, 2/2 | 2/2, 2/2 | yes |
| injury_decline | decline | FF | 0/2 | 0/3, 2/3 | 1/3, 2/3 | no |
| phase_after_player | topic_retention | .. | 2/2 | 3/3, 3/3 | 3/3, 3/3 | yes |
| topic_overall_after_player | topic_retention | FF | 0/2 | 1/2, 0/2 | 1/2, 0/2 | yes |
| team_month_switch | window_change | FF | 0/2 | 0/2, 0/2 | 1/2, 2/2 | yes |
| team_margin | metric_change | FF | 0/2 | 0/2, 1/2 | 1/2, 2/2 | yes |
| opponent_switch_team_stats | opponent_switch | FF | 0/2 | 1/2, 1/2 | 2/2, 2/2 | yes |
| reverse_switch_topic | player_switch | .F | 1/2 | 2/2, 0/2 | 2/2, 1/2 | no |
| decline_then_overall | decline | FF | 0/2 | 2/2, 2/2 | 2/2, 2/2 | yes |

## Failing turns by class (38 total)

Full per-turn detail (question, stages, warnings, failures, scope issues, answer) is in
`failing_turns.txt`. Classes are mutually exclusive root causes.

| Class | Turns | What happened |
| --- | --- | --- |
| Reviewer rejection | 10 | A review ran (`review` stage), rejected the proposal, and the turn fell back. |
| Fallback: validation or budget | 10 | No review stage: deterministic evidence checks or the repair call failed; fallback. |
| State after refusal | 3 | A refusal/fallback answer that cited facts became the new last topic; the next follow-up lost the prior scope/topic. |
| Model wording | 4 | Delivered model answers: one missed aggregation change, two declined an answerable turn, one stated an uncited date. |
| Commit failure | 1 | Correct LLM answer, but the session commit returned false; token/revision were cleared. |
| Benchmark scoring artifact | 10 | Correct answers scored wrong by the harness: 9 rounded numbers, 1 sentence-final W-L record. |

Reviewer rejection turns: opponent_phase_switch t1t1; player_phase_change t2t2;
game_reference_chain t1t3; betting_decline t1t2 and t2t2; injury_decline t1t1 and t1t2;
topic_overall_after_player t1t2; reverse_switch_topic t2t2; decline_then_overall t1t2.
Six fell back with `Model or budget unavailable.` after the repair call raised, four with
`Proposed wording did not pass evidence review.`.

Fallback validation/budget turns: phase_regular_overall_playoffs t2t2; opponent_switch_record
t1t1; opponent_phase_switch t2t1; opponent_home_road t1t1 and t2t1; team_total_average t2t2;
topic_overall_after_player t2t1 and t2t2; team_month_switch t1t1; team_margin t1t1.

State-after-refusal turns: injury_decline t1t3 and t2t3; decline_then_overall t2t3. This is
the only class that produced a wrong context on the following turn: injury_decline t3 expected
Brunson's December assists (7.1 over 14 games) and answered 6.8 assists over 74 regular-season
games because the December window was gone. Trial 2's t2 was a **correct** refusal
(`refused=true`) that also recited his December points; trial 1's t2 was a claim-less fallback.
Both lost the scope. `decline_then_overall` shows the A/B in one session: trial 1 t2 was a
claim-less fallback and t3 passed; trial 2 t2 was a model refusal that recited the 53-29 record
and t3 fell back with "verified archive facts are unavailable".

Model wording turns: team_total_average t1t2 (asked "And per game?", answered 1,710 total
points, not 122.14); game_why t1t2 and t2t2 (declined while quoting the 115-111 score);
team_total_average t2t1 ("Dec 2" is not present in the cited claim's metadata).

Scoring artifacts: phase_all_then_regular t2t1 (correct `69-32.`); team_ppg t1t2, t2t2;
team_month_switch t1t2, t2t1, t2t2; team_margin t1t2, t2t2; opponent_switch_team_stats t1t2,
t2t2. Nine of these have correct values; only the secondary rounded number or the trailing
period made the harness fail them.

## Ranked live defects with minimal reproductions

All commands run in the worktree after `uv sync --all-packages --all-extras --dev`,
`. /tmp/go.env`, `export REDIS_URL=redis://localhost:56500/3`, and
`docker exec kiq-integrate-redis-1 redis-cli -n 3 flushdb`.

1. **Fallback on 17.2% of turns; the repair path raises instead of repairing.** 22 turns
   fall back: 10 after reviewer rejection and 12 without a review verdict (10 deterministic or
   repair-path failures and 2 after the state loss in defect 2; one of the 12 logged a
   TimeoutError at `revise`). One
   further turn committed no state although its LLM answer was correct (defect 5).
   `Model or budget unavailable.` is used for a repair-call
   `ValidationError` (malformed structured output), so the warning mislabels the cause.
   Reproduction: the full run's rows are in `failing_turns.txt`; a narrower rerun is
   `uv run --package knicksiq-api python tools/release/followup_bench.py --trials 2
   --session opponent_phase_switch --session team_margin --session topic_overall_after_player
   --out /tmp/repro.json`. 19 of the 22 fallbacks still contained the expected
   value, so the damage is lost validation and session pass rate, not mainly wrong numbers.
2. **A refusal that cites facts overwrites the last accepted topic/scope.** 3 turns.
   `analyst_delivery.render` sets `state["declined"] = not claims and not evidence_ids`, so a
   refusal that carries archive facts marks the off-topic turn as accepted; `prepare` then
   copies its scope into `last_topic`/`last_scope`. The next "And his assists?" / "And overall?"
   loses the prior December or all-phase scope. Repro:
   `uv run --package knicksiq-api python tools/release/followup_bench.py --trials 2
   --session injury_decline --session decline_then_overall --out /tmp/repro.json`.
   Observed: injury_decline t3 falls to 74 regular-season games on both trials;
   decline_then_overall t3 passes on trial 1 (claim-less fallback decline) and fails on trial 2
   (model refusal that recited the record). The offline audit cannot see this because its
   deterministic decline has no claims.
3. **Aggregation changes are missed by the writer.** `team_total_average` t1t2 answers the
   December total (1,710) to "And per game?" instead of 122.14, with LLM validation true.
   Repro: `--trials 2 --session team_total_average` (the failure is stochastic; observed once
   in two trials).
4. **Answerable narration is declined.** `game_why` turns 2 both trials decline the "why"
   question while quoting the 115-111 score, so the honest scorer records
   `declined:phrase:decline`. Repro: `--trials 2 --session game_why`.
5. **Session commit can fail after a successful answer.** `reverse_switch_topic` t2t1 returned
   a correct validated answer with `revision=null`, `state_committed=false`; the client lost
   the token and the next turn started a fresh session, losing December scope. The commit Lua
   returns 0 when the 35 s lease expired or on a Redis error; the exception is swallowed as a
   warning. Deterministic lease mechanism reproduction (no provider call):
   ```
   uv run --package knicksiq-api python - <<'EOF'
   import asyncio, uuid
   from app.services.analyst_sessions import SessionTurn

   async def main():
       turn = await SessionTurn.begin(None, uuid.uuid4().hex, 0, {"question": "lease probe"})
       await asyncio.sleep(36)
       print(await turn.commit({"answer": "probe"}, turn.state))

   asyncio.run(main())
   EOF
   ```
   printed `False`. The observed turn's latency was not retained by the harness at the measured
   SHA, so lease expiry versus a transient Redis error is not distinguishable from the JSON.
6. **Two benchmark scoring false negatives inflate the failure count by 10 turns (not product
   defects).** `analyst_checks._same_number` passes an empty right raw string, collapsing the
   precision tolerance to exact equality, so a correctly rounded 116.3 or +2.8 against a
   full-precision claim is "unbacked". `followup_oracle.RECORD_PAIR` rejects a record at the
   end of a sentence because its lookahead forbids `.`. Reproduce:
   ```
   uv run --package knicksiq-api python - <<'EOF'
   import sys
   sys.path.insert(0, "tools/release")
   from analyst_checks import _same_number
   from followup_oracle import matches_record

   print(_same_number(116.3, 116.28571428571429, "116.3", ""))   # False
   print(matches_record("New York went 69-32.", 69, 32, 101))     # False
   EOF
   ```
   The same calls with `"116.28571428571429"` or `"69-32 and"` print `True`. Affected turns are listed
   above. With both fixed the honest turn pass would be 100/128; the remaining non-artifact
   failures are the fallback/review cluster, the state bug, the aggregation miss, the two
   declines, the uncited date and the commit failure.
7. **Minor: uncited date.** `team_total_average` t2t1 states "Dec 2–31, 2025" while the point
   claim has `window=null` and no date filters, so the date is not in the cited claim. The
   value is correct. Either carry the resolved window into claim metadata or omit the date.

## Model routing check

The measured harness dropped per-call model fields from `stages`; the committed harness now
keeps `model`, `served_model`, `protocol`, `provider`, `finish_reason`, `review_accepted` and
latency. A 6-turn probe (`model_routing.json`, 2 sessions, 1 trial) shows 7 writer calls to
`deepseek-v4.1-flash` over `chat` and 6 reviewer calls to `gpt-6-luna` over `responses`, all
`finish_reason=stop`; every review was accepted. Provider metadata is `null` in these traces.
This verifies the routing configuration, not every call of the recorded 128-turn run.

Harness fixes made for reruns: `require_live_env` now accepts `AI_API_KEY` (Go) as well as the
legacy `OPENROUTER_API_KEY`; the stage projection keeps the routing fields above. The default
`--out` still points at `w3-followups`; pass `--out` explicitly for this directory.

## Commands and observed results

```
cd ~/.local/share/knicksiq/worktrees/w4-followups
uv sync --all-packages --all-extras --dev
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/3
docker exec kiq-integrate-redis-1 redis-cli -n 3 flushdb
uv run --package knicksiq-api python tools/release/followup_bench.py --trials 2 --flush-redis \
  --out docs/release-evidence/llm-primary-20261021/w4-followups/followup_sessions.json
```
Observed: `{"turns": 128, "turn_passes": 90, "session_passes": 24, "session_runs": 54}` and
causes `{"pipeline:degraded": 23, "answer:value": 12, "answer:declined": 2, "scope": 1}`.

```
uv run --package knicksiq-api python tools/release/followup_scope_audit.py \
  --out docs/release-evidence/llm-primary-20261021/w4-followups/offline_scope_audit.json
```
Observed: 27/27 sessions, 64/64 turns, 64/64 scope clean, no causes.

```
uv run --package knicksiq-api python tools/release/followup_bench.py --trials 1 \
  --session record_home_road --session opponent_phase_switch \
  --out docs/release-evidence/llm-primary-20261021/w4-followups/model_routing.json
```
Observed: 6/6 turns pass; 7 writer / 6 reviewer calls on the expected models.

Provider calls spent: 329 (full run 307: 153 writer actions, 35 repairs, 119 reviews; routing
probe 13; smoke 9). No HTTP 429 or account error appeared in the captured logs; calls continued across both
trials and the probe.

## Open risks

- Reviewer-rejection reasons are not in the recorded JSON: the measured harness kept only
  stage/tool/status. The patch records `review_accepted` and per-call routing on the next run,
  but not the reviewer's issue text.
- The commit failure is 1/128 and the harness at the measured SHA did not retain turn latency,
  so its mechanism (35 s lease expiry vs transient Redis error) is not proven for that row.
- These results are on `536d12e`. `cacf474` adds a reversed-record gate and `b000e5a` fixes
  non-analyst Go session ids; rerun on integration HEAD before publishing final numbers.
