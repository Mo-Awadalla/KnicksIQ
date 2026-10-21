# llm_primary evidence index, 2026-10-21

Each directory holds one workstream's repeatable artifacts for the
`ANALYSIS_ANSWER_MODE=llm_primary` release candidate. Paths are relative to this directory.
The release record stays `blocked`; this index is evidence, not approval.

| Directory | Scope |
| --- | --- |
| [registry](registry/) | Tool registry refactor and live smoke: one tool table drives the prompt, the `ToolCall` Literal and dispatch, with prompt/schema diffs and dispatch parity recorded. |
| [scoring](scoring/) | Honest scorer plus the 60-question held-out set, with the 70-question offline rescore and the live held-out baseline. |
| [factual-audit](factual-audit/) | Independent SQL audit of finished answers: 0 incorrect figures and 0 unsupported claims on the audited responses. |
| [ops](ops/) | Release-ops reconciliation: 25/25 preflight, isolated failure cases, record-scope forced failures, launch-mode consistency and the rollback drill. |
| [safety](safety/) | Typed pre-model refusal gate and adversarial harness: 21/21 pre-model cases refused, 0 false refusals on 66 benign archive questions. |
| [web](web/) | Live web refusal checks showing the truthful `refused` flag on validated declines with no fabricated data. |
| [reviewer](reviewer/) | Reviewer stability work: prompt v4, the deterministic number gate and offline replay rates for correct and wrong answers. |
| [latency](latency/) | Stage-level latency profile, token caps and prefetch cuts, with before/after p50 and p95 on the same 40 questions. |
| [prefetch](prefetch/) | Deterministic prefetch contract fixes, payload measurements and an offline audit of all 110 non-follow-up questions. |
| [correctness](correctness/) | Audited correctness defects and fixes: regular-season default, opponent phase breakdown, outcome subsets, extremes and fallback families. |
| [turning](turning/) | `get_game_flow` definitions and immutable flow claims, with live turning-point results against base. |
| [splits](splits/) | Independent SQL audit for `get_team_splits` answers, rebuilding each bucket from raw game rows. |
| [quarters](quarters/) | `get_period_scoring` measurement: base declines versus the merged head answering quarter questions. |
| [cost](cost/) | Cost diagnosis, ledger reconciliation, billed-failure settlement and corrected capacity at the $2 cutoff. |

The recap workstream is excluded. Its live measurement showed no gain over the base tree (6/20
base versus 6/20 and 4/20 head), and the analyst input budget is the binding constraint, so it was
not merged and has no directory here.

The passing preflight is `ops/preflight.json`. The two record-scope negative cases are
`ops/preflight-record-policy-fail.json` and `ops/preflight-policy-broken-fail.json`.
