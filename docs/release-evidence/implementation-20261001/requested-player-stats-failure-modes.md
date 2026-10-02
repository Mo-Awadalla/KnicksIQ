# Requested player statistic failure modes

Written before the HTTP specification and implementation. Retained roster HTTP
responses show three distinct wrong answers: rebounding resolves to points,
double-doubles resolve to points per appearance, and an All-Star comparison
uses one full-season average.

- A metric inflection such as rebounding, scoring or assisting defaults to a
  different statistic. Explicit requested metrics take precedence over defaults.
- Double-doubles count the wrong categories, omit triple-doubles, count DNPs or
  use a rate when the question requests a count. Count observed appearances
  with at least ten in two of points, rebounds, assists, steals and blocks.
- A model tool overrides the user's explicit statistic and its unrelated result
  survives fallback. Reject mismatched explicit metrics before calculation.
- Before/after All-Star populations overlap, include another season or omit the
  postseason without a requested regular-season filter. Retain both complete
  scoped populations, their sample sizes, dates, source receipts and definitions.
- An All-Star date is guessed for an unsupported season. The verified 2025-26
  boundary is February 15, 2026, from https://www.nba.com/allstar/2026; other
  seasons need an explicit independently supported boundary.
- The complete comparison is lost because fallback expects only one full-window
  average. A combined claim must retain both source populations and baselines.
- A missing source row is treated as an observed zero or an injured-player fact.
  Describe observed archive coverage and retain missing-row limitations.
- Evaluation questions, gold labels, budget journals or paid providers are used
  to obtain fixture answers. Expected values are independently calculated from
  immutable raw bundle rows; retain actual HTTP responses and replay receipts.

These HTTP checks establish deterministic metric/population behavior, not
approved evaluation gold, provider quality, remote dependency or readiness proof.
