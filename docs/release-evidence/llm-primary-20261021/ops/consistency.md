# Launch-configuration consistency check

Single authoritative statement:
`docs/release-checklist.md#intended-launch-configuration`.

Commands run from the repository root on 2026-10-21, with observed output:

```sh
grep -rnE "launch configuration is 10% shadow|deterministic answers delivered to users|starts in sampled LLM shadow mode|\\\$8 application cutoff|\\\$8 cutoff was not changed" docs/*.md render.yaml
# no matches

grep -rnE "launch.*shadow|shadow.*launch|deliver(ed|s|y).*deterministic" docs/*.md | grep -v release-evidence/
# docs/production-runbook.md:132:### Shadow: delivery stays deterministic, the loop is sampled
# docs/release-checklist.md:50:  shadow gate from the llm_primary launch check. ...
# docs/render-deploy.md:66:shadow gates in docs/evaluation.md pass and the owner approves the launch
```

All three remaining matches describe the pre-promotion shadow gate or the shadow rollback drill,
not the launch mode.

```sh
grep -rn '\$8' docs/*.md render.yaml
# docs/production-runbook.md:44: ... The cutoff in force at that time was $8;
```

The remaining $8 mention is historical. The current configured cutoff is $2 in `render.yaml` and
in `docs/production-runbook.md`.

Machine check after the docs update:

```sh
python3 tools/release/check_launch_mode_consistency.py \
  --json-out docs/release-evidence/llm-primary-20261021/ops/docs-consistency.json
# status: pass, mismatches: []
```

The script compares the mode, evidence-loop flag, shadow rate and cutoff in `render.yaml` with the
authoritative release-checklist section. It requires `docs/analyst-evidence-loop.md` to link that
section, name the launch mode and name all nine tools. Its output is `docs-consistency.json`.

Blueprint and validator facts:

- `render.yaml` was reviewed and left unchanged. No provable inconsistency was found in it: its
  values match `test_render_blueprint_enables_the_grounded_ai_configuration`, and the earlier
  contradiction was in the docs, not the blueprint.
- `render.yaml` sets `ANALYSIS_ANSWER_MODE=llm_primary`, `ANALYST_EVIDENCE_LOOP_ENABLED=true`,
  `ANALYSIS_SHADOW_SAMPLE_RATE=0.1`, and `OPENROUTER_MONTHLY_CUTOFF_USD=2`.
- `apps/api/app/services/release_evidence.py` still requires a release record with
  `configuration.answer_mode=shadow` and `shadow_sample_rate=0.1`. That is the pre-promotion gate,
  not the launch configuration. Separating the two is the owner decision in
  `docs/release-policy-proposal.md`; the record was not edited in this run.
- `docs/analyst-evidence-loop.md`, `docs/render-deploy.md`, `docs/evaluation.md`,
  `docs/production-runbook.md`, and `docs/release-policy-proposal.md` all link to the authoritative
  statement instead of declaring a different launch mode.
