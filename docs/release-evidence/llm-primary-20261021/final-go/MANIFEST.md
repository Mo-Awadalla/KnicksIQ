# Provenance

Frozen SHA: `51f184a` on `codex/llmp-integration` ("Keep reasoning off; freeze for the final
runs"). Worktree `~/.local/share/knicksiq/worktrees/final2`, branch `codex/llmp-final2`.
No file under `apps/` or `packages/` was modified; the branch contains only this evidence
directory.

Every artifact in this directory was produced from that SHA. Generated harness output does not
embed the SHA; this manifest and `README.md` are the provenance record for it.

| Artifact | Producer | SHA |
| --- | --- | --- |
| `bench/metrics.json`, `bench/trial{N}.json`, `bench/trial{N}.scored.jsonl`, `bench/trial{N}.responses.jsonl`, `bench/calls.jsonl`, `bench/ledger.jsonl` | `../w4-bench/bench_runner.py` (unchanged) | 51f184a |
| `bench/run.log` | same benchmark, stdout | 51f184a |
| `audit/trial{N}/rows.jsonl`, `summary.md`, `diff.md` | `../factual-audit/audit.py` | 51f184a |
| `audit/flag-verdicts.md` | manual SQL re-check of every flagged atom | 51f184a |
| `followup/followup_sessions.json` | `tools/release/followup_bench.py` | 51f184a |
| `followup/summary.json` | derived from the raw follow-up output | 51f184a |
| `followup/run.log` | follow-up stdout | 51f184a |

Redis: db 10 on `kiq-integrate-redis-1`, flushed once before the benchmark. Restore DB:
`kiq-integrate-postgres-1`, port 55500. Host: OpenCode Go. Reasoning `none`; reviewer
`gpt-6-luna`.

Provider calls: 370 benchmark + 314 follow-up = 684. No HTTP 429, no account error, no
`MissingSessionID`, no transport error.
