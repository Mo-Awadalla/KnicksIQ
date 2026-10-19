# llm_primary live E2E on main, 2026-10-19

`tools/release/analyst_live_e2e.py` sends benchmark questions through the in-process API with the
real DeepSeek provider against a locally restored `2025-26.20260928.1` release. Qdrant is off.
Run it with a loaded release, Redis, and the production `AI_*` and `ANALYSIS_*` settings.

## Result on `14e5f11` (70 questions, one run, temperature 0)

| Outcome | Count |
| --- | ---: |
| Model answer validated | 11 |
| Model failed the claim-selection protocol, backend facts shown instead | 21 |
| Backend asked which game or scope | 25 |
| Backend declined unsupported question (correct) | 8 |
| Reviewer rejected, backend facts shown instead | 3 |
| Other | 2 |

`meets_expectation` is 19 of 70. It counts a backend fact shown after a model failure as not met,
because the user gets "Knicks wins: 69 over 101 archived games" and not a sentence. Decline and
clarification detection is a phrase match, and the expectations come from unreviewed draft labels.
Read `main-n70.responses.jsonl`.

## Why the model path fails: protocol and schema first, model second

The data is not the cause. The restored release holds 46,500 play-by-play events, 816 period
scores, team shooting lines and starter flags. Main already answers quarter, bench, home/road and
opponent comparisons from them.

All 21 orchestrate failures are the same error: `Model response changes a required sealed claim
choice`. Main sends the model `claims={slot: choice ordinal}` with `claim_uses` as a flat list of
ten `[claim index, precision]` pairs. For "What was the Knicks record this season?" slot 1 must
be ordinal 5 to 9. DeepSeek v4.1 flash answers `{"0": 0, "1": 0}` every time (same result on both
repeats), and so does v4 pro. Production uses `ANALYST_PROVIDER_FORMAT=json_object`, so the provider
never sees the enum that the schema in the payload declares.

The same 21 questions, one run per row:

| Model | Provider format | Validated |
| --- | --- | ---: |
| deepseek-v4.1-flash (production) | json_object | 0 / 21 (42 / 42 over two repeats) |
| deepseek-v4.1-flash | json_schema | 6 / 21 |
| deepseek-v4-pro-0813 | json_object | 9 / 21 |
| deepseek-v4-pro-0813 | json_schema | 16 / 21 |
| claude-haiku-5.5 | json_object | inconclusive, OpenRouter 404 for every request |

Both factors matter. Enforcing the schema helps flash more than a bigger model does. Together they
fix most failures. The remaining five still fail, so the protocol itself is brittle. A scheme that
asks the model for one short label per slot, not an ordinal into a shared list, would remove the
confusion. This run does not test that.

## Questions the backend answers with a clarification

25 of 70 get "Which archived BOS game date should I use". These are real ambiguities (four to nine
games against each opponent) and are a product choice, not a data or model failure.
