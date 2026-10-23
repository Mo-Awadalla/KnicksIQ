# Reviewer model decision

Both arms replayed the same 24 recorded answers (14 correct, 3 wrong with review payloads; 7 missed excluded) with only `ANALYST_REVIEW_MODEL` changed. Wrong-answer cases are 21 mutations, 15 of which pass the deterministic gate and reach the reviewer; controls are the 14 unmutated correct answers. Intervals are Wilson 95%.

| model | wrong accepted (mutated + recorded) | controls accepted | false rejects (correct) | true rejects (wrong) | malformed reviews | p50 / p95 review latency | cost per review |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-6-luna | 3/39 (0.077) [0.026, 0.203] (mutated 0/30; recorded 3/9) | 26/28 (0.929) [0.773, 0.980] | 4/42 (0.095) [0.038, 0.221] | 6/9 (0.667) [0.354, 0.879] | 0/109 (0.000) [0.000, 0.034] | 2829 / 4898 ms | $0.000310 |
| deepseek-v4.1-flash | 7/39 (0.179) [0.090, 0.327] (mutated 0/30; recorded 7/9) | 28/28 (1.000) [0.879, 1.000] | 0/42 (0.000) [0.000, 0.084] | 2/9 (0.222) [0.063, 0.547] | 0/109 (0.000) [0.000, 0.034] | 2556 / 4750 ms | $0.000924 |

Recommendation by the rule (fewest wrong acceptances, then fewest false rejects of correct answers, then latency): **gpt-6-luna**.

Wrong accepted counts every observation of a wrong answer that passed the pipeline: gate-passing mutations of correct answers plus recorded wrong writer answers replayed from `head-units.jsonl`. The rule applies to that total because the replay arm also measures wrong acceptances. In this run no model accepted a gate-passing mutation, so the difference comes entirely from recorded wrong answers. False rejects count trials where a correct recorded answer was rejected (reviewer, deterministic or structure). Malformed reviews count provider replies that failed JSON validation across both arms, including retried first attempts; the denominator is provider calls. Latency is the provider call from the false-acceptance arm; replay-arm latency and every call's model, protocol and token cap are in `decision.json`.

