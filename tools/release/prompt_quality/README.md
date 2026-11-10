# KnicksIQ prompt-quality evaluation

Portable export of the human-approved, flexible-answer evaluation. It calls the real
`/analysis/query` ASGI application against an isolated archive restore. It does not
change the production model configuration or application prompt.

## Recorded result

| Version | Change | Train pass | Held-out pass | Decision |
|---|---|---:|---:|---|
| Baseline | Original prompt | 30% | 16% | Retained |
| v1 | Preserve intent through subject corrections | 28% | 24% | Reverted |
| v2 | Preserve requested comparisons | 28% | 16% | Reverted |
| v3 | Compress orchestration instructions | 34% | 4% | Reverted |

Three non-improving rounds reached the approved plateau stop. **Do not merge any of
the experiment patches.** There were 75 completed scored trials per version:
15 cases × five repetitions, split into 10 training and five held-out cases.
All 300 score rows are in `scores/`; aggregate intervals, prices, errors, and gate
verdicts are in `summary.json`. The patches in `experiments/` are rejected historical
experiments, not applied application changes.

The paired held-out changes were +8 ±13.6 percentage points, 0, and
−12 ±37.7 points. None passed the improvement gate. The baseline interval was
16% ±32.4 points. A zero observed delta interval does not establish certainty.
Training-failure analysis classified 31 of the 33 failed v3 training rows as
structural and two as variance; these are model-assisted diagnoses, not proven
causes. More prompt wording did not demonstrate a fix.

## Included and excluded

- `runner.py`: real-app execution, fresh sessions, strict retry handling and train-only traces.
- `proofs.py`: independent source-row, identity, arithmetic and population verification.
- `grader.py`: flexible semantic grading and calibration using a separate model.
- `cases.json` and `split.json`: approved behavioral expectations and the historical split.
- `scores/`, `summary.json`, `experiments/`: transcript-free historical results.

No conversation transcripts, quoted before/after answers, judge explanations,
provider credentials, database credentials, archive snapshots, virtualenv files,
or machine-bound ratchet approvals are included. The original local flow remains
unchanged. Its approval hashes do **not** authorize this relocated harness; a new
ratchet optimization requires fresh harness/plan approvals. The standalone runner
does not implement or bypass ratchet's approval and keep/revert gates.

## Prerequisites and isolation

Run commands from the repository root. Use the workspace Python environment
(`uv sync --frozen --all-packages`), Docker, and an active OpenCode Go account
configured with `opencode auth login`. Credentials are loaded in memory through
`opencode auth export`; do not redirect that command to a file.

Candidate: OpenCode Go `deepseek-v4.1-flash`. Judge: `glm-5.3-flash`.
Both must remain available under the configured account. Inference consumes the
account's allowance even when the response reports zero per-request billing cost.

Use the separately obtained, approved archive bundle:

- `release-artifacts/2025-26/reliability-approved-20260928.json.gz`
- SHA-256: `549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b`
- Release: `2025-26.20260928.1`; 101 games.

This evaluates an explicitly selected **2025–26 archive**, not current-season or
live injury coverage. Do not replace the bundle with synthetic or newer data and
reuse these historical scores.

## Prepare a disposable local backend

Use dedicated ports and container names. These commands create new containers;
they do not reset existing databases. Choose different names/ports if occupied.

```bash
export EVAL=tools/release/prompt_quality
export DB_PASSWORD="$(openssl rand -hex 24)"
export RATCHET_DB_URL="postgresql+asyncpg://knicksiq:${DB_PASSWORD}@127.0.0.1:55439/knicksiq"
export RATCHET_REDIS_URL=redis://127.0.0.1:56389/0
export RATCHET_MAPPING_DIR="$PWD/$EVAL/local"

docker run --rm -d --name knicksiq-prompt-eval-pg \
  -p 127.0.0.1:55439:5432 -e POSTGRES_USER=knicksiq \
  -e POSTGRES_PASSWORD="$DB_PASSWORD" -e POSTGRES_DB=knicksiq postgres:18-alpine
docker run --rm -d --name knicksiq-prompt-eval-redis \
  -p 127.0.0.1:56389:6379 redis:7-alpine
```

Wait for PostgreSQL readiness (`docker exec knicksiq-prompt-eval-pg pg_isready -U
knicksiq -d knicksiq`), then migrate, load, and independently verify the restore:

```bash
env DB_URL="$RATCHET_DB_URL" REDIS_URL="$RATCHET_REDIS_URL" ENVIRONMENT=development \
  uv run --frozen --all-packages alembic upgrade head
env DB_URL="$RATCHET_DB_URL" REDIS_URL="$RATCHET_REDIS_URL" ENVIRONMENT=development \
  uv run --frozen --all-packages knicksiq-load-release \
  release-artifacts/2025-26/reliability-approved-20260928.json.gz \
  --sha256 549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b --activate
mkdir -p "$RATCHET_MAPPING_DIR"
uv run --frozen --all-packages python tools/release/runtime_mapping.py \
  --dsn "$RATCHET_DB_URL" \
  --output "$RATCHET_MAPPING_DIR/runtime-mapping.json" \
  --report "$RATCHET_MAPPING_DIR/runtime-mapping-verification.json"
```

The runner requires an explicit `RATCHET_DB_URL`; both it and the Redis URL must
be loopback. It overrides the application's ordinary database/provider settings
in its own process. Never use a production database or rely on the application's
ambient `DB_URL`. Mapping identities must come from this exact local restore.

## Exercise and run

An induced provider error makes no provider request. It exercises the real API
and must produce `errors.jsonl` with `provider_error`, not a zero-grade result:

```bash
.venv/bin/python "$EVAL/runner.py" --variant smoke-error \
  --out "$EVAL/local/smoke-error" --cases "$EVAL/cases.json" \
  --split "$EVAL/split.json" --pilot knicks-02 --induce-error
```

Calibrate the independent grader (this makes real judge calls):

```bash
PYTHONPATH="$EVAL" .venv/bin/python -c \
  'import asyncio, json, grader; print(json.dumps(asyncio.run(grader.preflight())))'
```

Run one training pilot, then a full comparison if desired. Always use a fresh
output directory for a changed harness, prompt, or grader:

```bash
.venv/bin/python "$EVAL/runner.py" --variant pilot \
  --out "$EVAL/local/pilot" --cases "$EVAL/cases.json" \
  --split "$EVAL/split.json" --pilot knicks-02
.venv/bin/python "$EVAL/runner.py" --variant baseline \
  --out "$EVAL/local/baseline" --cases "$EVAL/cases.json" \
  --split "$EVAL/split.json" --reps 5
```

The process reports per-slot outcomes and may exit successfully with error rows.
Require exactly 75 unique `(prompt_id, rep)` score rows before claiming a complete
full run. Repeating the identical command resumes unscored slots without duplicating
completed results. An external attempt that succeeds only after retry remains an
error for that invocation. The real application retains its own repair behavior.
Train traces and judge explanations are local-only and may contain full answers;
the runner never persists held-out traces when given the split. Keep all new run
outputs under ignored `local/`, not under the committed historical `scores/`.

Stop only the disposable containers created above when finished:

```bash
docker stop knicksiq-prompt-eval-pg knicksiq-prompt-eval-redis
unset DB_PASSWORD RATCHET_DB_URL RATCHET_REDIS_URL RATCHET_MAPPING_DIR
```

## Interpretation limits

The grading policy accepts different wording and different supported interesting
stats, but requires relevance, backend grounding, and contextual novelty. Missing
receipt proof fails grounding; unavailable arithmetic recipes, provider failures,
timeouts, and grader crashes remain errors. Delivered application fallbacks after
input-budget rejection are graded as delivered and expose `input_budget_ok=0`.

Historical error rows numbered 2, 12, 3, and 2 for baseline/v1/v2/v3; incomplete slots
were resumed. Scores are conditional on completed trials, not production reliability.
Cost estimates cover scored candidate and judge tokens, not failed-attempt spend.
Small held-out size, pre-split pilot exposure of a later test example, repeated
judging, and strict archive scope limit generalization. No deployment or live-season
quality claim follows from these results.

## Packaging verification

The portable CLI was exercised from outside the checkout against a fresh local
restore. A real OpenCode training pilot produced a scored result (the answer itself
failed the quality rubric); the induced provider failure produced only an error row.
The extracted grader's archive oracle passed twice, while empty, null, unknown,
and wrong-question controls failed. Missing database configuration, remote database
URLs, and remote Redis URLs were rejected. All 300 exported score rows have unique
case/repetition slots and contain no answer text or judge explanations.
