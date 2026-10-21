# Correctness evidence (codex/llmp-correctness)

## Reproduce without a provider

```
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run --package knicksiq-api python repro.py
```

Writes `repro-after/<id>.json` (compact scope counts, tool claims, fallback answer). The pre-fix
observations are quoted in `repro-before.md`; `failure-modes.md` records first wrong place and fix.

## Live acceptance run

```
DB_URL=... REDIS_URL=redis://localhost:56500/13 ANALYSIS_ANSWER_MODE=llm_primary \
ANALYST_EVIDENCE_LOOP_ENABLED=true OPENROUTER_MONTHLY_CUTOFF_USD=2 AI_* from the repo .env \
  uv run --package knicksiq-api python run_ids.py \
  --ids <the audited ids> --trials 2 --out acceptance.json
```

`run_ids.py` uses the same in-process app path as `tools/release/analyst_live_e2e.py`.
`acceptance.json` / `acceptance.responses.jsonl` hold both trials per id.

## Independent audit

```
python3 ../factual-audit/audit.py acceptance.responses.jsonl
```

`checks_policy_20261021.py` extracts each claimed value from the fresh answer and compares it
with the SQL oracle; season-level questions must state the regular season. The audit rewrites
`../factual-audit/summary.md` and `verdicts/` for this run.

## Result

See the final chat report for counts and commands. Backend gate: `TEST_MODE=true uv run pytest
apps packages tools/report_audit`, `uv run ruff check apps packages migrations`, `uv run ruff
format --check apps packages migrations`, `uv run pyright apps packages migrations`.
