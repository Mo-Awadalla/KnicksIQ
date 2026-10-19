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

## Why the model path fails

The data is not the cause. The restored release holds 46,500 play-by-play events, 816 period
scores, team shooting lines and starter flags. Main already answers quarter, bench, home/road and
opponent comparisons from them.

Twenty-one of 70 turns fail at the orchestrate stage with a `ValueError`. The harness records only
the exception type and stage, not the message. I read the message for one question, "What was the
Knicks record this season?", and it was `Model response changes a required sealed claim choice`.
Main sends the model `claims={slot: choice ordinal}` with `claim_uses` as a flat list of ten
`[claim index, precision]` pairs. Slot 1 must be ordinal 5 to 9. For that question DeepSeek v4.1
flash and v4 pro both answered `{"0": 0, "1": 0}`. Production uses
`ANALYST_PROVIDER_FORMAT=json_object`, so the provider never sees the enum that the payload schema
declares.

That is a confirmed example, not a proven cause for all 21. Other `ValueError` messages in main's
claim-selection code are possible for the rest, and I did not read them.

The same 21 questions, one run each unless noted:

| Model | Provider format | Past orchestrate | Validated end to end |
| --- | --- | ---: | ---: |
| deepseek-v4.1-flash (production) | json_object | 0 / 21 | 0 / 21 |
| deepseek-v4.1-flash | json_schema | 15 / 21 | 6 / 21 |
| deepseek-v4-pro-0813 | json_object | 9 / 21 | 9 / 21 |
| deepseek-v4-pro-0813 | json_schema | 21 / 21 | 16 / 21 |
| claude-haiku-5.5 | json_object | inconclusive, OpenRouter 404 on every request | |

Flash with json_object was also run twice over the 21 questions. All 42 runs failed to validate:
41 failed at orchestrate and one was rejected by the reviewer.

What the table supports:

- Enforcing the schema moves flash past the orchestrate step on 15 of 21 questions, against 9 for
  pro without it. End to end, flash with the schema validates fewer (6) than pro without it (9),
  because 9 flash answers are then rejected by the reviewer. The table does not rank the two
  changes.
- Each change helps on its own, and together they validate the most (16 of 21).
- Five questions still fail with both changes. I did not read their messages.

A scheme that asks the model for one short label per slot, not an ordinal into a shared list, might
reduce the confusion. This run does not test that.

## Questions the backend answers with a clarification

25 of 70 get "Which archived BOS game date should I use". These are real ambiguities (four to nine
games against each opponent) and are a product choice, not a data or model failure.
