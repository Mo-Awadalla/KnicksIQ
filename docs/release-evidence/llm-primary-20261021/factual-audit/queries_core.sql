-- Independent audit queries for the 2025-26.20260928.1 local restore.
-- Every query is read-only and returns one JSON value so audit.py can parse it.
-- Run with: docker exec kiq-integrate-postgres-1 psql -U knicksiq -d knicksiq -At -c "<query>"

-- name: core
with k as (
  select g.id, g.season_type, g.game_date, g.home_team_id, g.away_team_id,
         g.home_score, g.away_score,
         case when g.home_team_id='NYK' then g.home_score else g.away_score end pts,
         case when g.home_team_id='NYK' then g.away_score else g.home_score end opp,
         case when g.home_team_id='NYK' then 'home' else 'away' end loc,
         case when (g.home_team_id='NYK' and g.home_score>g.away_score)
                or (g.away_team_id='NYK' and g.away_score>g.home_score)
              then true else false end win
  from games g
  where 'NYK' in (g.home_team_id, g.away_team_id)
)
select json_agg(x) from (
  select 'all' scope, count(*) games, count(*) filter (where win) wins,
         count(*) filter (where not win) losses, sum(pts) points,
         round(avg(pts)::numeric,4) avg_points, sum(pts-opp) margin,
         round(avg(pts-opp)::numeric,4) avg_margin,
         count(*) filter (where loc='home' and win) home_wins,
         count(*) filter (where loc='away' and win) away_wins,
         count(*) filter (where loc='home') home_games,
         count(*) filter (where loc='away') away_games
  from k
  union all
  select 'regular' scope, count(*), count(*) filter (where win),
         count(*) filter (where not win), sum(pts),
         round(avg(pts)::numeric,4), sum(pts-opp),
         round(avg(pts-opp)::numeric,4),
         count(*) filter (where loc='home' and win),
         count(*) filter (where loc='away' and win),
         count(*) filter (where loc='home'), count(*) filter (where loc='away')
  from k where season_type='regular'
) x;

-- name: integrity
select json_build_object(
  'games', (select count(*) from games),
  'distinct_nba_game_ids', (select count(distinct nba_game_id) from games),
  'team_stat_rows', (select count(*) from team_game_stats),
  'player_stat_rows', (select count(*) from player_game_stats),
  'period_rows', (select count(*) from period_scores),
  'event_rows', (select count(*) from game_events),
  'team_score_mismatches', (
    select count(*) from (
      select g.id from games g join team_game_stats t on t.game_id=g.id
      group by g.id, g.home_score, g.away_score
      having g.home_score <> sum(case when t.team_id=g.home_team_id then t.points end)
          or g.away_score <> sum(case when t.team_id=g.away_team_id then t.points end)
    ) z),
  'period_score_mismatches', (
    select count(*) from (
      select g.id from games g join period_scores p on p.game_id=g.id
      group by g.id, g.home_score, g.away_score
      having g.home_score <> sum(case when p.team_id=g.home_team_id then p.points end)
          or g.away_score <> sum(case when p.team_id=g.away_team_id then p.points end)
    ) z),
  'play_in_games', (select count(*) from games where season_type='play_in')
);

-- name: extremes
with k as (
  select g.id, g.game_date, g.season_type, g.home_team_id, g.away_team_id,
         g.home_score, g.away_score,
         case when g.home_team_id='NYK' then g.home_score else g.away_score end pts,
         case when g.home_team_id='NYK' then g.away_score else g.home_score end opp,
         case when (g.home_team_id='NYK' and g.home_score>g.away_score)
                or (g.away_team_id='NYK' and g.away_score>g.home_score)
              then 'W' else 'L' end res
  from games g where 'NYK' in (g.home_team_id, g.away_team_id)
)
select json_build_object(
  'biggest_win', (select row_to_json(x) from (
      select id, game_date, season_type,
             case when home_team_id='NYK' then away_team_id else home_team_id end opponent,
             pts, opp, pts-opp margin
      from k order by pts-opp desc limit 1) x),
  'worst_loss', (select row_to_json(x) from (
      select id, game_date, season_type,
             case when home_team_id='NYK' then away_team_id else home_team_id end opponent,
             pts, opp, pts-opp margin
      from k order by pts-opp asc limit 1) x),
  'highest_team_game', (select row_to_json(x) from (
      select id, game_date, season_type,
             case when home_team_id='NYK' then away_team_id else home_team_id end opponent,
             pts, opp, pts-opp margin
      from k order by pts desc limit 1) x),
  'highest_player_game', (select row_to_json(x) from (
      select p.full_name, s.points, g.game_date, g.season_type,
             case when g.home_team_id='NYK' then g.away_team_id else g.home_team_id end opponent
      from player_game_stats s join players p on p.id=s.player_id
      join games g on g.id=s.game_id
      order by s.points desc limit 1) x),
  'second_highest_player_game', (select row_to_json(x) from (
      select p.full_name, s.points, g.game_date, g.season_type,
             case when g.home_team_id='NYK' then g.away_team_id else g.home_team_id end opponent
      from player_game_stats s join players p on p.id=s.player_id
      join games g on g.id=s.game_id
      order by s.points desc offset 1 limit 1) x),
  'latest_game_date', (select max(game_date) from games),
  'closest_games', (select json_agg(x) from (
      select id, game_date, season_type, home_team_id, away_team_id,
             home_score, away_score, abs(home_score-away_score) diff
      from games where 'NYK' in (home_team_id, away_team_id)
      order by diff asc, game_date limit 6) x)
);

-- name: splits
with k as (
  select g.id, g.game_date, g.season_type, g.home_team_id, g.away_team_id,
         g.home_score, g.away_score,
         case when g.home_team_id='NYK' then g.home_score else g.away_score end pts,
         case when g.home_team_id='NYK' then g.away_score else g.home_score end opp,
         case when g.home_team_id='NYK' then 'home' else 'away' end loc,
         case when (g.home_team_id='NYK' and g.home_score>g.away_score)
                or (g.away_team_id='NYK' and g.away_score>g.home_score)
              then 'W' else 'L' end res
  from games g where 'NYK' in (g.home_team_id, g.away_team_id)
), s as (
  select 'last5' name, * from (select * from k order by game_date desc limit 5) q
  union all select 'last8', * from (select * from k order by game_date desc limit 8) q
  union all select 'last10', * from (select * from k order by game_date desc limit 10) q
  union all select 'first10', * from (select * from k order by game_date limit 10) q
  union all select 'january', * from k where game_date between '2026-01-01' and '2026-01-31'
  union all select 'dec_away', * from k where game_date between '2025-12-01' and '2025-12-31' and loc='away'
  union all select 'mar1_15', * from k where game_date between '2026-03-01' and '2026-03-15'
  union all select 'post_asb', * from k where game_date > '2026-02-15'
  union all select 'post_asb_regular', * from k where game_date > '2026-02-15' and season_type='regular'
  union all select 'pre_asb', * from k where game_date <= '2026-02-15'
)
select json_agg(x) from (
  select name, count(*) games, count(*) filter (where res='W') wins,
         count(*) filter (where res='L') losses, sum(pts) points, sum(pts-opp) margin,
         round(avg(pts)::numeric,2) avg_points,
         round(avg(pts-opp)::numeric,2) avg_margin,
         min(game_date) first_date, max(game_date) last_date,
         string_agg(res, '' order by game_date) results,
         count(*) filter (where loc='home') home_games,
         count(*) filter (where loc='away') away_games
  from s group by name
) x;

-- name: players
select json_agg(x) from (
  select p.full_name, count(*) rows,
         count(*) filter (where s.minutes > 0) appearances,
         sum(s.points) points,
         round(avg(s.points)::numeric,3) ppg_all,
         round(avg(s.points) filter (where s.minutes > 0)::numeric,3) ppg,
         round(avg(s.rebounds) filter (where s.minutes > 0)::numeric,3) rpg,
         round(avg(s.assists) filter (where s.minutes > 0)::numeric,3) apg,
         round(avg(s.turnovers) filter (where s.minutes > 0)::numeric,3) topg
  from player_game_stats s join players p on p.id=s.player_id
  where p.full_name in ('Jalen Brunson','Karl-Anthony Towns','Josh Hart','Mikal Bridges','OG Anunoby')
  group by p.full_name
) x;

-- name: player_windows
with b as (
  select p.full_name, g.game_date, g.id game_id, s.points
  from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
  where p.full_name='Jalen Brunson'
  order by g.game_date desc limit 5
), last3 as (
  select g.id game_id, g.game_date
  from games g where 'NYK' in (g.home_team_id, g.away_team_id)
  order by g.game_date desc limit 3
)
select json_build_object(
  'brunson_last5', (select json_agg(x) from (select * from b order by game_date) x),
  'brunson_last5_avg', (select round(avg(points)::numeric,3) from b),
  'last3_leader', (select row_to_json(x) from (
      select p.full_name, sum(s.points) points, count(*) games
      from player_game_stats s join players p on p.id=s.player_id
      join last3 l on l.game_id=s.game_id and s.team_id='NYK'
      group by p.full_name order by points desc, full_name limit 1) x)
);

-- name: matchup_summary
with k as (
  select case when g.home_team_id='NYK' then g.away_team_id else g.home_team_id end opp,
         g.season_type,
         case when g.home_team_id='NYK' then g.home_score else g.away_score end pts,
         case when g.home_team_id='NYK' then g.away_score else g.home_score end opp_pts,
         case when (g.home_team_id='NYK' and g.home_score>g.away_score)
                or (g.away_team_id='NYK' and g.away_score>g.home_score)
              then 1 else 0 end win
  from games g where 'NYK' in (g.home_team_id, g.away_team_id)
)
select json_agg(x) from (
  select opp, season_type, count(*) games, sum(win) wins, count(*)-sum(win) losses,
         sum(pts) points, sum(pts-opp_pts) margin
  from k where opp in ('BOS','TOR','ATL','CHI','LAL')
  group by grouping sets ((opp, season_type), (opp))
) x;

-- name: matchups
with k as (
  select g.id, g.game_date, g.season_type, g.home_team_id, g.away_team_id,
         g.home_score, g.away_score,
         case when g.home_team_id='NYK' then g.away_team_id else g.home_team_id end opp,
         case when g.home_team_id='NYK' then 'home' else 'away' end loc
  from games g where 'NYK' in (g.home_team_id, g.away_team_id)
)
select json_agg(x) from (
  select opp, id, game_date, season_type, loc, home_team_id, away_team_id,
         home_score, away_score
  from k where opp in ('BOS','TOR','ATL','CHI','LAL')
  order by opp, game_date
) x;

-- name: team_splits
with k as (
  select g.id, g.game_date, g.season_type,
         case when g.home_team_id='NYK' then 'home' else 'away' end loc,
         case when (g.home_team_id='NYK' and g.home_score>g.away_score)
                or (g.away_team_id='NYK' and g.away_score>g.home_score)
              then 'W' else 'L' end res,
         t.points, t.field_goals_made fgm, t.field_goals_attempted fga, t.turnovers
  from games g join team_game_stats t on t.game_id=g.id and t.team_id='NYK'
  where 'NYK' in (g.home_team_id, g.away_team_id)
), bench as (
  select g.id, g.game_date,
         case when g.home_team_id='NYK' then 'home' else 'away' end loc,
         sum(case when s.starter then 0 else s.points end) bench_points,
         sum(case when s.starter then s.points else 0 end) starter_points
  from games g join player_game_stats s on s.game_id=g.id and s.team_id='NYK'
  where 'NYK' in (g.home_team_id, g.away_team_id)
  group by g.id, g.game_date, loc
), periods as (
  select g.id, p.period, p.points
  from games g join period_scores p on p.game_id=g.id and p.team_id='NYK'
  where 'NYK' in (g.home_team_id, g.away_team_id)
)
select json_build_object(
  'by_location', (select json_agg(x) from (
      select loc, count(*) games, round(avg(points)::numeric,2) ppg,
             round(100.0*sum(fgm)/sum(fga),2) fg_pct,
             round(avg(fgm)::numeric,2) fgm, round(avg(fga)::numeric,2) fga
      from k group by loc) x),
  'by_result', (select json_agg(x) from (
      select res, count(*) games, round(avg(turnovers)::numeric,2) avg_turnovers,
             round(100.0*sum(fgm)/sum(fga),2) fg_pct
      from k group by res) x),
  'bench_by_location', (select json_agg(x) from (
      select loc, count(*) games, round(avg(bench_points)::numeric,2) bench_ppg,
             round(avg(starter_points)::numeric,2) starter_ppg
      from bench group by loc) x),
  'quarters', (select json_agg(x) from (
      select period, count(*) games, sum(points) total,
             round(avg(points)::numeric,2) avg_points
      from periods group by period order by period) x),
  'game_halves', (select json_agg(x) from (
      select g.id, g.game_date,
             sum(case when p.team_id='NYK' and p.period<=2 then p.points end) nyk_h1,
             sum(case when p.team_id='NYK' and p.period>2 then p.points end) nyk_h2,
             sum(case when p.team_id<>'NYK' and p.period<=2 then p.points end) opp_h1,
             sum(case when p.team_id<>'NYK' and p.period>2 then p.points end) opp_h2
      from games g join period_scores p on p.game_id=g.id
      where g.id in (6,21)
      group by g.id, g.game_date) x)
);
