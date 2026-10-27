# Dispatch parity, base vs registry branch

Base tree: `d5800118b497e92e5e5609c7b66404d930e1e2fb` extracted to `/tmp/kiq-base-registry`.
Branch tree: this worktree before the artifact commit.
Local release: `2025-26.20260928.1`, local Postgres on port 55500, Qdrant off.

Command, run once per tree:

```text
DB_URL=postgresql+asyncpg://knicksiq:knicksiq@localhost:55500/knicksiq \
  uv run python tools/release/registry_dispatch_parity.py --root <tree> --out <json>
```

`registry_dispatch_parity.py` calls the same `ToolCall` matrix through `AnalystTools.execute`,
hashes each canonical `ToolResult` JSON, and records the imported `app` path (`--root` is asserted
to win the import). The reports are `dispatch-parity-base.json` and `dispatch-parity-head.json`.
Removing the `app` path, the two reports are byte-identical.

| Case | Status | Claims | Evidence |
| --- | --- | --- | --- |
| team_total | ok | 4 | 101 |
| team_average | ok | 4 | 101 |
| player | incomplete_coverage | 1 | 93 |
| discover | ok | 10 | 10 |
| archive | no_matching_results | 0 | 0 |
| compare | ambiguous_entity | 0 | 0 |
| periods_guard | unsupported_metric_or_scope | 0 | 0 |
| empty_games | ok | 4 | 101 |
| missing_player | ambiguous_entity | 0 | 0 |
| season_guard | unsupported_metric_or_scope | 0 | 0 |
| unissued_evidence | unsupported_metric_or_scope | 0 | 0 |
| issued_evidence | ok | 0 | 2 |

The matrix covers the happy path for all six tools plus the four pre-check branches: periods,
empty games, player requirement, season guard, and issued-evidence validation. Claim ids, evidence
ids, messages, scopes and ordering are included in the hash.
