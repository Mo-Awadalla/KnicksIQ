# Corrected report verification

{"content_hashes_passed": 101, "cross_period_reports": 0, "passed": 101, "player_lines_passed": 303, "reports": 101, "score_summaries_passed": 101, "unresolved": 0}

Canonical basketball data SHA-256: `b2ad21c69175600c3192ef6133f8c11fd63890609a8204f92508a5fb04d05170`

Canonical basketball rows are unchanged. All 101 report drafts remain unreviewed.

Enumerate same-period intervals lasting at most 180 seconds. Include all events at each endpoint clock, including every same-clock free throw. A candidate begins at a clock with positive scoring and contains no backward scoreboard correction. Select the greatest NYK margin gain for best_stretch and the greatest opponent margin gain for worst_stretch; tie-break by own points, shortest duration, earliest sequence. turning_point displays the larger of those two margin gains, with NYK winning a tie. These are selected scoring intervals, without a claim of causality or an unrestricted game-wide best/worst interval.

Cached 0-0 rows are missing-score sentinels and carry the prior observed score. A backward nonzero score is retained as the new canonical baseline. No selected interval crosses that correction; all excluded corrections are listed for review.

Games with excluded scoreboard corrections: 1.

Every replaced claim and exact sequence-level evidence is in audit.json. The proposal is not an approved production release.

Owner review requires the corrected template, correction exceptions and hash-bound final audit summary. Active archive identity remains a separate release check.
