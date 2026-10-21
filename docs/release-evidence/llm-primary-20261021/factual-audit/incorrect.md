# INCORRECT responses

Primary verdict INCORRECT: 9 responses. Including finding-level incorrect statements: 10 responses.

## exact_statistics-009

- Question: What was the Knicks worst loss by margin?
- Quoted answer: "Knicks wins: 0 over 32 archived games. Knicks losses: 32 over 32 archived games. Knicks points: 3421 over 32 archived games."
- Primary verdict: INCORRECT
- Right value: Worst loss is 38 points: 80-118 at DET on 2026-02-06 (game 52).
- Missing required fact: 38
- Tables: games, team_game_stats

## exact_statistics-010

- Question: What was the Knicks highest-scoring game?
- Quoted answer: "The highest-scoring individual Knicks game in the available 2025-26 archive is Jalen Brunson's 47 points on 2025-12-21 against MIA (regular season). The next-highest is his 45 points on 2026-06-13 against SAS in the playoffs. Note: this reflects the highest single-player scoring game in the archive, not the team's highest total points in a game."
- Primary verdict: INCORRECT
- Right value: Team highest-scoring game is 146 points, 146-112 vs UTA on 2025-12-05 (game 22). The 47 is the player high, a different question.
- Missing required fact: 146
- Tables: games, player_game_stats

## date_range_last_n-006

- Question: How many road games did they win in December?
- Quoted answer: "The Knicks won 5 road games in December (5 wins, 0 losses across 5 archived away games)."
- Primary verdict: INCORRECT
- Right value: 5-3 in 8 road games in December (LWWWLWWL). The 5 wins are right; the 0 losses and 5-game count are not.
- FAIL: record claimed `5-0`, SQL `5-3`; quote "5 wins, 0 losses"
- FAIL: games claimed `5`, SQL `8`; quote "across 5 archived away games"
- Tables: games

## comparisons-001

- Question: Compare the Knicks' offense at home and on the road.
- Quoted answer: "I can't complete this comparison: the available evidence covers only Knicks home games (48 games in scope), with no road-game data retrieved, so there's no away sample to contrast against. The home sample does include team points totals, but without the road counterpart no home-vs-road offense comparison can be made from what's here."
- Primary verdict: DECLINE_MISSED_ANSWER
- Right value: Home 118.20 ppg over 49 games; road 114.58 ppg over 52 games. The home offense was 3.62 ppg better.
- finding: "48 games in scope" - The home-game count is 49, not 48. (home_games=49, away_games=52)
- Tables: games, team_game_stats

## turning_points-003

- Question: When did the Knicks collapse against Atlanta?
- Quoted answer: "Knicks wins: 6 over 9 archived games. Knicks losses: 3 over 9 archived games. Knicks points: 1042 over 9 archived games."
- Primary verdict: INCORRECT
- Right value: The 6-3 / 1,042 aggregates are true for the nine Atlanta games, but they do not answer when a collapse happened. The largest lead lost was 14 points on 2026-04-20 (106-107); the largest deficit was 26 on 2026-01-02.
- Missing required fact: 14
- Tables: games, game_events

## aliases_typos-004

- Question: Tell me about KAT vs the Raps.
- Quoted answer: "In the available 2025-26 regular-season archive, Karl-Anthony Towns' game against Toronto came on 2026-03-03: 21 points, 12 rebounds, 6 assists and 3 turnovers in about 29 minutes, with the Knicks winning 111-95. That's a single observed appearance, so it doesn't establish a season-long pattern versus Toronto."
- Primary verdict: INCORRECT
- Right value: The 2026-03-03 line is correct, but Towns has five appearances vs TOR, not one: 17.4 ppg, 13.6 rpg, 3.2 apg over five games.
- FAIL: appearances_vs_tor claimed `1`, SQL `5`; quote "a single observed appearance"
- Tables: player_game_stats, games

## aliases_typos-006

- Question: How did they do v ATL?
- Quoted answer: "Jalen Brunson's line against ATL on 2026-04-28 (playoffs): 39 points, 3 rebounds, 8 assists, 1 turnover in 34.7 minutes, with a +23 plus-minus in a 126-97 NYK win."
- Primary verdict: INCORRECT
- Right value: The Knicks went 6-3 vs ATL (2-1 regular season, 4-2 playoffs). The answer gives only one player's line from one game, so it does not answer 'how did they do'.
- Missing required fact: 6-3
- Tables: games, player_game_stats

## aliases_typos-009

- Question: How did OG look vs the C's?
- Quoted answer: "In the available 2025-26 archive, OG Anunoby averaged 11.5 points across 2 observed appearances against Boston. Coverage is incomplete: player rows are missing for two of the four archived games against the Celtics (game IDs 20 and 53), so this reflects only the games with recorded data."
- Primary verdict: INCORRECT
- Right value: OG averaged 11.5 over two appearances, but no player rows are missing: game 20 has 12 NYK rows and game 53 has 14. Anunoby simply did not appear in those two games.
- FAIL: rows_missing_claim claimed `True`, SQL `False`; quote "player rows are missing for two of the four archived games (game IDs 20 and 53)"
- Tables: player_game_stats, games

## aliases_typos-010

- Question: What was NY's worst collpase?
- Quoted answer: "Knicks wins: 69 over 101 archived games. Knicks losses: 32 over 101 archived games. Knicks points: 11750 over 101 archived games."
- Primary verdict: INCORRECT
- Right value: Worst collapse by blown lead is 19 points on 2025-12-31 at SAS (134-132, game 33); the worst loss by final margin is 38 at DET on 2026-02-06. The dumped 69-32 / 11750 totals are true but answer neither.
- Missing required fact: 19
- Tables: games, game_events

## unsupported-007

- Question: Did the Knicks win yesterday?
- Quoted answer: "I can't confirm a game from yesterday — the archive has no live or current-date data, and its latest dated game is 2025-12-21. In that game, a Knicks win, Jalen Brunson recorded 47 points, 3 rebounds, 8 assists and 0 turnovers against MIA."
- Primary verdict: INCORRECT
- Right value: The decline is appropriate, but the latest dated game is 2026-06-13, not 2025-12-21.
- FAIL: latest_date claimed `2025-12-21`, SQL `2026-06-13`; quote "latest dated game is 2025-12-21"
- Tables: games

