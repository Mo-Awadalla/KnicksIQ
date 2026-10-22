# Multi-turn follow-up session benchmark (w3-followups)

Status: offline benchmark and defect reproductions complete. The two live trials are blocked
because the OpenRouter account behind `OPENROUTER_API_KEY` returns HTTP 402 (usage 35.159 of
35 USD). Zero live questions were spent; no 402 response was scored or stored. The live harness
is committed and reruns with one command once credits are restored.

Base: `codex/llm-integration` at `5b585e6` (branch `codex/llm-w3-followups`).

## Files

| Path | Role |
| --- | --- |
| `apps/api/app/evaluation/followup_sessions.jsonl` | 27 sessions, 64 turns, 2 to 4 turns each. Scope expectations only; no hand-typed answers. |
| `tools/release/followup_oracle.py` | Computes expected records, player averages/totals and team averages/totals from the active local release. Also parses answers and compares committed scope. |
| `tools/release/followup_bench.py` | Live in-process harness: session token, revision and `context` per turn; reads committed state from Redis; honest checks plus expected scope and revision integrity. |
| `tools/release/followup_scope_audit.py` | Deterministic half: prepare, backend prefetch, recovery lookup and deterministic fallback, with the state a turn would commit. No provider. |
| `tools/release/followup_scope_repros.py` | 12 minimal reproductions, each with an explicit "defect present" predicate. |
| `offline_scope_audit.json` | Every turn of every session: expected scope, actual scope, carried claims, prefetch calls, fallback text, honest checks, cause. |
| `offline_spread.json` | Per-session pass marks from two runs and the summary. |
| `repro.txt` | Captured reproduction transcript. |
| `failing_turns.txt` | One row per failing turn: cause, scope issues, prefetch and recovery stages, fallback text. |

Generated JSON and TXT are marked `linguist-generated=true` in `.gitattributes`.

## Coverage

27 sessions, 64 turns. Categories: phase_change 7, home_road 2, opponent_switch 3,
player_switch 2, pronoun 1, window_change 3, aggregation 1, game_reference 1, explanation 1,
decline 3, topic_retention 2, metric_change 1.

The sessions exercise regular/playoffs/overall phase changes, home/road, opponent switches,
player switches ("what about Towns?"), pronouns ("his assists"), windows ("last 5", "in
December", "in January"), metric changes ("and points?", "average margin"), aggregation changes
("and per game?"), game references ("that game", "the game before that"), an explanation
follow-up ("why did they lose that game?"), and declines in the middle of a session (betting,
injury) followed by an answerable turn.

## Expected values

Each turn names a structured scope: phase (`regular`, `playoffs`, `all`, `any`), opponent, home
or road, month, relative window, date, player, metric and aggregation. The oracle reads the
active release from `DB_URL` and computes the expected record, value and game population. A
record must be `W-L` with `W+L` equal to the population size, or the fallback's
`wins: W over N ... losses: L over N` wording. A stat must be within display tolerance of the
computed value; totals are integers. Narrative turns require the Knicks points or the opponent
alias from the archive row. The model never writes an expected value.

## Scoring

- Honest checks: `analyst_scoring.score_response` with citations, required facts, required
  entities, unbacked-number detection, decline handling and no-cited-claims.
- Expected semantic check from the oracle (record shape, value tolerance, narrative anchor).
- Expected scope from the committed state: season type and all-phases flag, player ids, metric,
  opponent, home/away, relative window, date range, exact game ids where the turn names a game,
  and the game population the scope selects.
- Live session integrity: one token for the session, committed revisions 1..N, `state_committed`
  on every committed turn, and the returned revision equal to the prior revision plus one.
- Offline audit: deterministic backend prefetch, then the same recovery lookup the server runs
  when a turn has no claims, then the deterministic fallback claim selector. This isolates
  scope and fallback behaviour; it does not model model wording.

## Offline results (deterministic, two runs)

Two runs are byte-identical (`offline_spread.json`; audit sha256
`412dbcc25079a3d8d44c0371e0ce81422153a73cd725c51ace55069d12bc338d`). Spread is 0 turns across
the two runs. Totals: 7/27 sessions pass, 35/64 turns pass the fallback content check, 42/64
turns resolve the expected scope. Causes: scope 11, scope+decline 10, answer:value 5,
answer:declined 2, latent_scope 1.

`.` is a passing turn, `F` a failing turn. `pass` counts fallback content; `scope` requires
every turn's committed scope to match.

| Session | Turns | Marks | Pass | Scope clean |
| --- | --- | --- | --- | --- |
| phase_regular_overall_playoffs | 3 | ... | 3/3 | yes |
| record_home_road | 3 | ... | 3/3 | yes |
| phase_all_then_regular | 2 | .. | 2/2 | yes |
| phase_playoffs_then_overall | 2 | .. | 2/2 | yes |
| including_playoffs | 2 | .. | 2/2 | yes |
| home_phase_change | 2 | .. | 2/2 | yes |
| team_ppg_home_away_playoffs | 3 | FFF | 0/3 | no |
| opponent_switch_record | 2 | .F | 1/2 | no |
| opponent_phase_switch | 3 | ... | 3/3 | yes |
| opponent_home_road | 3 | .FF | 1/3 | no |
| player_switch | 2 | .F | 1/2 | no |
| player_pronoun_metric | 2 | .F | 1/2 | no |
| player_phase_change | 2 | .F | 1/2 | no |
| player_month_switch | 2 | .F | 1/2 | no |
| player_last5_to_month | 2 | .F | 1/2 | no |
| team_total_average | 2 | .F | 1/2 | no |
| game_reference_chain | 3 | FFF | 0/3 | no |
| game_why | 2 | FF | 0/2 | no |
| betting_decline | 3 | ..F | 2/3 | yes |
| injury_decline | 3 | ..F | 2/3 | no |
| phase_after_player | 3 | ..F | 2/3 | no |
| topic_overall_after_player | 2 | .F | 1/2 | no |
| team_month_switch | 2 | FF | 0/2 | no |
| team_margin | 2 | FF | 0/2 | no |
| opponent_switch_team_stats | 2 | FF | 0/2 | no |
| reverse_switch_topic | 2 | .F | 1/2 | no |
| decline_then_overall | 3 | ..F | 2/3 | yes |

The phase-change sessions (1 to 6, `opponent_phase_switch`, `phase_after_player`,
`topic_overall_after_player`) also cover the one-phase claim carry rule. The audit carried no
regular-season claim into an all-phase or playoff turn; the observed `carried_claims` arrays are
empty there, so that earlier fix still holds on `5b585e6`.

## Ranked follow-up defects with minimal reproductions

Reproduction numbers refer to `followup_scope_repros.py`; all 12 cases print REPRODUCED on
`5b585e6`.

1. Inherited scope omits metric, relative window, date window and game ids. 22 turns resolve a
   different population than the follow-up implies. `analyst_tools.py:142` copies only
   `player_ids, season_type, opponent_id, home_away, game_result`. Results: a player switch
   after "last 5 games" drops the window and metric (repro 1); "his points" after a December
   average drops December (repro 2); "And in the playoffs?" after a player average drops the
   metric (repro 3); "that game" drops the game ids and returns to 82 regular games (repro 5);
   "And per game?" after a December total drops the month (repro 11). 13 turns have a lost
   metric, 7 a lost date window, 3 a lost game reference.
2. An any-phase matchup or window becomes regular season on the next turn. A matchup question
   resolves `season_type=None` without `all_phases`, and `analyst_tools.py:102-106,149` treats
   that as unspecified and defaults the follow-up to regular. "And at home?" after the
   Cleveland matchup returns 2 games instead of 4 (repro 6); matchup, game and player-switch
   follow-ups all show the same `season_type=regular` drift.
3. An opponent switch phrased "what about X?" asks which player. `analyst_tools.py:162` reads
   "about Cleveland" as an unknown subject and produces a player clarification (repro 7).
   `opponent_switch_record` turn 2 fails completely.
4. "Points per game against <opponent>" asks which game. `query_resolution.py:436-440` treats
   "per game" as a single-game reference when an opponent is present; the turn returns
   ambiguous-game choices (repro 8). `opponent_switch_team_stats` turn 1 fails.
5. Elliptical topic detection runs after inheritance. `analyst_tools.py:187` checks the merged
   scope, so a follow-up whose player or metric was just inherited is never elliptical and the
   prior intent is overwritten by the two-word question. "And overall?" after a player window
   loses both the topic and the metric and the fallback declines (repro 4); the same happens
   for "And in the playoffs?" after a player average (sessions `player_phase_change`,
   `phase_after_player`, `topic_overall_after_player`).
6. A declined turn overwrites intent. `prepare` always replaces `state["intent"]`, so after a
   betting or injury decline the next "And overall?" / "And in the playoffs?" has no topic;
   the deterministic fallback returns no claims (repro 10). Sessions `betting_decline` and
   `decline_then_overall` fail turn 3 even though their scope is correct.
7. The deterministic fallback reads "how many ... game(s)" as a record request.
   `analyst_fallback.py:23` matches "per game", "last game" and "that game" questions, so a
   points question falls back to wins and losses instead of points or per-game points
   (repro 9). The five answer:value turns are all this path: home team PPG, the two December
   team PPG sessions, the last-game team points turn and the dated-game team points turn. The
   fallback answers with a W-L record.
8. A total-to-average follow-up keeps the topic's aggregation. `analyst_prefetch.py:80-87`
   picks the aggregation from the previous topic, so "And per game?" after a total prefetches
   `get_team_stats` with `aggregation=total` (repro 11). Combined with defect 1 it answers
   116.45 over 82 games instead of 122.14 over 14.
9. An explanation follow-up has no game retention and no deterministic fallback. "Why did they
   lose that game?" resolves 82 regular games, and the fallback prints the season record
   without the opponent (repro 12). Whether the live model recovers from context is untested
   until credits return.

## Commands and observed results

```
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python tools/release/followup_oracle.py
```
64 turns across 27 sessions; expected values printed for every turn.

```
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python tools/release/followup_scope_audit.py
```
`{"sessions": 27, "sessions_pass": 7, "sessions_scope_clean": 9, "turns": 64,
"turns_pass": 35, "turns_scope_clean": 42}` and cause counts
`{"answer:value": 5, "scope": 11, "scope+decline": 10, "latent_scope": 1,
"answer:declined": 2}`. Repeated runs are byte-identical.

```
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python tools/release/followup_scope_repros.py
```
Exit 0; `REPRODUCED 12 of 12`. Transcript in `repro.txt`.

## Backend gate on this branch

`TEST_MODE=true uv run pytest apps packages tools/report_audit -q`: 439 passed in 36.69s.
`uv run ruff check apps packages migrations`: all checks passed.
`uv run ruff format --check apps packages migrations`: 246 files already formatted.
`uv run pyright apps packages migrations`: 0 errors, 0 warnings. The four new files also pass
`ruff check` and `ruff format --check`.

## Pending live runs (blocked on provider credits)

128 questions are required (64 turns x 2 trials), inside the 150-question budget. Redis db 8.

```
docker exec kiq-integrate-redis-1 redis-cli -n 8 flushdb
set -a; . /Users/mohamedawadalla/Projects/KnicksIQ/.env; set +a
export DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq
export REDIS_URL=redis://localhost:56500/8
export ANALYSIS_ANSWER_MODE=llm_primary ANALYST_EVIDENCE_LOOP_ENABLED=true
export RAG_QDRANT_ENABLED=false OPENROUTER_MONTHLY_CUTOFF_USD=2 AI_REASONING_EFFORT=none
uv run --package knicksiq-api python tools/release/followup_bench.py --trials 2 --flush-redis
```

Writes `followup_sessions.json` next to this file with per-turn stages, committed scope,
honest failures, revisions and session integrity, plus per-session pass spread and causes.

## Open risks

- Offline pass counts measure the fallback trajectory, not model wording. A live turn can pass
  the answer check while the committed scope is still wrong; the harness records both.
- Two scope defects (3 and 4) and defect 7 are answer-level even when a model writes the
  answer, because the turn never reaches a normal aggregate or falls back to the wrong family.
- The audit uses backend prefetch plus the server's recovery lookup; the model may choose other
  tools. Scope resolution happens before any model call and is unaffected.
