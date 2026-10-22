# llm_primary evidence index, 2026-10-21

Each directory holds one workstream's repeatable artifacts for the
`ANALYSIS_ANSWER_MODE=llm_primary` release candidate. Paths are relative to this directory.
The release record stays `blocked`; this index is evidence, not approval.

Start with [final](final/). It holds the shipped configuration's results and supersedes the
latency and capacity figures in `latency/` and `cost/`, which were measured with the older
8,000-byte input budget.

| Directory | Scope |
| --- | --- |
| [registry](registry/) | Tool registry refactor and live smoke: one tool table drives the prompt, the `ToolCall` Literal and dispatch, with prompt/schema diffs and dispatch parity recorded. |
| [scoring](scoring/) | Honest scorer plus the 60-question held-out set, with the 70-question offline rescore and the live held-out baseline. |
| [factual-audit](factual-audit/) | SQL audit harness. The original audit of the 2026-10-18 run (9 incorrect, 25/37 old passes correct) is pinned at commit `5ed8333`; the files at this path were later regenerated for the correctness acceptance run. Claims without an extractor are checked against fixed values from the original answers, so "0 numeric failures" does not mean every delivered number was recomputed. |
| [ops](ops/) | Release-ops reconciliation: 25/25 preflight, isolated failure cases, record-scope forced failures, launch-mode consistency and the rollback drill. |
| [safety](safety/) | Typed pre-model refusal gate and adversarial harness. 21/21 and 0/66 are offline routing checks of the gate; the live harness covers a subset of decline shapes, and end-to-end unsupported passes are 15/20 in `final/`. |
| [web](web/) | Live web refusal checks showing the truthful `refused` flag on validated declines with no fabricated data. |
| [reviewer](reviewer/) | Reviewer stability work: prompt v4, the deterministic number gate and offline replay rates for correct and wrong answers. |
| [latency](latency/) | Stage-level latency profile, token caps and prefetch cuts, with before/after p50 and p95 on the same 40 questions. |
| [prefetch](prefetch/) | Deterministic prefetch contract fixes, payload measurements and an offline audit of all 110 non-follow-up questions. |
| [correctness](correctness/) | Audited correctness defects and fixes: regular-season default, opponent phase breakdown, outcome subsets, extremes and fallback families. |
| [turning](turning/) | `get_game_flow` definitions and immutable flow claims, with live turning-point results against base. |
| [splits](splits/) | Independent SQL audit for `get_team_splits` answers, rebuilding each bucket from raw game rows. |
| [quarters](quarters/) | `get_period_scoring` measurement: base declines versus the merged head answering quarter questions. |
| [cost](cost/) | Cost diagnosis, ledger reconciliation and billed-failure settlement. Its capacity figure predates the 16,000-byte budget; see `final/`. |
| [w3-routing](w3-routing/) | Settings-driven OpenRouter upstream routing, a per-upstream table from 1,269 recorded calls, the call-count analysis, and the pending live before/after arms. Live blocked by provider credits. |
| [final](final/) | Input budget A/B (8,000 vs 16,000 bytes, 70 questions x 2 trials), factual audit of both trials, one held-out run, preflight. Shipped config: p50 3,312 ms, p95 7,640 ms, about 1,009 questions per month at $2. |
| [final/relabel](final/relabel/) | Offline rescore of both held-out runs under phase-policy labels: baseline 4/60, final 29/60. This is a rescore of observed responses, not a fresh run, and `date_range_last_n-007` later drove a code fix, so the held-out set is no longer untouched. |
| [final/gate](final/gate/) | Saved backend and web suite output for the integration head. |

The recap workstream is excluded. Its live measurement showed no gain over the base tree (6/20
base versus 6/20 and 4/20 head), and the analyst input budget is the binding constraint, so it was
not merged and has no directory here.

The passing preflight on the integration head is `ops/preflight-1688ea8.json`. The two
record-scope negative cases are `ops/preflight-record-policy-fail.json` and
`ops/preflight-policy-broken-fail.json`. In `reviewer/`, `mutations.json` supersedes the mutation
totals embedded in `replay.json`. Its head 0/64 counts deterministic and structure rejections of
preselected mutations; the model reviewer was never called on them, so the reviewer's
false-acceptance rate is unmeasured. `gate-mutations.md` has the unselected gate result.
