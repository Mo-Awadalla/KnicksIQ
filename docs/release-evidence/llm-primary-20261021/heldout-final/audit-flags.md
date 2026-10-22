# Held-out v2 SQL flag verdicts

Frozen code SHA: `51f184a` (`Keep reasoning off; freeze for the final runs`). The full audit is `audit-main/`; it flagged 33 numeric atoms as `wrong`. Every one was re-evaluated under the response's stated and held-out question scope below. Verdict convention: **BINDING** means the number is true under its stated scope and the audit bound it to another scope/order/game; **REAL** means the number itself is wrong under the stated scope.

**Verdicts: 33 BINDING, 0 REAL.** There are also 151 audit `unverified` atoms; they are unresolved and are not counted as correct. Some responses below still fail the honest question scorer because they missed the requested scope/fact, even where their flagged numbers are true.

All SQL was run against the restored local `knicksiq` database via `docker exec kiq-integrate-postgres-1 psql -U knicksiq -d knicksiq`. `games` is the Knicks schedule in this release. Per-game Knicks/opponent values use home/away orientation, not raw home/away orientation.

## Flag ledger

Every item listed is individually labelled **BINDING**.

| Response id | Flagged atom(s) | Correct scope / SQL result | Verdict |
| --- | --- | --- | --- |
| `heldout2-exact_statistics-003` | `42` | 42 regular-season road games; 23 wins, 19 losses. | BINDING |
| `heldout2-date_range_last_n-002` | `113.4` | October Knicks scoring: 567 / 5 = 113.4 PPG. The requested opponent-allowed figure is 577 / 5 = 115.4 PPG; the answer explicitly labels 113.4 as Knicks scoring and declines the requested value. | BINDING |
| `heldout2-date_range_last_n-003` | `12`, `9`, `3` | April all-phase record population: 12 games, 9 wins, 3 losses. | BINDING |
| `heldout2-date_range_last_n-004` | `9-3`, `12`, `1,401`, `+168` | April all-phase record, games, Knicks points and aggregate point margin: 9-3, 12, 1,401, +168. | BINDING |
| `heldout2-date_range_last_n-005` | `4-1`, `4` | April road games: 5 total, 4 wins, 1 loss. | BINDING |
| `heldout2-date_range_last_n-008` | `82` | 82 regular-season games overall; the requested last 11 regular-season games are 11 games at 114.27 PPG. The answer gives a true season-wide count/PPG but does not answer the last-11 question. | BINDING |
| `heldout2-date_range_last_n-009` | `2-3`, `5`, `11-3`, `14` | October regular season: 2-3 in 5; November: 11-3 in 14; combined window: 13-6. | BINDING |
| `heldout2-date_range_last_n-010` | `9`, `12`, `3`, `12` | April all-phase record is 9-3 in 12 games; SQL finds 7 April wins by at least 10 points. The answer gives the true April record but misses the asked double-digit-win count. | BINDING |
| `heldout2-comparisons-005` | `116.45`, `6.33` | 116.45 PPG and +6.33 average margin are true overall regular-season values. The requested opponent PPGs are Brooklyn 115.00 and Indiana 121.25. | BINDING |
| `heldout2-comparisons-008` | `-2.0`, first `5`, second `5` | October: 5 games, -2.00 average margin, -10 aggregate margin. April all phases: 12 games, +14.00 average margin, +168 aggregate margin. The response repeats October values/does not supply April's required value; the audit's season-wide 82-game binding is not applicable. | BINDING |
| `heldout2-comparisons-011` | `567`, `5` | October Knicks scored 567 points in 5 games. The answer does not give the requested October/April point differentials (-10 and +168). | BINDING |
| `heldout2-single_game_narrative-001` | `Q1 10:58` | Game 9's first scoring play is a Knicks made shot at Q1 10:58, score 2-0. | BINDING |
| `heldout2-turning_points-001` | `28-25` | In game 14, quarter-end score deltas in Knicks-Dallas order are Q1 24-25, Q2 28-25, Q3 35-35, Q4 26-26; final Knicks win 113-111. | BINDING |
| `heldout2-turning_points-002` | `15-5`, `14-0`, `104-122` | In game 15 (Orlando home, Knicks away), Q1 score at 08:08 is ORL-NYK 5-15 / NYK-ORL 15-5; Orlando then scores from 5 to 19 while NYK remains 15 (14-0), ending Q1 04:39; Q4 06:18 is ORL-NYK 122-104 / NYK-ORL 104-122. | BINDING |
| `heldout2-aliases_typos-011` | `8` | Jose Alvarado's game-57 player line is 8 points; game score is 108-106. The audit attached the player's number to the team's 108 points. | BINDING |

## SQL used for each group

### Regular-season road record (`exact_statistics-003`)

```sql
SELECT count(*) AS games,
       count(*) FILTER (WHERE away_score > home_score) AS wins,
       count(*) FILTER (WHERE away_score < home_score) AS losses
FROM games
WHERE season_type = 'regular' AND away_team_id = 'NYK';
-- 42 | 23 | 19
```

### October scoring and opponent scoring (`date_range_last_n-002`, `comparisons-011`)

```sql
SELECT count(*) AS games,
       sum(CASE WHEN home_team_id = 'NYK' THEN home_score ELSE away_score END) AS nyk_points,
       sum(CASE WHEN home_team_id = 'NYK' THEN away_score ELSE home_score END) AS opponent_points
FROM games
WHERE 'NYK' IN (home_team_id, away_team_id)
  AND game_date BETWEEN '2025-10-01' AND '2025-10-31';
-- 5 | 567 | 577; 567/5 = 113.4 PPG, 577/5 = 115.4 PPG
```

### April all-phase record and totals (`date_range_last_n-003`, `-004`, `-010`)

```sql
WITH april AS (
  SELECT *,
         CASE WHEN home_team_id = 'NYK' THEN home_score ELSE away_score END AS nyk,
         CASE WHEN home_team_id = 'NYK' THEN away_score ELSE home_score END AS opp
  FROM games
  WHERE 'NYK' IN (home_team_id, away_team_id)
    AND game_date BETWEEN '2026-04-01' AND '2026-04-30'
)
SELECT count(*) AS games,
       count(*) FILTER (WHERE nyk > opp) AS wins,
       count(*) FILTER (WHERE nyk < opp) AS losses,
       sum(nyk) AS nyk_points,
       sum(nyk - opp) AS aggregate_margin,
       count(*) FILTER (WHERE nyk > opp AND nyk - opp >= 10) AS wins_by_10_plus
FROM april;
-- 12 | 9 | 3 | 1401 | 168 | 7
```

### April road record (`date_range_last_n-005`)

```sql
SELECT count(*) AS games,
       count(*) FILTER (WHERE away_score > home_score) AS wins,
       count(*) FILTER (WHERE away_score < home_score) AS losses
FROM games
WHERE away_team_id = 'NYK'
  AND game_date BETWEEN '2026-04-01' AND '2026-04-30';
-- 5 | 4 | 1
```

### Regular-season last 11 and full-season values (`date_range_last_n-008`, `comparisons-005`)

```sql
WITH recent AS (
  SELECT CASE WHEN home_team_id = 'NYK' THEN home_score ELSE away_score END AS nyk
  FROM games
  WHERE 'NYK' IN (home_team_id, away_team_id) AND season_type = 'regular'
  ORDER BY game_date DESC LIMIT 11
)
SELECT (SELECT count(*) FROM games
        WHERE 'NYK' IN (home_team_id, away_team_id) AND season_type = 'regular') AS season_games,
       (SELECT count(*) FROM recent) AS last_11_games,
       round((SELECT avg(nyk) FROM recent)::numeric, 2) AS last_11_ppg;
-- 82 | 11 | 114.27

SELECT count(*) AS games,
       count(*) FILTER (WHERE (home_team_id = 'NYK' AND home_score > away_score)
                            OR (away_team_id = 'NYK' AND away_score > home_score)) AS wins,
       count(*) FILTER (WHERE (home_team_id = 'NYK' AND home_score < away_score)
                            OR (away_team_id = 'NYK' AND away_score < home_score)) AS losses,
       round(avg(CASE WHEN home_team_id = 'NYK' THEN home_score ELSE away_score END)::numeric, 2) AS ppg,
       round(avg(CASE WHEN home_team_id = 'NYK' THEN home_score-away_score
                      ELSE away_score-home_score END)::numeric, 2) AS average_margin
FROM games
WHERE 'NYK' IN (home_team_id, away_team_id) AND season_type = 'regular';
-- 82 | 53 | 29 | 116.45 | 6.33

SELECT opponent, count(*) AS games,
       round(avg(nyk_points)::numeric, 2) AS ppg
FROM (
  SELECT CASE WHEN home_team_id = 'NYK' THEN away_team_id ELSE home_team_id END AS opponent,
         CASE WHEN home_team_id = 'NYK' THEN home_score ELSE away_score END AS nyk_points
  FROM games
  WHERE 'NYK' IN (home_team_id, away_team_id) AND season_type = 'regular'
) g
WHERE opponent IN ('BKN', 'IND')
GROUP BY opponent ORDER BY opponent;
-- BKN | 4 | 115.00; IND | 4 | 121.25
```

### October/November records (`date_range_last_n-009`)

```sql
SELECT to_char(game_date, 'YYYY-MM') AS month, count(*) AS games,
       count(*) FILTER (WHERE (home_team_id = 'NYK' AND home_score > away_score)
                            OR (away_team_id = 'NYK' AND away_score > home_score)) AS wins,
       count(*) FILTER (WHERE (home_team_id = 'NYK' AND home_score < away_score)
                            OR (away_team_id = 'NYK' AND away_score < home_score)) AS losses
FROM games
WHERE 'NYK' IN (home_team_id, away_team_id) AND season_type = 'regular'
  AND game_date BETWEEN '2025-10-01' AND '2025-11-30'
GROUP BY 1 ORDER BY 1;
-- 2025-10 | 5 | 2 | 3; 2025-11 | 14 | 11 | 3
```

### October and April margins (`comparisons-008`)

```sql
SELECT to_char(game_date, 'YYYY-MM') AS month, count(*) AS games,
       round(avg(CASE WHEN home_team_id = 'NYK' THEN home_score-away_score
                      ELSE away_score-home_score END)::numeric, 2) AS average_margin,
       sum(CASE WHEN home_team_id = 'NYK' THEN home_score-away_score
                ELSE away_score-home_score END) AS aggregate_margin,
       sum(CASE WHEN home_team_id = 'NYK' THEN home_score ELSE away_score END) AS nyk_points
FROM games
WHERE 'NYK' IN (home_team_id, away_team_id)
  AND (game_date BETWEEN '2025-10-01' AND '2025-10-31'
       OR game_date BETWEEN '2026-04-01' AND '2026-04-30')
GROUP BY 1 ORDER BY 1;
-- 2025-10 | 5 | -2.00 | -10 | 567
-- 2026-04 | 12 | 14.00 | 168 | 1401
```

### Game 9 first score (`single_game_narrative-001`)

```sql
SELECT sequence, period, clock, team_id, home_score, away_score, description
FROM game_events
WHERE game_id = 9 AND period = 1 AND event_type = 'made_shot'
ORDER BY sequence LIMIT 1;
-- 8 | 1 | 10:58 | NYK | 2 | 0 | Towns made shot
```

### Game 14 quarter scores (`turning_points-001`)

```sql
WITH end_scores AS (
  SELECT DISTINCT ON (e.period) e.period,
         CASE WHEN g.home_team_id = 'NYK' THEN e.home_score ELSE e.away_score END AS nyk_total,
         CASE WHEN g.home_team_id = 'NYK' THEN e.away_score ELSE e.home_score END AS opp_total
  FROM game_events e JOIN games g ON g.id = e.game_id
  WHERE e.game_id = 14 AND (e.home_score > 0 OR e.away_score > 0)
  ORDER BY e.period, e.sequence DESC
), quarters AS (
  SELECT period,
         nyk_total - coalesce(lag(nyk_total) OVER (ORDER BY period), 0) AS nyk_points,
         opp_total - coalesce(lag(opp_total) OVER (ORDER BY period), 0) AS opp_points
  FROM end_scores
)
SELECT period, nyk_points, opp_points FROM quarters ORDER BY period;
-- Q1 24-25; Q2 28-25; Q3 35-35; Q4 26-26
```

### Game 15 score order, Orlando run and Q4 lead (`turning_points-002`)

```sql
SELECT sequence, period, clock, home_score AS ORL, away_score AS NYK
FROM game_events
WHERE game_id = 15 AND (
  sequence IN (32, 38, 71) OR (period = 4 AND clock = '06:18')
)
ORDER BY sequence;
-- 32 | Q1 08:08 | 5 | 15
-- 38 | Q1 07:34 | 7 | 15
-- 71 | Q1 04:39 | 19 | 15
-- 403 | Q4 06:18 | 122 | 104

SELECT min(home_score) AS ORL_start, max(home_score) AS ORL_end,
       min(away_score) AS NYK_min, max(away_score) AS NYK_max
FROM game_events
WHERE game_id = 15 AND sequence BETWEEN 32 AND 71
  AND (home_score <> 0 OR away_score <> 0);
-- 5 | 19 | 15 | 15: Orlando gained 14; New York did not score.
-- In Knicks-Orlando order: 15-5, 15-19; at Q4 06:18, 104-122.
```

### Game 57 Jose Alvarado line (`aliases_typos-011`)

```sql
SELECT p.full_name, s.points, s.minutes, g.home_score, g.away_score,
       g.home_team_id, g.away_team_id
FROM player_game_stats s
JOIN players p ON p.id = s.player_id
JOIN games g ON g.id = s.game_id
WHERE g.id = 57 AND p.full_name = 'Jose Alvarado' AND s.team_id = 'NYK';
-- Jose Alvarado | 8 | 19.85 | 108 | 106 | NYK | HOU
```
