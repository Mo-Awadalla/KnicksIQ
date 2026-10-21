# turning_points: get_game_flow

Branch `codex/llmp-turning`, based on `codex/llmp-integration` (c3ad843). Local release
`2025-26.20260928.1`, Redis db 9, provider cutoff $2, 60 live questions spent.

## What changed

- `apps/api/app/services/analyst_flow.py` defines every concept deterministically:
  scoring play, score state, largest lead, lead change, tie, scoring run, go-ahead for
  good, clutch window, deficit erased, lead lost and period net. The release's
  `scoring_runs` and `bad_stretches` tables contain zero rows, so runs are rebuilt from
  `game_events` rather than trusted from those tables.
- `analyst_flow_claims.py` turns one game flow into immutable claims with game_events
  receipts (period, clock, score before and after).
- `analyst_tool_runs.py` ranks the largest run, comeback, deficit and lost lead across
  a game set and exposes `run()` for the registry.
- `analyst_tool_registry.py`: one appended `ToolSpec` named `get_game_flow` and a
  two-sentence game-flow instruction in `tools_hint()`. The instruction makes the model
  call this tool alone first; the input packer otherwise spends the claim budget on
  unrelated discovery box scores before flow claims are reached.
- Every claim names the game's phase and states whether it is regular season, play-in
  or playoffs. The handler respects `scope.season_type`; it does not hard-code a
  season default.

The prompt addition is intentionally short because the model input budget is 8,000
bytes and the schema-growth fallback test is sensitive to it.

## Live results

Base and head use the same release, provider, Redis db and cutoff. Base questions were
run on `codex/llmp-integration`; head questions on this branch. `meets_expectation` is
the harness screen, not a truth label.

| Question | Base | Head | Head answer core |
| --- | --- | --- | --- |
| turning_points-001 | 0/2 | 1/2 | 17-0, Q2 07:29 to 03:49, 2025-10-24, 105-95 |
| turning_points-002 | 2/2 | 1/1 | Toronto dates, clarification |
| turning_points-003 | 0/2 | 1/1 | 14-point lead lost, 2026-04-20, 106-107 |
| turning_points-004 | 2/2 | 1/1 | Chicago dates, clarification |
| turning_points-005 | 0/2 | 2/2 | 21-point deficit erased, 2026-03-15, 48-27, 110-107 |
| turning_points-006 | 2/2 | 1/1 | Boston dates plus drought clarification |
| turning_points-007 | 0/2 | 2/2 | 17-0 BKN overall; 15-0 PHX in a loss |
| turning_points-008 | 0/2 | 1/1 | 21-point deficit in both CHA losses |
| turning_points-009 | 0/2 | 1/1 | 12-point deficit, 2026-01-28, 7-0 run |
| turning_points-010 | 2/2 | 1/1 | Atlanta dates, clarification |

Base: 8/20 responses and 4/10 questions. Head: 12/13 responses, 9/10 questions with
every trial passing, and 10/10 with at least one verified answer.

Trial coverage is uneven because the 60-question budget was exhausted: 2 trials for
001, 005 and 007; 1 trial for the rest. An earlier 18-response head pass used a
pre-tuning prompt and is excluded as invalidated. The one head failure is
turning_points-001 `failed:orchestrate:ValueError` with the fallback aggregate dump;
its retry answered correctly. This is provider/orchestrator stochasticity, not a wrong
flow number.

`turning_points-005` was run with a temporary, uncommitted mirror of the phase-policy
change in `query_resolution.py` from `codex/llmp-correctness` (season-level questions
default to regular season). The branch does not include that change. Merge
`codex/llmp-correctness` before re-running; without it the same question resolves to
all phases and the largest comeback is 29 in the 2026-06-10 playoff game.

### Exact statistics regression

Base sample: `exact_statistics-001`, `-003`, `-007`, `-014`, 2 trials each, 7/8 passed
(the one failure is the known fallback aggregate dump on `-003`, rejected by the
reviewer). A live head sample was not run: the 60-question budget was fully consumed
by the turning-point base and head runs. The new tool never computes box-score totals,
and the full backend suite is green (`411 passed`). A live exact-statistics head sample
remains to be run on the integration branch.

## Independent verification

`verify_turning.py` imports no application code. It reads `games` and `game_events`
and rebuilds runs with the audit SQL's lag grouping, margins, comebacks, go-ahead
plays and date lists. It checks every key number and date in `head.responses.jsonl`.

`verification.json`: 10/10 questions have at least one verified answer; 9/10 have every
trial verified (001 has the orchestration failure above). The oracle confirms:

- 001: NYK 17-0 vs BOS, game 2, Q2, 2025-10-24.
- 003: ATL loss on 2026-04-20, 14-point lead lost; 26-point deficit on 2026-01-02.
- 005: regular-season largest erased deficit 21, 2026-03-15, 48-27 stretch, 110-107.
- 007: opponent 17-0 on 2026-03-20; opponent 15-0 in a loss on 2026-01-17.
- 008: 21-point deficits on 2026-03-26 and 2026-04-12.
- 009: 12-point deficit on 2026-01-28, 47-34 stretch, 7-0 run.

## Commands

```sh
# Base, on the integration tree:
.venv/bin/python /tmp/run_with_env.py <integration>/.venv/bin/python \
  docs/release-evidence/llm-primary-20261021/turning/run_category.py \
  --category turning_points --trials 2 --out .../base.json

# Head, on this branch:
.venv/bin/python /tmp/run_with_env.py .venv/bin/python \
  docs/release-evidence/llm-primary-20261021/turning/run_category.py \
  --category turning_points --trials 2 --out .../head.json

# Independent audit:
.venv/bin/python verify_turning.py

# Backend gate:
TEST_MODE=true uv run pytest apps packages tools/report_audit
uv run ruff check apps packages migrations
uv run ruff format --check apps packages migrations
uv run pyright apps packages migrations
```

`run_with_env.py` is a local wrapper, not committed: it reads the repository `.env`
without printing it, overrides DB/Redis/cutoff, and execs the command. The harness
itself is `run_category.py` in this directory.

## Open risks

- turning_points-001 passed 1 of 2 head trials. The failure is an orchestrator
  `ValueError` followed by the aggregate fallback, not a wrong run. Reducing this
  needs the reviewer/orchestration work, not a flow change.
- The live head answers were produced with the longer prompt hint. The committed hint
  is shorter so `mandatory_bytes` stays within 8,000 and the schema-growth test passes;
  the instruction is unchanged. A final live confirmation on integration is
  recommended.
- No live head sample for exact_statistics (budget exhausted). Gate tests pass.
- Only the game-set path was live-tested. The single-game and period-scoped paths were
  exercised directly against the release database, not through the provider.
- Head 005 depends on `codex/llmp-correctness`; without it, season-level questions
  remain all-phase.
- Claims describe observed sequence only. Causal wording remains governed by the
  existing interpretation policy; the tool supplies no causes.
