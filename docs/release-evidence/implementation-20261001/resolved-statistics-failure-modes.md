# Resolved statistics: failure modes recorded before the fix

Fresh exact_statistics-002 asked for a game/date range instead of the available
11,750-point total. The writer had a resolved points scope, all 101 archive games
and two tool rounds available, but zero claims/evidence. The reviewer received no
scope or facts and accepted both spans as conversational. The record and player
average exceptions already passed the same live run; the common preparation rule
was missing for other deterministic native statistics.

Socket HTTP/SQL/Redis regressions must cover these failure modes before code changes:

- A resolved team total, average, win count or game count starts with empty facts.
- An explicit player total starts empty, despite available appearance rows.
- A model omits available requested facts and validates an unnecessary clarification.
- Every declared native population, metric, value, citation and source must survive.
- Broad preparation turns a player quantity question into the default average.
- Unsupported team metrics fall through to unrelated wins/losses.
- Arbitrary comparisons lose their baseline because a single population is prefetched.
- Team All-Star comparisons borrow an exception implemented only for players.
- Comparison/better wording or mixed period/month scopes collapse distinct populations.
- Grouped rebounds and total points allowed become unrelated records or an average.
- Grouped explicit totals become per-game averages from the comparison dispatcher.
- Difference/differ wording bypasses comparison detection and loses a player baseline.
- Ambiguous subjects, unavailable seasons and discovery are forced into statistics.
- Tool/time/model/budget caps change, or replay repeats provider work.

Reuse existing native tool dispatch and completeness policy. Add one eligibility
decision shared by preparation and required-claim projection. Genuine unavailable
data may retain its normal response; a complete supported statistic may not become
a fresh clarification. Test both synthetic CI and SHA-pinned approved archives;
retain HTTP responses, exact inputs/schemas, traces, replay and ledger receipts.
