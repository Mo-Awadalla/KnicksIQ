# Per-flag verdicts: the 11 atoms the full SQL audit marked wrong

Frozen SHA: `51f184a` (`codex/llmp-integration`), worktree `final2`, live config reasoning `none`,
writer `deepseek-v4.1-flash`, reviewer `gpt-6-luna`. Responses audited:
`../bench/trial{1,2}.responses.jsonl`; audit rows: `trial{1,2}/rows.jsonl`.

Every row below is an atom the full SQL audit marked `wrong`. The delivered value was recomputed
from the raw restore tables (`kiq-integrate-postgres-1`, port 55500) under the scope the same
sentence states. `BINDING` means the delivered number is correct and the audit bound the atom to
the wrong subject, scope, sign, clock or game. `REAL` means the delivered number is wrong.

**Result: 11 BINDING, 0 REAL.** Trial 1: 6 flagged, 6 BINDING. Trial 2: 5 flagged, 5 BINDING.

## Trial 1 (6 atoms)

| id | atom | delivered | recomputed | SQL | verdict | mis-binding |
| --- | --- | ---: | --- | --- | --- | --- |
| comparisons-002 | `74` | 74 | 74 | `select p.full_name, count(*) games, round(avg(s.points)::numeric,2) ppg from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name in ('Jalen Brunson','Karl-Anthony Towns') and s.minutes>0 and g.season_type='regular' group by 1 order by 1` → Brunson 74 / 26.04; Towns 75 / 20.05 | BINDING | `74` is Brunson's appearance count; the audit bound it to Towns (expected 75) |
| single_game_narrative-001 | `18` | 18 | 18 | `select sequence,period,clock,team_id,home_score,away_score from game_events where game_id=20 and period=3 and clock='00:03'` → 94-76 (BOS-NYK); NYK deficit 18 | BINDING | the audit classified the atom as a `comeback` (expected `None`); it is a scoreboard deficit |
| turning_points-008 | `3-0` | '3-0' | '3-0' | `select sequence,period,clock,team_id,event_type,home_score,away_score from game_events where game_id=82 and period=1 and clock='10:26' order by sequence` → NYK free throw makes it 3-0; `select max(score_margin) from game_events where game_id=82` → 3 | BINDING | the audit looked for a CHA run; the atom is the NYK lead snapshot |
| aliases_typos-004 | `8` | 8 | 8 | `select g.game_date,s.points,s.rebounds from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id where s.team_id='NYK' and p.full_name='Karl-Anthony Towns' and s.minutes>0 and g.season_type='regular' and 'TOR' in (g.home_team_id,g.away_team_id) order by g.game_date` → 2026-01-28: 8 points, 22 rebounds | BINDING | the audit bound a player point total to team points (expected 575) |
| aliases_typos-005 | `Q1 05:53` | 'Q1 05:53' | 'Q1 05:53' | `select sequence,period,clock,team_id,event_type,home_score,away_score from game_events where game_id=22 and period=1 and event_type in ('made_shot','free_throw') order by sequence` → NYK made shot at 05:53 makes it 23-0; the 20 unanswered NYK points run from the 09:14 basket (pre-run score 3-0) to 05:53 | BINDING | run end clock is 05:53; the audit expected Q1 01:01 |
| aliases_typos-005 | `23-0` | '23-0' | '23-0' | same query → 23-0 at Q1 05:53; 20-0 from 09:14 to 05:53, start score 3-0 | BINDING | the audit reported `no matching run` because it attributed the run to the wrong team/window |

## Trial 2 (5 atoms)

| id | atom | delivered | recomputed | SQL | verdict | mis-binding |
| --- | --- | ---: | --- | --- | --- | --- |
| date_range_last_n-001 | `+12` | 12.0 | 12 | `with t as (select case when home_team_id='NYK' then home_score else away_score end nyk, case when home_team_id='NYK' then away_score else home_score end opp from games where 'NYK' in (home_team_id,away_team_id) and season_type='playoffs' and game_date between '2026-06-03' and '2026-06-13') select count(*), sum(nyk), sum(opp), sum(nyk-opp), avg(nyk-opp) from t` → 5 games, 522-510, +12 aggregate, 2.40 per game | BINDING | the sentence says aggregate margin; the audit bound it as margin per game (expected 2.4) |
| comparisons-002 | `74` | 74 | 74 | same appearance query as trial 1 → Brunson 74 / 26.04; Towns 75 / 20.05 | BINDING | the sentence says `74 ... for Brunson and 75 for Towns`; the audit bound 74 to Towns |
| comparisons-010 | `29` | 29 | 29 | `with t as (select case when (home_team_id='NYK' and home_score>away_score) or (away_team_id='NYK' and away_score>home_score) then 'W' else 'L' end res, case when home_team_id='NYK' then home_score else away_score end nyk, case when home_team_id='NYK' then away_score else home_score end opp from games where 'NYK' in (home_team_id,away_team_id) and season_type='regular') select res, count(*), round(avg(nyk)::numeric,2), round(avg(opp)::numeric,2), round(avg(nyk-opp)::numeric,2) from t group by res` → L 29 (106.76/118.55/-11.79), W 53 (121.75/105.51/+16.25) | BINDING | the atom is the loss count; the audit bound it to wins (expected 53) |
| turning_points-001 | `17-0` | '17-0' | '17-0' | `select sequence,period,clock,team_id,event_type,home_score,away_score from game_events where game_id=2 and period=2 and sequence between 146 and 192 and event_type in ('made_shot','free_throw') order by sequence` → BOS last score at 07:48 makes 33-36; NYK then score 17 unanswered to 50-36 at 03:49 | BINDING | the audit classified it as a BOS run; it is a NYK run |
| turning_points-009 | `69-68` | '69-68' | '69-68' | `select sequence,period,clock,team_id,event_type,home_score,away_score from game_events where game_id=47 and period=3 and clock='03:54'` → 68-69 (TOR-NYK); `with e as (select sequence,period,clock,home_score,away_score,(away_score-home_score) m from game_events where game_id=47 and event_type in ('made_shot','free_throw') and home_score+away_score>0 and (period>2 or (period=2 and sequence >= (select min(sequence) from game_events where game_id=47 and period=2 and clock='09:15')))) select * from e where m>=0 order by sequence limit 3` → first non-negative NYK margin is Q3 03:54 | BINDING | the audit's `first tie` verifier returned `None`; the score and first lead are correct |

## Real wrong numbers

None among the 11 flagged atoms. The audit cannot certify the rest of either response set:
211 (trial 1) and 186 (trial 2) atoms, 397 in total, are `unverified`, so "zero wrong numbers"
for the full 140-answer set remains unproven by this audit.
