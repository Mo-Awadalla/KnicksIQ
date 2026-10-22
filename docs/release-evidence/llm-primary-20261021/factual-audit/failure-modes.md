# Failure modes of the 2026-10-18/21 claim audit

Written before the replacement audit code. The old audit is
`git show 5b585e6:docs/release-evidence/llm-primary-20261021/factual-audit/audit.py`,
lines 146-152. It computes a claim only when the spec has an `extract` callable;
otherwise it compares the spec's `claimed` constant with SQL and never looks at
today's answer.

1. **Number in the answer is never checked.** A spec lists only some claims. In
   `date_range_last_n-001` the audit checks wins (4), losses (1), points (522)
   and margin (+12); 522 and +12 are not in the trial-1 answer, while the five
   game scores, the 4-1 record, the dates and the opponents are not checked.
   "0 numeric failures" therefore means only "0 failures among the claims that
   happened to be listed".
2. **Number is checked against a stale constant.** A claim without `extract`
   carries a literal `claimed` value copied from an older response. The verdict
   says the answer was audited, but the answer was never read.
3. **Wrong subject.** Team total checked against a player line, NYK total against
   the opponent, one player against another, or a team-stat sum that forgot
   `team_id = 'NYK'` and double counted both teams.
4. **Wrong phase.** Regular season against playoffs against all 101 archived
   games. The app defaults to regular season, but "the archive" and "all games"
   answers use 101 games, and last-N questions often mean the playoff tail.
5. **Wrong window.** Last N against whole season, first N against last N, an
   inclusive date range with an off-by-one endpoint, a month filter that includes
   a game outside the month, or "last 10" applied after a regular-season filter
   instead of across all season types.
6. **Wrong location.** Home against road, or home/road ignored in a split.
   `comparisons-001` trial 2 publishes both splits; a single SQL total would
   validate neither.
7. **Wrong opponent.** `opponent_id` omitted, an alias not resolved (Celts,
   Raps, C's, ATL), or Boston games counted as Toronto games.
8. **Unit and scale mismatch.** Total points against points per game, cumulative
   margin against average margin, points against wins, a percentage against a
   count, `9,549` parsed as 9 or 9549, `+11.9` parsed as 11.9 without its sign.
9. **Rounding not defined.** One-decimal displays (`114.1`, `32.6`, `9.75`),
   two-decimal displays (`116.45`, `6.33`), SQL `round` values and Python float
   formatting disagree at the half. A tolerance must depend on the number of
   displayed decimals, not a single global epsilon.
10. **Date components tokenised as independent numbers.** `2025-12-21` can be
    read as 2025, -12 and 21, or as the pair 2025-12. The year, month, day and
    date-range endpoints must each be verified against `games.game_date`.
11. **Score orientation and type.** `105-95` can be NYK-opponent, opponent-NYK,
    a win-loss record, a run, or a scoreboard snapshot. The same digits pass a
    different check if type is inferred from the number alone.
12. **Scoreboard snapshot not checked.** A play-by-play sentence quotes a score
    at a clock (`22-30 at Q1 00:17`). Checking only the run length ignores
    whether the score, period and clock existed at that event.
13. **Run is not consecutive.** A "17-0 run" verified as "NYK scored 17 more
    than BOS over some interval" can include opponent scores. Consecutive
    scoring plays must be used, and the opening run versus a period-filtered run
    changes the answer.
14. **Per-game list unverified.** A list of five finals or five player scoring
    games can be checked as an aggregate but not as a set; a wrong single value
    then hides inside a correct sum.
15. **Arithmetic identity unchecked.** `30-10` with `40 games`, `53-29` with
    `82 games`, `2,375 - 2,316 = 59`, or `+238 - +68 = 170` can each be wrong
    while every isolated number is right.
16. **Decline treated as pass.** The old audit's `DECLINE_MISSED_ANSWER` is not a
    correctness pass, and a forbidden-term match can force INCORRECT on an
    otherwise correct decline. Neither outcome audits the numbers in the answer.
17. **Static findings and static right answers.** `findings`, `flags` and
    `right_answer` are copied from the spec and are annotations of the
    2026-10-18 response, not measurements of the current one.
18. **Citation values trusted.** `metadata.claim.value` is supplied by the
    system under test. It is a hypothesis for the audit, never the oracle; every
    cited value must be recomputed from the raw tables.
19. **Coverage is not reported.** A response with one checked claim and ten
    unchecked numbers looks the same as a fully checked response.
20. **No denominator.** "0 failed" without "N found, N verified, N wrong,
    N unverified" cannot distinguish a clean answer from an unaudited one.

The replacement audit extracts every numeric atom from each answer, assigns a
subject, phase, window, location, opponent and type from the sentence, recomputes
the expected value from raw tables with its own SQL, and records one of
`verified`, `wrong` or `unverified` per atom. Unverified is never a pass.
