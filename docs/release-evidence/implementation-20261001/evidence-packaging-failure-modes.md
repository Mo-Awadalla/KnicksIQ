# Evidence packaging: failures written before the fix

These HTTP regressions use the public analysis route, real SQL, a disposable real
Redis process, and a synthetic zero-cost model adapter. They make no provider
requests. Save the HTTP response, replay, internal search/tool receipts, exact
model inputs, and budget balance before checking assertions.

| Failure | Required behavior | Regression |
| --- | --- | --- |
| A nonempty tool result suppresses already-issued canonical discovery sources. | Preserve current-turn discovery alongside result sources, including when a whole result source is too large to send. | `test_current_discovery_survives_oversized_result_http` |
| A source appears in both result and discovery. | Send the whole record once; current result priority precedes discovery rank. | Same HTTP test; a controlled result seam reuses a real discovered source. |
| Merging every hydrated source revives an unrelated prior game. | Merge current results and current canonical discovery only; do not add unrelated registry evidence. | Same HTTP test; a controlled prior registry source is deliberately present. |
| Packing clips source text, claim values, or numerical records to fit. | Include or omit whole immutable records; keep the existing input/evidence caps. | Exact captured-record equality and byte-cap assertions in the same test. |
| A required narrative claim cannot fit, yet an empty payload starts model calls. | Return the complete verified backend narrative before any provider dispatch; preserve both tied Boston runs. | `test_oversized_boston_narrative_falls_back_before_dispatch_http` |
| Replay repeats discovery, tools, or model calls. | Return the committed response exactly with zero extra work and unchanged budget. | Both new HTTP tests retain first/replay captures and dispatch counts. |
| A budget guard disables small valid narratives or relaxes review. | Small complete narratives still pass the normal whole-answer review; incomplete stories fail it. | Existing `test_primary_review_requires_every_selected_game` in `test_canonical_narrative_http.py`. |
| Complete tied games/runs are silently truncated. | Preserve all selected games, all tied maxima, and all canonical event references even when fallback text exceeds the model answer cap. | Existing archive narrative, run-boundary, and large tied-game HTTP regressions in `test_canonical_narrative_http.py`, plus both Boston runs in the new test. |

The oversized-result seam changes only the synthetic tool result delivered to
the real orchestration loop. Canonical discovery still queries SQL and records
its real ranking; it is not mocked. The Boston scenario uses the tracked
synthetic archive by default. Set `KNICKSIQ_APPROVED_BUNDLE` to the approved
archive to repeat it against the pinned approved SHA without changing the test.

Run from the repository root, with its Python dependencies and `redis-server`:

```sh
PYTHONPATH=apps/api:apps/worker:apps/mcp:packages/basketball-core/src \
KNICKSIQ_PAYLOAD_ARTIFACT_DIR=release-artifacts/evidence-packaging/run-001 \
python -m pytest apps/api/app/tests/test_analyst_payload_http.py \
  apps/api/app/tests/test_canonical_narrative_http.py -q \
  --junitxml=release-artifacts/evidence-packaging/run-001.junit.xml
```

Use a fresh artifact directory per run: receipts are created exclusively rather
than overwritten. These protocol regressions establish evidence transport and
fallback behavior; they do not establish live-model semantic quality or frozen
release-gate passage.

## Verification on 2026-10-02

The new regressions failed before the production patch: the tool-followup prompt
retained only one compact source, and Boston used three model calls despite its
required narrative claim being absent from every input. After the patch, the
same source fixture retained four complete records in priority order. Its largest
model input was 7,977 UTF-8 bytes, within the unchanged 8,000-byte conservative
bound. The Boston response preserved both tied 12–0 runs with zero model calls.

- Both new HTTP regressions pass against the synthetic fixture and the approved
  archive selected through `KNICKSIQ_APPROVED_BUNDLE`.
- All eight packaging and existing narrative HTTP scenarios pass, including
  complete/incomplete model narratives and large tied selections.
- The full backend command passes: 622 tests. Ruff lint/format and Pyright pass.
- The rebuilt local Docker API passes `verify_local_staging.py`, including
  committed turns, exact replay, conflicts, and the missing-game clarification.

The full Boston claim remains too large for the general model prompt. This fix
delivers its complete verified backend answer immediately; it does not claim
that Boston wording passed model review. No input/output ceilings, complete-value
contracts, tie requirements, or review rules were relaxed.
