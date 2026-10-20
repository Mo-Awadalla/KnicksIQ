# Opponent narrowing release evidence — 2026-10-20

## Scope and interpretation

Local, read-only HTTP verification against active archive `2025-26.20260928.1`, manifest SHA-256 `549af2edd0d195eff60bb318bdc58a8c8e217ea0359c0684d492d5292dcb595b`. The query-specific narrowing rule is strict sign reversal: a Knicks lost lead requires a verified Knicks lead followed by an opponent lead; a tie alone is not a lost lead. Erased deficit accepts a later tie or Knicks lead. These are implementation/draft semantics pending owner review, not an owner ruling.

The SQL below independently recomputes the date candidates from active-release games and observed event scoreboards. Explicitly unobserved scores and legacy 0–0 sentinels are ignored; score margins, duplicate sequences, monotonic/non-simultaneous points, final status and final-score reconciliation are checked before a PBP row can count as verified. Final-score win candidates are kept separate from PBP lead-change candidates.

## Independent SQL candidate sets

The query returned:

| Predicate | Exact game dates |
|---|---|
| ATL strict lost lead | 2025-12-27, 2026-01-02, 2026-04-06, 2026-04-18, 2026-04-20, 2026-04-23, 2026-04-25, 2026-04-30 |
| BOS strict lost lead | 2025-10-24, 2025-12-02, 2026-02-08, 2026-04-09 |
| DEN strict lost lead | 2026-02-04 |
| CHI final-score Knicks wins | 2025-11-02, 2026-02-22, 2026-04-03 |

This excludes ATL 2026-04-28, where the Knicks did not lead and then trail, and CHI 2025-10-31, a loss rather than a Knicks win. The only unverified row in the queried ATL/BOS/CHI/DEN/MIL opponent set was MIL 2025-10-28 (`nonmonotonic_or_simultaneous_points`); there were no unverified ATL, BOS, CHI or DEN rows in the query result.

Repeatable PostgreSQL SQL:

```sql
WITH active_games AS (
  SELECT g.id, g.game_date, g.home_team_id, g.away_team_id,
         g.home_score AS final_home, g.away_score AS final_away, g.status,
         CASE WHEN g.home_team_id = 'NYK' THEN g.away_team_id ELSE g.home_team_id END AS opponent_id
  FROM games g
  JOIN dataset_releases r ON r.id = g.release_id
  WHERE r.status = 'active' AND g.season = '2025-26'
    AND 'NYK' IN (g.home_team_id, g.away_team_id)
    AND CASE WHEN g.home_team_id = 'NYK' THEN g.away_team_id ELSE g.home_team_id END IN ('ATL','BOS','CHI','DEN','MIL')
), event_rows AS (
  SELECT e.game_id, e.period, e.sequence, e.home_score, e.away_score, e.score_margin,
         e.score_observed,
         (e.score_observed IS TRUE OR (e.score_observed IS NULL AND (e.home_score, e.away_score) <> (0, 0))) AS observed,
         count(*) OVER (PARTITION BY e.game_id, e.sequence) AS sequence_count,
         g.home_team_id
  FROM game_events e JOIN active_games g ON g.id = e.game_id
), grouped AS (
  SELECT *, sum(CASE WHEN observed THEN 1 ELSE 0 END) OVER (
    PARTITION BY game_id ORDER BY period, sequence ROWS UNBOUNDED PRECEDING
  ) AS score_group
  FROM event_rows
), filled AS (
  SELECT *, coalesce(max(home_score) OVER (PARTITION BY game_id, score_group), 0) AS event_home,
            coalesce(max(away_score) OVER (PARTITION BY game_id, score_group), 0) AS event_away
  FROM grouped
), ordered AS (
  SELECT *, lag(event_home, 1, 0) OVER (PARTITION BY game_id ORDER BY period, sequence) AS previous_home,
            lag(event_away, 1, 0) OVER (PARTITION BY game_id ORDER BY period, sequence) AS previous_away,
            max(CASE WHEN (CASE WHEN home_team_id = 'NYK' THEN event_home - event_away ELSE event_away - event_home END) > 0 THEN 1 ELSE 0 END)
              OVER (PARTITION BY game_id ORDER BY period, sequence ROWS UNBOUNDED PRECEDING) AS nyk_had_led
  FROM filled
), summaries AS (
  SELECT game_id,
         max(CASE WHEN observed THEN 1 ELSE 0 END) AS has_observed,
         max(CASE WHEN observed AND score_margin <> home_score - away_score THEN 1 ELSE 0 END) AS bad_margin,
         max(CASE WHEN sequence_count > 1 THEN 1 ELSE 0 END) AS duplicate_sequence,
         max(CASE WHEN event_home < previous_home OR event_away < previous_away
                       OR (event_home > previous_home AND event_away > previous_away)
                  THEN 1 ELSE 0 END) AS bad_transition,
         (array_agg(event_home ORDER BY period DESC, sequence DESC))[1] AS observed_final_home,
         (array_agg(event_away ORDER BY period DESC, sequence DESC))[1] AS observed_final_away,
         max(CASE WHEN (CASE WHEN home_team_id = 'NYK' THEN event_home - event_away ELSE event_away - event_home END) < 0
                       AND nyk_had_led = 1 THEN 1 ELSE 0 END) AS strict_lost_lead
  FROM ordered GROUP BY game_id
), reconciled AS (
  SELECT g.*, coalesce(s.has_observed, 0) AS has_observed, coalesce(s.bad_margin, 0) AS bad_margin,
         coalesce(s.duplicate_sequence, 0) AS duplicate_sequence, coalesce(s.bad_transition, 0) AS bad_transition,
         s.observed_final_home, s.observed_final_away, s.strict_lost_lead,
         coalesce(g.status = 'final' AND s.has_observed = 1 AND s.bad_margin = 0 AND s.duplicate_sequence = 0
          AND s.bad_transition = 0 AND s.observed_final_home = g.final_home AND s.observed_final_away = g.final_away, false) AS verified
  FROM active_games g LEFT JOIN summaries s ON s.game_id = g.id
)
SELECT 'release' AS evidence, r.version AS value, r.manifest_sha256 AS details
FROM dataset_releases r WHERE r.status = 'active'
UNION ALL
SELECT 'ATL_strict_lost_lead', game_date::text, id::text FROM reconciled WHERE opponent_id = 'ATL' AND verified AND strict_lost_lead = 1
UNION ALL
SELECT 'BOS_strict_lost_lead', game_date::text, id::text FROM reconciled WHERE opponent_id = 'BOS' AND verified AND strict_lost_lead = 1
UNION ALL
SELECT 'DEN_strict_lost_lead', game_date::text, id::text FROM reconciled WHERE opponent_id = 'DEN' AND verified AND strict_lost_lead = 1
UNION ALL
SELECT 'CHI_final_score_wins', game_date::text, id::text FROM reconciled
WHERE opponent_id = 'CHI' AND status = 'final' AND final_home > final_away AND home_team_id = 'NYK'
   OR opponent_id = 'CHI' AND status = 'final' AND final_away > final_home AND away_team_id = 'NYK'
UNION ALL
SELECT 'unverified_' || opponent_id, game_date::text,
       concat_ws(',', CASE WHEN has_observed = 0 THEN 'no_observed_scores' END,
                        CASE WHEN bad_margin = 1 THEN 'score_margin_mismatch' END,
                        CASE WHEN duplicate_sequence = 1 THEN 'duplicate_sequence' END,
                        CASE WHEN bad_transition = 1 THEN 'nonmonotonic_or_simultaneous_points' END,
                        CASE WHEN observed_final_home IS DISTINCT FROM final_home OR observed_final_away IS DISTINCT FROM final_away THEN 'final_score_unreconciled' END)
FROM reconciled WHERE NOT verified
ORDER BY 1, 2;
```

## Real HTTP verification

Used the local ASGI app over `httpx.ASGITransport` with the local archive/Redis stack, `ANALYSIS_ANSWER_MODE=llm_primary`, and the configured DeepInfra route (`deepseek/deepseek-v4.1-flash`). This exercised `/analysis/query`, including the live writer and independent reviewer; no production request or data write was made.

* One fit: `How did the Knicks lose the lead against Denver?` → HTTP 200, `route=llm_analyst`, `llm_validated=true`, no warnings. The active archive has exactly one fit, 2026-02-04. The final answer stated that NYK led 3–0 at Q1 11:33 (event 4), then DEN led 18–16 at Q1 04:53 (event 46), and the Knicks ultimately won 134–127. Both writer and reviewer made provider calls; the trace recorded two DeepInfra calls and no provider errors.
* Multiple fits: `How did the Knicks lose the lead against Atlanta?` → HTTP 200, deterministic clarification listing exactly the eight ATL dates above; zero provider calls, no citations and no warnings.

**Exact returned answers:**

* Denver: “In the 2026-02-04 regular-season game, the Knicks beat Denver 134–127. The archive's verified lead-change sequence shows the Knicks first took the lead at Q1 11:33 (NYK 3–DEN 0, event 4), and Denver then took the lead at Q1 04:53 (NYK 16–DEN 18, event 46). That is the first verified transition pair in which the Knicks led and then trailed. The available play-by-play evidence is descriptive only and does not establish why or how the lead changed beyond these observed scoring transitions.”
* Atlanta: “Which archived ATL game date should I use: 2025-12-27, 2026-01-02, 2026-04-06, 2026-04-18, 2026-04-20, 2026-04-23, 2026-04-25, 2026-04-30?”

The repeatable synthetic HTTP fixture is in `apps/api/app/tests/test_opponent_narrowing_http.py`: TOR 2026-02-01 `[(2, 0), (2, 3), (4, 3)]` is a lead lost and regained in a final Knicks win; TOR 2026-02-02 `[(0, 2), (2, 2), (2, 2)]` ties after trailing without a strict lead reversal; TOR 2026-02-03 `[(10, 0), (12, 0), (12, 4)]` is a wire-to-wire win. BOS 2026-01-01 `[(2, 0), (2, 3), (8, 3)]` loses the lead but wins; 2026-01-02 `[(0, 2), (0, 4), (2, 4)]` loses without leading; 2026-01-03 `[(3, 0), (10, 0), (10, 4)]` is wire-to-wire; 2026-01-04 `[(5, 0), (5, 7)]` loses a lead and the game. CHI 2026-03-01 `[(2, 0)]` is a final win and 2026-03-02 `[(0, 3)]` is a loss. The same file mutates a score observation to `score_observed=false` and separately corrupts an observed scoreboard; only the valid TOR lost-lead game is cited in the former, and the malformed game is clarified rather than counted in the latter.

The pre-fix llm_primary failure artifact is retained at `/tmp/kiq-opp-live-opponent-narrowing-failure.json`. The exact incorrect answer began: “The Knicks won this game 134-127 over Denver on 2026-02-04, so they did not lose the lead.” It was `validated_declined` with three citations, no warnings, four provider calls, and independently verified DEN candidate date 2026-02-04; no PBP lead-reversal claim reached the writer/reviewer. An intermediate compact-claim run supplied the reversal pair to the writer, which answered correctly, but unrelated retrieval receipts crowded the reviewer input. The final report `/tmp/kiq-opp-live-opponent-narrowing.json` preserves the HTTP response, raw writer/reviewer responses, claim binding and call records; `/tmp/kiq-opp-live-opponent-narrowing.trace.json` preserves both prepared provider payloads. The final run sends the complete selected-game claim and its supporting evidence, and the independent reviewer validates the exact answer above.
