# Release verification

Use the [versioned release record](release-evidence/release-record.json) and
[generated owner review view](release-evidence/release-record.md) as the source of
release status. Historical local preflight results do not establish current deployment readiness.

Generate the view and run the fail-closed gate from the repository root:

```sh
uv run --package knicksiq-api python -m app.services.release_evidence docs/release-evidence/release-record.json --readiness --render
```

## Intended launch configuration

This section is the single authoritative statement of the intended launch. Other documents link
here instead of restating the mode.

The owner removed the required shadow stage on 2026-10-20; launch goes straight to
`llm_primary`. The launch serves `ANALYSIS_ANSWER_MODE=llm_primary` with
`ANALYST_EVIDENCE_LOOP_ENABLED=true`, `ANALYSIS_SHADOW_SAMPLE_RATE=0.1` retained only for
explicit shadow drills (primary turns are never sampled), and a configured Sentry DSN. The
approved record's pending `openrouter_monthly_cutoff_usd` target is $20, applied only during an
explicitly authorized deployment; `render.yaml` still declares $2 until that authorized change.
Models run on the owner's OpenCode Go subscription: `AI_PROVIDER=opencode-go`,
`AI_CHAT_MODEL=deepseek-v4.1-flash` writes over Chat Completions, and
`ANALYST_REVIEW_MODEL=gpt-6-luna` reviews over the Responses API
(`AI_MODEL_PROTOCOLS={"gpt-6-luna":"responses"}`). `AI_MODEL_PRICES` prices each call because Go
reports no per-call cost, and `OPENROUTER_ALLOWED_MODELS` contains exactly the writer and the
reviewer. Users receive validated evidence-loop answers. Any provider, budget, validation or
optional-dependency failure degrades to deterministic cited facts, and a suspended Go account
needs no action. Switching back to OpenRouter is the configuration change in
[the runbook](production-runbook.md#switch-back-to-openrouter). The mode, evidence loop, provider
and model values are declared by `render.yaml` and asserted by
`test_render_blueprint_enables_the_grounded_ai_configuration`; the blueprint cutoff remains $2
until the authorized change.

Readiness requires no shadow configuration, `shadow_dependencies` or `shadow_evaluation`
evidence. The record's `configuration` block is the historical tested-commit configuration, not
the launch target. Readiness does not supply final launch approval or the owner-controlled record
digest required by the deployment coordinator.

### Analyst behavior at launch

The evidence loop exposes eleven registered tools: `get_player_stats`, `get_team_stats`,
`compare_windows`, `discover_facts`, `search_archive`, `get_evidence`, `find_player_games`,
`get_game_narrative`, `get_game_flow`, `get_team_splits` and `get_period_scoring`. Quarter, period,
play-by-play and split questions are answerable. Season-level records and stats include all
archived phases unless the question or inherited scope restricts them; answers state the scope. Typed
pre-model refusals cover instruction override, wagering and out-of-archive dates. Other unsupported
wording reaches the analyst, which declines or explains coverage through the `refused` flag. Prompt
`analyst-balanced-v6` and validator `whole-answer-v3` run the deterministic number gate. Reasoning
effort is `none` by default, token caps are enforced and deterministic prefetch is enabled. As a
historical OpenRouter measurement at the 16,000-byte input budget, the $2 cutoff supported about
1,009 questions per month on the 70-question mix and about 750 on the held-out rate, at mean costs
of $0.001981 and $0.002668 per question, respectively; measured p95 latency was 7,640 ms on 140
questions. The owner relaxed the latency gate from four seconds to 15 seconds on 2026-10-19, so
that measurement meets the current local bound. Capacity was route dependent. OpenCode Go latency
and capacity are not yet measured. Full behavior is in
[the analyst implementation](analyst-evidence-loop.md). Evidence is in the
[final measurement](release-evidence/llm-primary-20261021/final/README.md).

Owner-only decisions:

- Authorize real-provider spend and the approved monthly cutoff. The blueprint currently declares
  $2; the approved record's $20 target applies only during an explicitly authorized deployment.
- Approve any exception to a failed quantitative release gate.
- Approve evaluation labels, the scoring rubric, the exact frozen evaluation contract hash, the
  release record digest and any exception.
- Authorize deploy and activation, and any production settings change, including a rollback
  drill against production.

Everything else in this document is agent-verifiable and does not require owner sign-off.
Automatic Render deployments stay disabled. Both NOW workstreams block deployment. NEXT and LATER
are outside this release gate and hosting remains unchanged.

Agents verify all reports against canonical evidence. The owner approves the corrected template,
exceptions and final hash-bound audit summary rather than each write-up. A reviewed flag alone
is insufficient. Evaluation labels require owner approval in batches. Do not fill approvals on
the owner's behalf. The tested commit, audit/evaluation/data/bundle hashes, environment checks,
deployment IDs and rollback snapshot belong in the record.

Application deployment rebuilds the exact tested Git commit on existing Render services;
these rebuilt artifacts are not asserted identical to CI artifacts. Capture both existing
application deployments, active data version and alias mapping before promotion. Smoke-test
both resulting services. Restore every changed component on failure; coordinated restoration
is not atomic. Stop promotion and alert the owner if any restoration fails.
