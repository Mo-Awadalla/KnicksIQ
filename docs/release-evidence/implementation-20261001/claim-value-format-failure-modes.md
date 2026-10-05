# Claim value formatting: failure matrix before implementation

The retained free-model run copied a claim's prose statement into
`displayed_value`, despite the authoritative numeric value being present. The
same error survived repair because its guidance identified neither the field
nor the required typed representation. Exact-value validation correctly rejected
both answers; it must continue doing so.

| Failure | Required behavior | HTTP regression |
| --- | --- | --- |
| Initial answer supplies the backend statement as the displayed value. | Repair receives complete copyable `claim_uses` templates and explicit typed-value guidance; a corrected value must pass independent whole-answer review before delivery. | `repair` |
| Repair repeats the prose value despite guidance. | Reject it and return verified fallback; never coerce text to a number or accept it because its prose contains the right number. | `stubborn-prose` |
| Repair supplies a different numeric value. | Reject it and return verified fallback. | `wrong-number` |
| A correct numeric value accompanies unsupported causal wording. | Whole-answer review rejects it, including after repair; correct formatting alone does not authorize delivery. | `unsupported-wording` |
| A valid aggregate cites a complete calculation receipt registered by the backend but absent from the abbreviated tool evidence list. | Resolve only retained claims' exact supporting IDs from the registry and pack their whole receipts ahead of optional tool/discovery sources; both writer and reviewer must receive the cited receipt. Keep review reference validation strict. | `test_calculation_receipt_reaches_writer_and_reviewer_http` |
| A supported review repeats so much evidence in its explanation that `reason` exceeds the existing 500-character schema bound. | Explicitly instruct the reviewer to keep every reason brief and within 500 characters, placing IDs in their dedicated fields. Preserve the compact schema's bound for both assertion and follow-up reasons. | `test_review_reason_bounds_http[compliant]` |
| A reviewer ignores the bound for an assertion or follow-up reason, including after repair. | Reject the malformed review and retain verified fallback; never truncate an explanation or silently accept a schema violation. | `test_review_reason_bounds_http[oversized-assertion]` and `[oversized-follow-up]` |
| Templates are detached from selected claims, incomplete, or alter values. | Writer/repair templates correspond exactly to retained complete claim records, preserving JSON types and object values; reviewer inputs have no writer templates. | Every captured input in the new HTTP module. |
| Additional guidance silently exceeds packing budgets. | Count templates alongside their whole claims under the existing 8,000 input-byte and 6,000 evidence-byte conservative bounds; omit whole groups rather than clipping values. | Every captured input plus the existing payload and narrative HTTP regressions. |
| Formatting change disables legitimate numeric rounding or short complete narratives. | Preserve explicit `decimal_places` validation and existing complete narrative review. | Existing analyst contract and canonical narrative tests. |
| Replay repeats work or reservations retain known zero-cost calls. | Exact committed response, zero replay model/search/tool work, unchanged isolated Redis budget. | Every new case. |

`test_analyst_value_format_http.py` uses the public analysis HTTP route, real SQL,
and a disposable real Redis process. The synthetic adapter reproduces the saved
mistake and responds to the new protocol; it never contacts a provider. Each
case saves complete requests, responses, replay receipts, search/tool capture,
model inputs, and its known-zero-cost accounting before assertions.

The calculation-receipt regression uses the tracked synthetic archive and
Brunson's last five appearances, producing the real aggregate receipt rather
than an injected source. Set `KNICKSIQ_APPROVED_BUNDLE` to repeat it against the
approved archive. Its adapter reproduces the live reviewer's citation of the
claim's supporting calculation ID. The source-union regression also continues
to require retained canonical discovery, duplicate elimination, whole records,
and exclusion of unrelated prior-game evidence after supporting sources take
priority.

The reason-length regression reproduces a subsequent live failure after typed
values and the calculation receipt were correct. The compact reviewer schema
already contains `maxLength: 500`; the missing part is explicit reviewer prose
guidance. Synthetic responses cover a compliant short reason and ignored limits
on both bounded reason fields, with actual HTTP repair and replay behavior.

Run with a fresh output directory from the repository root:

```sh
PYTHONPATH=apps/api:apps/worker:apps/mcp:packages/basketball-core/src \
KNICKSIQ_PAYLOAD_ARTIFACT_DIR=release-artifacts/claim-value-format/run-001 \
python -m pytest apps/api/app/tests/test_analyst_value_format_http.py -q \
  -o junit_family=xunit1 \
  --junitxml=release-artifacts/claim-value-format/run-001.junit.xml
```

These tests establish transport, repair, validation, and replay behavior. They
do not establish live-model semantic quality; retain that distinction when
reporting synthetic protocol results.

## Diagnosis and implemented behavior

The captured provider responses reproduced the first failure: replacing only
the prose `displayed_value` with the immutable numeric `32.6` made structural
validation pass. Writer and repair inputs now contain exact typed `claim_uses`
templates, admitted atomically with their complete claims and counted within
the existing limits. The prompt version is `analyst-balanced-v3`.

The first live rerun returned the correct numeric value but exposed a second
failure. Its independent reviewer cited the aggregate's registered calculation
receipt, which was missing from the packed evidence. Packing now resolves only
the retained claims' supporting IDs from the active-release registry before
prioritizing whole evidence records. The 601-byte Brunson receipt reaches both
writer and reviewer; validation rules and input limits are unchanged.

The next live run confirmed both fixes but returned a 585-character reviewer
reason, exceeding the unchanged 500-character contract. The compact schema
already contained that limit. The reviewer now receives explicit instructions
to use one short sentence within the limit and keep supporting IDs in their
dedicated fields. Oversized assertion and follow-up reasons remain rejected.

Each regression failed before its corresponding production change. The final
43 targeted checks and all 630 backend tests pass. Ruff lint/format, Pyright,
and `git diff --check` pass.
The local Docker API also passes the real HTTP replay verifier. Captures,
responses, accounting receipts, and JUnit reports are retained under
`release-artifacts/claim-value-format-20261002/`, with durable copies under
`release-artifacts/docker-staging-20261002/claim-value-format-20261002/`.

The final bounded Docker smoke against OpenRouter's free NVIDIA model passes.
Brunson's answer is "Jalen Brunson averaged 32.6 points per game over his last
5 games." The public HTTP route reports `llm_validated=true`; the independent
review covers the exact entire answer, cites its complete calculation receipt,
and supplies a 197-character explanation. The three provider calls report and
settle zero cost. Missing-game clarification and Boston's two tied 12–0 runs
remain correct without model calls. All three exact replays make zero further
model calls.

The isolated Redis ledger remains `0.0722179`, including the earlier conservative
hold for a response rejected before settlement; no balance was reset or reduced
to erase that uncertainty. Provider keys were removed after the run. This smoke
verifies these three cases on the approved archive; it does not establish dense
vector retrieval quality or satisfy the complete frozen release workload.
