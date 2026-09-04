# Report integrity audit

Audit SHA-256 (canonical JSON): `1027834ac9d07dfad7e0b4640a25aff731f1d51756d67efa0588f98523cbd1ad`

Local candidate only; active archive identity and owner approval remain unverified.

{"content_hashes_passed": 101, "cross_period_reports": 40, "passed": 0, "player_lines_passed": 303, "reports": 101, "score_summaries_passed": 101, "unresolved": 101}

Agents verify every report; unresolved checks block approval. Owner approves the corrected template, all exceptions and final hash-bound audit summary. reviewed=true alone is not approval.

Retain the existing selected interval only when canonical cumulative event scores independently prove its points. Identify both periods explicitly. These are selected scoring intervals, not causal turning points or necessarily the best/worst interval.

Start is inclusive: baseline is the score immediately before the first scoring event at the stated start clock. End is inclusive: last event at the end clock. Resolve the end period by chronology and the claimed score difference; require a unique interval.

| Game | Result | Cross-period | Exceptions |
|---|---|---|---|
| 0022500003 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500018 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500108 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500125 | unresolved | False | turning_point:nonmonotonic_canonical_score, best_stretch:nonmonotonic_canonical_score, worst_stretch:nonmonotonic_canonical_score |
| 0022500023 | unresolved | True | turning_point:missing_scoring_start, best_stretch:run_points_or_boundary_mismatch, worst_stretch:missing_scoring_start |
| 0022500153 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500159 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500175 | unresolved | False | best_stretch:run_points_or_boundary_mismatch |
| 0022500192 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500208 | unresolved | False | best_stretch:run_points_or_boundary_mismatch |
| 0022500215 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500039 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500244 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0022500262 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500269 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500285 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500061 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500074 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500303 | unresolved | False | best_stretch:run_points_or_boundary_mismatch |
| 0022500320 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500328 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500343 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500357 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501202 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501229 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0022500372 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500382 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500398 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500416 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500009 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500435 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500454 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500467 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500479 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500487 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500502 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500522 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500538 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500551 | unresolved | True | turning_point:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500576 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0022500584 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500596 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500016 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500622 | unresolved | False | turning_point:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500643 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500665 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0022500675 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500690 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500708 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0022500718 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500726 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500742 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0022500757 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0022500771 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500780 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0022500796 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500816 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0022500825 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500835 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0022500860 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500868 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500887 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500893 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500911 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500922 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500935 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500949 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500962 | unresolved | True | best_stretch:run_points_or_boundary_mismatch |
| 0022500981 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022500994 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501016 | unresolved | False | best_stretch:run_points_or_boundary_mismatch |
| 0022501034 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501048 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501063 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0022501089 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501102 | unresolved | False | turning_point:unsupported_run_format, best_stretch:unsupported_run_format, worst_stretch:unsupported_format |
| 0022501003 | unresolved | False | turning_point:unsupported_run_format, best_stretch:unsupported_run_format, worst_stretch:unsupported_format |
| 0022501123 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501143 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501168 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501176 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0022501190 | unresolved | True | turning_point:missing_scoring_start, best_stretch:unsupported_run_format, worst_stretch:missing_scoring_start |
| 0042500121 | unresolved | False | turning_point:missing_scoring_start, best_stretch:run_points_or_boundary_mismatch, worst_stretch:missing_scoring_start |
| 0042500122 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500123 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500124 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500125 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500126 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500211 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500212 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:unsupported_run_format, worst_stretch:run_points_or_boundary_mismatch |
| 0042500213 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0042500214 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:unsupported_format |
| 0042500301 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500302 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500303 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500304 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500401 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500402 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500403 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500404 | unresolved | False | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
| 0042500405 | unresolved | True | turning_point:run_points_or_boundary_mismatch, best_stretch:run_points_or_boundary_mismatch, worst_stretch:run_points_or_boundary_mismatch |
