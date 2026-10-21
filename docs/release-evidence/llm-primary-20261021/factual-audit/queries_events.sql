-- name: event_runs
with sc as (
  select e.game_id, e.period, e.sequence, e.team_id,
         (e.home_score+e.away_score) - (lag(e.home_score) over w + lag(e.away_score) over w) delta
  from game_events e
  where e.event_type in ('made_shot','free_throw') and e.home_score+e.away_score>0
  window w as (partition by e.game_id order by e.period, e.sequence)
), scored as (select * from sc where delta>0),
grp as (
  select *, row_number() over (partition by game_id order by period,sequence)
          - row_number() over (partition by game_id,team_id order by period,sequence) grp
  from scored
), runs as (
  select game_id, team_id, grp, sum(delta) run_points, min(period) period
  from grp group by game_id, team_id, grp
)
select json_build_object(
  'nyk_runs', (select json_agg(x) from (
      select r.game_id, g.game_date, g.home_team_id, g.away_team_id,
             r.run_points, r.period
      from runs r join games g on g.id=r.game_id
      where r.team_id='NYK' order by r.run_points desc, g.game_date limit 8) x),
  'opp_runs', (select json_agg(x) from (
      select r.game_id, g.game_date, g.home_team_id, g.away_team_id,
             r.run_points, r.period
      from runs r join games g on g.id=r.game_id
      where r.team_id<>'NYK' order by r.run_points desc, g.game_date limit 8) x),
  'opp_runs_in_losses', (select json_agg(x) from (
      select r.game_id, g.game_date, g.home_team_id, g.away_team_id,
             r.run_points, r.period
      from runs r join games g on g.id=r.game_id
      where r.team_id<>'NYK'
        and ((g.home_team_id='NYK' and g.home_score<g.away_score)
          or (g.away_team_id='NYK' and g.away_score<g.home_score))
      order by r.run_points desc, g.game_date limit 8) x),
  'nyk_runs_vs_bos', (select json_agg(x) from (
      select r.game_id, g.game_date, r.run_points, r.period
      from runs r join games g on g.id=r.game_id
      where r.team_id='NYK' and 'BOS' in (g.home_team_id,g.away_team_id)
      order by r.run_points desc limit 5) x)
);

-- name: event_deficits
with ev as (
  select e.game_id, e.period, e.sequence, e.home_score, e.away_score,
         case when g.home_team_id='NYK' then e.score_margin else -e.score_margin end nyk_margin,
         case when (g.home_team_id='NYK' and g.home_score>g.away_score)
                or (g.away_team_id='NYK' and g.away_score>g.home_score)
              then 'W' else 'L' end res,
         g.game_date, g.home_team_id, g.away_team_id, g.home_score final_home,
         g.away_score final_away
  from game_events e join games g on g.id=e.game_id
  where 'NYK' in (g.home_team_id, g.away_team_id) and e.home_score+e.away_score>0
), agg as (
  select game_id, game_date, home_team_id, away_team_id, res, final_home, final_away,
         min(nyk_margin) biggest_deficit, max(nyk_margin) biggest_lead
  from ev group by game_id, game_date, home_team_id, away_team_id, res, final_home, final_away
)
select json_build_object(
  'largest_deficit_erased', (select row_to_json(x) from (
      select game_id, game_date, home_team_id, away_team_id, biggest_deficit,
             final_home, final_away
      from agg where res='W' and biggest_deficit<0
      order by biggest_deficit asc limit 1) x),
  'largest_blown_lead', (select row_to_json(x) from (
      select game_id, game_date, home_team_id, away_team_id, biggest_lead,
             final_home, final_away
      from agg where res='L'
      order by biggest_lead desc limit 1) x),
  'atlanta_games', (select json_agg(x) from (
      select game_id, game_date, home_team_id, away_team_id, res,
             biggest_lead, biggest_deficit, final_home, final_away
      from agg where 'ATL' in (home_team_id, away_team_id)
      order by game_date) x),
  'charlotte_games', (select json_agg(x) from (
      select game_id, game_date, home_team_id, away_team_id, res,
             biggest_lead, biggest_deficit, final_home, final_away
      from agg where 'CHA' in (home_team_id, away_team_id)
      order by game_date) x)
);

-- name: box_scores
select json_agg(x) from (
  select p.full_name, s.game_id, g.game_date, g.season_type,
         g.home_team_id, g.away_team_id, g.home_score, g.away_score,
         s.points, s.rebounds, s.assists, s.turnovers, s.minutes,
         s.three_pointers_made, s.plus_minus, s.starter
  from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
  where (p.full_name='Mikal Bridges' and g.id in (2,20,62))
     or (p.full_name='Karl-Anthony Towns' and g.id in (6,21,62))
     or (p.full_name='Jalen Brunson' and g.id in (2,28,62,87))
     or (p.full_name='OG Anunoby' and g.id in (2,20,53,80))
  order by g.game_date, p.full_name
) x;

-- name: player_matchups
select json_build_object(
  'kat_vs_tor', (select json_agg(x) from (
      select g.game_date, s.points, s.rebounds, s.assists, s.turnovers, s.minutes
      from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
      where p.full_name='Karl-Anthony Towns' and 'TOR' in (g.home_team_id,g.away_team_id)
      order by g.game_date) x),
  'kat_vs_tor_avg', (select row_to_json(x) from (
      select count(*) appearances, round(avg(s.points)::numeric,2) ppg,
             round(avg(s.rebounds)::numeric,2) rpg,
             round(avg(s.assists)::numeric,2) apg,
             round(avg(s.turnovers)::numeric,2) topg
      from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
      where p.full_name='Karl-Anthony Towns' and 'TOR' in (g.home_team_id,g.away_team_id)) x),
  'bridges_vs_tor', (select json_agg(x) from (
      select g.game_date, s.points, s.rebounds, s.assists, s.turnovers, s.minutes
      from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
      where p.full_name='Mikal Bridges' and 'TOR' in (g.home_team_id,g.away_team_id)
      order by g.game_date) x),
  'bridges_vs_tor_avg', (select row_to_json(x) from (
      select count(*) appearances, round(avg(s.points)::numeric,2) ppg,
             round(avg(s.rebounds)::numeric,2) rpg
      from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
      where p.full_name='Mikal Bridges' and 'TOR' in (g.home_team_id,g.away_team_id)) x),
  'og_vs_bos', (select json_agg(x) from (
      select g.game_date, s.points, s.rebounds, s.assists, s.minutes
      from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
      where p.full_name='OG Anunoby' and 'BOS' in (g.home_team_id,g.away_team_id)
      order by g.game_date) x),
  'og_vs_bos_avg', (select row_to_json(x) from (
      select count(*) appearances, round(avg(s.points)::numeric,2) ppg
      from player_game_stats s join players p on p.id=s.player_id join games g on g.id=s.game_id
      where p.full_name='OG Anunoby' and 'BOS' in (g.home_team_id,g.away_team_id)) x),
  'nyk_rows_by_game', (select json_agg(x) from (
      select g.id game_id, count(s.id) nyk_rows
      from games g left join player_game_stats s on s.game_id=g.id and s.team_id='NYK'
      where 'NYK' in (g.home_team_id,g.away_team_id)
      group by g.id order by g.id) x)
);

-- name: coverage
with k as (
  select g.id, case when g.home_team_id='NYK' then g.away_team_id else g.home_team_id end opp
  from games g where 'NYK' in (g.home_team_id, g.away_team_id)
)
select json_build_object(
  'event_rows', (select count(*) from game_events),
  'period_rows', (select count(*) from period_scores),
  'player_rows', (select count(*) from player_game_stats),
  'nyk_player_rows', (select count(*) from player_game_stats where team_id='NYK'),
  'team_rows', (select count(*) from team_game_stats),
  'last3_player_rows', (
    select count(*) from player_game_stats s
    where s.game_id in (select id from games where 'NYK' in (home_team_id,away_team_id)
                        order by game_date desc limit 3)),
  'by_opponent', (select json_agg(x) from (
      select k.opp, count(distinct k.id) games,
             (select count(*) from game_events e
              where e.game_id in (select id from k k2 where k2.opp=k.opp)) event_rows,
             (select count(*) from period_scores p
              where p.game_id in (select id from k k2 where k2.opp=k.opp)) period_rows,
             (select count(*) from player_game_stats s
              where s.game_id in (select id from k k2 where k2.opp=k.opp)) player_rows
      from k where k.opp in ('BOS','TOR','ATL','CHA','CHI','LAL')
      group by k.opp order by k.opp) x)
);
