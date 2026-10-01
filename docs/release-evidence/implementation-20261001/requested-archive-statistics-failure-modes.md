# Requested archive statistic failures

Written before the HTTP specification and changes below.

- An average, margin, allowed-points, count or extreme request returns unrelated
  wins/losses/points totals. Threshold boundaries are reversed or approximate.
- Total player points returns an average; percentage uses an average of game
  percentages rather than summed makes divided by summed attempts; starts
  counts appearances instead of canonical starter flags.
- A unique Knicks first name is missed and an unrelated ordinary word is fuzzy
  matched to an opponent player (Mikal resolves from "well" to Wells).
- First/final/last-N windows use the wrong end of the archive, or last-N player
  games selects team games before observed appearances.
- A model tool replaces an explicit requested metric or aggregation.
- Claims lose their actual population, denominator, raw source fields or ties.
- Existing undefined measures acquire defaults; missing game references stop
  asking for the identified game in the preceding ten messages.
- HTTP verification creates a paid adapter or uses shared production state.

The E2E loads the unchanged approved archive once, independently calculates all
expected values from its raw rows, retains every request/response/replay and
checks typed claims and complete underlying source receipts. These are local
engineering checks against proposed expectations, not approved release gold.
