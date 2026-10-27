# Elliptical follow-ups after a named game (w4-gamefollow)

Status: **VERIFIED** for the scope defect. Branch `codex/llmp-w4-gamefollow` from
`51f184a` (`codex/llmp-final2`), merged with integration `a56ef41`; code head
`dfc42c8`. The one live OpenCode Go run measured 15/15 turn-2 scopes on the single
game and 8/15 turns fully `ok`; the seven non-`ok` turns are five
reviewer/validation fallbacks and two wording/scoring rows, detailed below.

## The defect

Turn 1 names one game by opponent and date:

> How many points did the Knicks score against the Hawks on January 2?

Turn 2 asks a stat about it without repeating the game or saying "that game":

> What was the margin?

`AnalystTools.followup` was a lexical regex (pronoun, leading `and`/`why`/`now`,
`what about`). An elliptical stat question matched none of it, so no
`InheritedScope` was built and resolution returned the whole 82-game regular
season. The one-time held-out v2 run found this shape in 10 of 10 sessions.

## Reproduction

`gamefollow_sessions.jsonl` holds 15 fresh two-turn sessions over nine different
games: 3 margin, 3 team-stat, 3 quarter, 3 player-stat defect pairs, 2 "that game"
controls and 1 legitimate widening control (`And for the season?`). Expected values
and scopes are computed from the archive by `followup_oracle`; the file only states
the questions and filters.

`gamefollow_repro.py` prepares turn 1, commits its scope the way the session store
does, prepares turn 2 and compares the scope with the session's expectation. It also
probes a game-id-only window, a degraded turn between the game question and the
follow-up, and checks that every prefetched tool claim stays inside the turn's own
game window.

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python \
  docs/release-evidence/llm-primary-20261021/w4-gamefollow/gamefollow_repro.py
```

| Run | Result |
| --- | --- |
| `repro-before.txt` at `51f184a` | `WINDOW LOST 15 of 17 checks` (13 sessions, both probes); only the 2 deictic controls pass |
| `repro-after.txt` at this head | `WINDOW LOST 0 of 17 checks`; `DISPATCH WIDENED 0 of 15 sessions` |

Offline audit with the same sessions (`followup_scope_audit.py --sessions`):

```sh
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python tools/release/followup_scope_audit.py \
  --sessions docs/release-evidence/llm-primary-20261021/w4-gamefollow/gamefollow_sessions.jsonl \
  --out docs/release-evidence/llm-primary-20261021/w4-gamefollow/offline_audit_after.json
```

The before file was produced by the same command with the `51f184a` worktree's
environment (no branch code loaded).

| Metric | 51f184a (`offline_audit_before.json`) | this head (`offline_audit_after.json`) |
| --- | ---: | ---: |
| Sessions pass | 4/15 | 15/15 |
| Turns pass | 19/30 | 30/30 |
| Turn-2 pass | 4/15 | 15/15 |
| Turn-2 scope clean | 2/15 | 15/15 |

The base audit's causes were `scope+decline` 5, `scope` 5, `latent_scope` 3,
`answer:declined` 1. The after audit has no causes.

## Cause table

| Candidate | Found? | Evidence before | Fix |
| --- | --- | --- | --- |
| Not inherited: lexical follow-up gate | **Yes** | Every elliptical turn printed `followup=False` and 82 games (`repro-before.txt`); 13/15 sessions lost | `query_game_scope.is_elliptical_follow_up`: a team/opponent, date window, phase, site or season phrase stands alone; a stat/score/period question with none of those continues the prior population. `AnalystTools.prepare` resolves it after the archive games load. |
| Derived window lost: inherited `game_ids` never applied | **Yes** | A game named without a date ("their most recent game against the Hawks", ids `[88]`) followed by "What was the margin?" resolved all 9 Hawks games (`probe_game_id_window` LOST) | `resolve_query` bounds the candidates with the inherited ids when the follow-up names no opponent, site or outcome of its own, and keeps them in the resolved scope. |
| Season widening | **Yes** | "And for the season?" kept `date_start=date_end=2026-01-02` and 1 game | A season phrase replaces the inherited game/date window with the regular-season population (or the inherited phase), keeping subject and metric. |
| Declined flag after a degraded turn | **Yes** | Record turn, degraded game turn, then "What was the margin?" read `last_scope` from before the game and answered 82 games (`probe_degraded_turn` LOST) | `analyst_delivery.render` stores the resolved topic and scope as the last accepted frame for every non-refusal turn, including a claim-less fallback; a refusal still leaves the previous frame. |
| Dispatch/tool choice | **Yes, for one shape** | A single-game margin with no opponent (last game) prefetched `discover_facts`; the fallback had no margin claim and declined | A one-game scope with a points/margin/score shape now prefetches `get_team_stats`. Dispatch itself never widened: 0/15 sessions had claims outside the turn window. |
| Date window cleared by a metric | No | After the gate fix every metric follow-up keeps `date_start`/`date_end` and the game ids (`repro-after.txt`); the metric only replaces the metric field | none |
| `continues_topic` false | No scope effect | A metric-named follow-up returns `False` by design and becomes the topic; the inherited scope is unchanged (all metric turns in `repro-after.txt` keep the game window) | none |

## Live run (OpenCode Go, one run)

```sh
. /tmp/go.env
export REDIS_URL=redis://localhost:56500/12 BENCH_BASE=51f184a
uv run --package knicksiq-api python tools/release/followup_bench.py \
  --sessions docs/release-evidence/llm-primary-20261021/w4-gamefollow/gamefollow_sessions.jsonl \
  --trials 1 --flush-redis \
  --out docs/release-evidence/llm-primary-20261021/w4-gamefollow/live_after.json
```

`live_after.json`: 15 sessions, 30 turns, one trial. Turn 1 passed 15/15. Turn 2:

| Turn-2 metric | Result |
| --- | ---: |
| Scope clean | 15/15 |
| Cause `ok` | 8/15 |
| Model path (`llm_validated`) | 10/15 |
| Degraded (review/validation fallback) | 5/15 |
| Honest scorer pass | 9/15 |
| Expected check pass | 13/15 |

Routing: orchestrate/revise `deepseek-v4.1-flash` (chat), review `gpt-6-luna`
(responses); 30 orchestrate + 9 revise + 26 review calls. No HTTP 429 or account
error.

The seven non-`ok` turn-2 rows:

- 5 `pipeline:degraded`: the proposed wording failed validation/review and the
  deterministic fallback delivered the correct claim (margin -12, margin 22, Q3
  report, Q4 report, Brunson 24 points). This is the reviewer/validation class
  already counted in `w4-followups`, not a scope loss; all five scopes are clean.
- 1 `answer:value`, `team_bulls_apr3`: honest scorer passes; the answer states
  "Knicks 136, Bulls 96" and the oracle's narrative score check requires a
  hyphenated `136-96` pair. Benchmark wording artifact.
- 1 `answer:value`, `that_game_last_margin`: the model answered the final score
  (94-90) instead of the margin (4); required fact missing. Model wording.

A live before-run on `51f184a` was not spent: the defect is deterministic and the
same sessions lose 15/17 checks and 13/15 turn-2 scopes offline at that commit, and
the Go budget was reserved for the after measurement. The held-out v2 trigger
(10/10 sessions failed) is recorded in the integration history, not re-read here.

## Gate

On the merged head, in a clean environment:

```sh
env -i HOME="$HOME" PATH="$PATH" TEST_MODE=true uv run pytest apps packages tools/report_audit -q
# 439 passed
env -i HOME="$HOME" PATH="$PATH" uv run ruff check apps packages migrations        # All checks passed
env -i HOME="$HOME" PATH="$PATH" uv run ruff format --check apps packages migrations  # 260 files already formatted
env -i HOME="$HOME" PATH="$PATH" uv run pyright apps packages migrations          # 0 errors, 0 warnings
```

Follow-up suites on the same head:

- `tools/release/followup_scope_repros.py`: `REPRODUCED 0 of 17`.
- `tools/release/followup_scope_audit.py`: 27/27 sessions, 64/64 turns, 64/64 scope clean.
- `docs/release-evidence/llm-primary-20261021/w3-declines/reproduce_declines.py`: 73/73.
- `docs/release-evidence/llm-primary-20261021/correctness/repro.py`: 12/12 tools `ok`,
  0 failures.

## Commits

1. `193583a` continue the prior scope for elliptical stat questions.
2. `a078219` bound an elliptical turn by the inherited game ids.
3. `b4c7275` widen a follow-up that names the season.
4. `fb89e98` keep the scope of a degraded turn.
5. `c57b8f8` route a single-game margin or score to the team tool.
6. `dfc42c8` merge integration `a56ef41` (period phrase table, record-order gate,
   safety wording); no conflicts.

## Open risks

- The live pass rate is limited by the reviewer/validation fallback (5/15) and two
  wording/scoring rows, not by scope. A reviewer that accepts these terse claim
  statements would lift the turn-2 rate without a scope change.
- `is_elliptical_follow_up` deliberately treats a question with no team, window,
  phase, site, season phrase, stat, score or period as a new turn. "How did they
  do?" still does not inherit; it did not before either.
- The season phrase means the regular season unless a phase is already under
  discussion; a playoffs-scoped prior widens within that phase.
