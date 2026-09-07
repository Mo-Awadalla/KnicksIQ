# Evaluation label review

All 120 fixed questions reviewed against canonical rows. Owner approvals: **0**. Gold-label eligibility: **blocked**.

Proposed dispositions: {"answer": 58, "clarify": 53, "refuse": 9}.

Original questions, categories and expected labels are preserved. Recommendations below are explicit owner adjudications, not relabelled passing results.

Player averages use appearances; last-N player windows use appearances rather than team games. All-Star boundary is after February 15, 2026, verified against [NBA All-Star](https://www.nba.com/allstar/2026/). All arithmetic uses canonical archive rows.

Every factual claim has typed values, metric scope, canonical source IDs and source-row hashes in labels.jsonl. These IDs still need mapping to the verified runtime/index; accepted prose variants and rounding are pending owner batch review.

| Question | Proposed behavior | Canonical facts / decision |
|---|---|---|
| exact_statistics-001: What was the Knicks record this season? | answer | archive — games: 101; archive — wins: 69; archive — losses: 32 |
| exact_statistics-002: How many total points did the Knicks score? | answer | archive — points: 11750 |
| exact_statistics-003: What was the Knicks average score per game? | answer | archive — points_per_game: 116.3366 |
| exact_statistics-004: What was the Knicks average margin? | answer | archive — average_margin: 7.9406 |
| exact_statistics-005: How many home games did the Knicks win? | answer | home — wins: 37 |
| exact_statistics-006: How many road games did the Knicks win? | answer | away — wins: 32 |
| exact_statistics-007: How many games did the Knicks lose? | answer | archive — losses: 32 |
| exact_statistics-008: What was the Knicks biggest win by margin? | answer | archive — game_score: {"nba_game_id": "0022500622", "game_date": "2026-01-21", "home_team_id": "NYK", "away_team_id": "BKN", "home_score": 120, "away_score": 66}; archive — margin: 54 |
| exact_statistics-009: What was the Knicks worst loss by margin? | answer | archive — game_score: {"nba_game_id": "0022500742", "game_date": "2026-02-06", "home_team_id": "DET", "away_team_id": "NYK", "home_score": 118, "away_score": 80}; archive — margin: -38 |
| exact_statistics-010: What was the Knicks highest-scoring game? | answer | archive — game_score: {"nba_game_id": "0022500343", "game_date": "2025-12-05", "home_team_id": "NYK", "away_team_id": "UTA", "home_score": 146, "away_score": 112} |
| exact_statistics-011: What was the Knicks lowest-scoring game? | answer | archive — game_score: {"nba_game_id": "0022500742", "game_date": "2026-02-06", "home_team_id": "DET", "away_team_id": "NYK", "home_score": 118, "away_score": 80} |
| exact_statistics-012: How many games did the Knicks score at least 120? | answer | archive — game_count: 37 |
| exact_statistics-013: How many games did the Knicks hold opponents under 100? | answer | archive — game_count: 26 |
| exact_statistics-014: What was Jalen Brunson's scoring average? | answer | archive — Jalen Brunson: average points: 26.5161 |
| exact_statistics-015: How many total points did Jalen Brunson score? | answer | archive — Jalen Brunson: total points: 2466 |
| exact_statistics-016: What was Karl-Anthony Towns' rebounding average? | answer | archive — Karl-Anthony Towns: average rebounds: 11.5957 |
| exact_statistics-017: How many double-doubles did Towns have? | answer | archive — Karl-Anthony Towns: double_doubles points: 68 |
| exact_statistics-018: Who led the Knicks in assists? | answer | archive — assists leader: {"name": "Jalen Brunson", "total": 618} |
| exact_statistics-019: Who led the Knicks in rebounds? | answer | archive — rebounds leader: {"name": "Karl-Anthony Towns", "total": 1090} |
| exact_statistics-020: Who led the Knicks in steals? | answer | archive — steals leader: {"name": "OG Anunoby", "total": 130} |
| exact_statistics-021: What was Mikal Bridges' three-point percentage? | answer | archive — Mikal Bridges: percentage three_pointers_made: 37.06 |
| exact_statistics-022: How many games did Josh Hart start? | answer | archive — Josh Hart: starts starter: 71 |
| exact_statistics-023: What was OG Anunoby's scoring average? | answer | archive — OG Anunoby: average points: 17.381 |
| exact_statistics-024: What was the Knicks record against Boston? | answer | BOS — games: 4; BOS — wins: 3; BOS — losses: 1 |
| exact_statistics-025: How many points per game did the Knicks allow? | answer | archive — points_allowed_per_game: 108.396 |
| date_range_last_n-001: What was the Knicks record in their last 5 games? | answer | archive — games: 5; archive — wins: 4; archive — losses: 1 |
| date_range_last_n-002: How many points did the Knicks average in their last 10 games? | answer | archive — points_per_game: 114.1 |
| date_range_last_n-003: What was Brunson's scoring average over his last 5 games? | answer | last appearances — Jalen Brunson: average points: 32.6 |
| date_range_last_n-004: How did the Knicks perform from January 1 through January 31? | answer | January 2026 — games: 15; January 2026 — wins: 7; January 2026 — losses: 8 |
| date_range_last_n-005: What was their record after the All-Star break? | answer | after February 15, 2026 (including postseason) — games: 46; after February 15, 2026 (including postseason) — wins: 34; after February 15, 2026 (including postseason) — losses: 12 |
| date_range_last_n-006: How many road games did they win in December? | answer | December road games — wins: 5 |
| date_range_last_n-007: What was their average margin over the last 8 games? | answer | archive — average_margin: 9.75 |
| date_range_last_n-008: Who led the team in scoring over the last 3 games? | answer | archive — points leader: {"name": "Jalen Brunson", "total": 113} |
| date_range_last_n-009: How many games did they play between March 1 and March 15? | answer | archive — game_count: 9 |
| date_range_last_n-010: What was their record in the first 10 games? | answer | archive — games: 10; archive — wins: 7; archive — losses: 3 |
| date_range_last_n-011: How many points did Towns average in his last 7 games? | answer | last appearances — Karl-Anthony Towns: average points: 13.8571 |
| date_range_last_n-012: What was the defense like over the last 5 games by points allowed? | answer | archive — points_allowed_per_game: 102.0 |
| date_range_last_n-013: What was their record over the final 15 regular-season games? | answer | archive — games: 15; archive — wins: 11; archive — losses: 4 |
| date_range_last_n-014: How many back-to-backs did they win in February? | clarify | Back-to-back wins may mean winning the second night or sweeping both games. Both canonical counts supplied; ask which definition is intended. |
| date_range_last_n-015: Compare their January record with their February record. | answer | January 2026 — games: 15; January 2026 — wins: 7; January 2026 — losses: 8; February 2026 — games: 12; February 2026 — wins: 8; February 2026 — losses: 4 |
| comparisons-001: Compare the Knicks' offense at home and on the road. | answer | home — points_per_game: 118.2041; away — points_per_game: 114.5769 |
| comparisons-002: Compare Brunson and Towns as scorers this season. | answer | archive — Jalen Brunson: average points: 26.5161; archive — Karl-Anthony Towns: average points: 19.2128 |
| comparisons-003: Did the Knicks play better against Boston or Toronto? | answer | BOS — games: 4; BOS — wins: 3; BOS — losses: 1; BOS — average_margin: 8.0; TOR — games: 5; TOR — wins: 5; TOR — losses: 0; TOR — average_margin: 19.6 |
| comparisons-004: Compare their first 10 games with their last 10 games. | answer | first 10 games — games: 10; first 10 games — wins: 7; first 10 games — losses: 3; last 10 games — games: 10; last 10 games — wins: 9; last 10 games — losses: 1 |
| comparisons-005: Compare wins and losses by average turnover count. | answer | wins — turnovers_per_game: 11.971; losses — turnovers_per_game: 14.2812 |
| comparisons-006: Was the bench more productive in home or away games? | answer | home — bench_points_per_team_game: 32.1224; away — bench_points_per_team_game: 29.8846 |
| comparisons-007: Compare the two Knicks games against Boston. | clarify | Archive contains 4 Boston games, not two. Request the intended dates or compare all four explicitly. |
| comparisons-008: Who had the better rebounding season, Towns or Hart? | answer | archive — Karl-Anthony Towns: average rebounds: 11.5957; archive — Josh Hart: average rebounds: 7.7176 |
| comparisons-009: Compare the Knicks' third-quarter and fourth-quarter scoring. | answer | quarter 3 — period_points_per_game: 29.0198; quarter 4 — period_points_per_game: 27.8911 |
| comparisons-010: Did the Knicks shoot better in wins or losses? | answer | wins — field_goal_percentage: 49.7461; losses — field_goal_percentage: 44.1632 |
| comparisons-011: Compare Bridges' scoring before and after the All-Star break. | answer | before All-Star break — Mikal Bridges: average points: 15.9273; after All-Star break including postseason — Mikal Bridges: average points: 12.1957 |
| comparisons-012: Which was stronger: the Knicks offense or defense? | clarify | Define strength against a league benchmark or rating; archive points alone do not establish relative offense versus defense strength. |
| comparisons-013: Compare close games with blowouts. | clarify | Define close-game and blowout margin thresholds before comparing; no threshold is stated in the question. |
| comparisons-014: Did the Knicks fare better against Eastern or Western teams? | answer | East — games: 66; East — wins: 47; East — losses: 19; East — average_margin: 9.7424; West — games: 35; West — wins: 22; West — losses: 13; West — average_margin: 4.5429 |
| comparisons-015: Compare Brunson's last 5 games with his season average. | answer | last 5 appearances — Jalen Brunson: average points: 32.6; season appearances — Jalen Brunson: average points: 26.5161 |
| single_game_narrative-001: How did the Knicks lose the lead against Boston? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-002: What decided the Knicks game against Toronto? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-003: Walk me through the fourth quarter against Atlanta. | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-004: Why did the Knicks win the Chicago game? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-005: What changed after halftime against Charlotte? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-006: Tell the story of the closest Knicks game. | clarify | Multiple games tie for smallest final margin; ask which date. |
| single_game_narrative-007: How did Brunson influence the Boston game? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-008: What were the decisive possessions against Toronto? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-009: How did the Knicks close the Atlanta game? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-010: Why did the Knicks offense stall against Chicago? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-011: What did Towns do in the biggest win? | answer | archive — Karl-Anthony Towns: total points: 14; archive — Karl-Anthony Towns: total rebounds: 8; archive — Karl-Anthony Towns: total assists: 3; archive — game_score: {"nba_game_id": "0022500622", "game_date": "2026-01-21", "home_team_id": "NYK", "away_team_id": "BKN", "home_score": 120, "away_score": 66} |
| single_game_narrative-012: Which plays swung the Charlotte game? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-013: How did the bench affect the Toronto game? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-014: What happened in the final two minutes against Boston? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-015: Explain the Knicks' best defensive game. | answer | archive — game_score: {"nba_game_id": "0022500622", "game_date": "2026-01-21", "home_team_id": "NYK", "away_team_id": "BKN", "home_score": 120, "away_score": 66} |
| single_game_narrative-016: How did turnovers shape the Atlanta game? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-017: What happened immediately after the Knicks took the lead against Chicago? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-018: Describe the Knicks' worst third quarter. | clarify | Worst third quarter may mean fewest scored or worst net margin. Specify the metric before calling one worst. |
| single_game_narrative-019: How did the Knicks answer Toronto's late run? | clarify | No unique game/date is identified. Request a date and avoid treating a narrative premise as proven. |
| single_game_narrative-020: What was the key sequence in the Boston loss? | clarify | Game identity is unique, but causal/decisive premise needs qualification. Use corrected report interval as a descriptive example, not causal proof. |
| turning_points-001: What was the Knicks' biggest scoring run against Boston? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-002: Where did the Toronto game turn? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-003: When did the Knicks collapse against Atlanta? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-004: What run broke open the Chicago game? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-005: How did the Knicks erase their largest deficit? | clarify | Specify comeback/run boundaries and whether biggest means unanswered points, net margin or duration. Corrected report intervals use an explicit three-minute bound and cannot establish an unrestricted season superlative. |
| turning_points-006: Which drought cost the Knicks the Boston game? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-007: What was the most damaging opponent run this season? | clarify | Specify comeback/run boundaries and whether biggest means unanswered points, net margin or duration. Corrected report intervals use an explicit three-minute bound and cannot establish an unrestricted season superlative. |
| turning_points-008: When did the Knicks lose control against Charlotte? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-009: What sequence started the comeback against Toronto? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| turning_points-010: Which late-game possessions were the turning point against Atlanta? | clarify | Specify the game and scoring-run definition. A selected bounded scoreboard interval does not prove a causal turning point, collapse or drought that cost the game. |
| follow_ups-001: What happened next? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-002: Why was that stretch decisive? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-003: Who was on the floor then? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval.; Exact on-court lineup needs validated substitution reconstruction; player box-score participation is not lineup evidence. |
| follow_ups-004: How long did that run last? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-005: Did they recover after that? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-006: What did Brunson do during it? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-007: Show me the receipts for that. | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-008: Was that their worst stretch? | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-009: Compare that with the other Boston game. | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| follow_ups-010: Tell me more about the final possession. | clarify | Supplied conversation does not pin a game, event interval or valid evidence. The assistant's asserted decisive Boston run is not canonical proof. Ask for a game/date or cited interval. |
| aliases_typos-001: How did NYK do vs BOS? | answer | BOS — games: 4; BOS — wins: 3; BOS — losses: 1 |
| aliases_typos-002: What happened agianst the Celts? | clarify | Typo/alias is understandable, but multiple matching opponent games require a date. |
| aliases_typos-003: How did JB play in that game? | clarify | JB resolves to Jalen Brunson, but 'that game' has no provided context. |
| aliases_typos-004: Tell me about KAT vs the Raps. | answer | archive — Karl-Anthony Towns: average points: 17.4 |
| aliases_typos-005: What was the Knics biggest run? | clarify | Typo is understandable; define scoring run or collapse before choosing a season-wide superlative. |
| aliases_typos-006: How did they do v ATL? | answer | ATL — games: 9; ATL — wins: 6; ATL — losses: 3 |
| aliases_typos-007: What happened in the 4Q against CHI? | clarify | Typo/alias is understandable, but multiple matching opponent games require a date. |
| aliases_typos-008: Did Mikal play well aginst Toronto? | answer | archive — Mikal Bridges: average points: 16.6 |
| aliases_typos-009: How did OG look vs the C's? | answer | archive — OG Anunoby: average points: 11.5 |
| aliases_typos-010: What was NY's worst collpase? | clarify | Typo is understandable; define scoring run or collapse before choosing a season-wide superlative. |
| unsupported-001: What is the live score tonight? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-002: Will the Knicks win their next game? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-003: Who is injured today? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-004: What trade should the Knicks make tomorrow? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-005: Show possessions from 2099-01-01. | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-006: What are the current Eastern Conference standings? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-007: Did the Knicks win yesterday? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-008: How will Brunson play next season? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
| unsupported-009: What happened in the Lakers game? | clarify | Lakers is an archived opponent with two games. This is ambiguous, not unsupported solely because it names Lakers. |
| unsupported-010: Which Boston game do you mean? | clarify | No prior game selection exists in the supplied context. List the archived Boston dates and ask which. |
| unsupported-011: Was that a good game? | clarify | Missing game, player, time period or evaluation metric. Ask for the intended scope; generic language alone does not prove an out-of-archive request. |
| unsupported-012: What was the score? | clarify | Missing game, player, time period or evaluation metric. Ask for the intended scope; generic language alone does not prove an out-of-archive request. |
| unsupported-013: Who was better? | clarify | Missing game, player, time period or evaluation metric. Ask for the intended scope; generic language alone does not prove an out-of-archive request. |
| unsupported-014: Explain their defense. | clarify | Missing game, player, time period or evaluation metric. Ask for the intended scope; generic language alone does not prove an out-of-archive request. |
| unsupported-015: What is the best betting line for tonight? | refuse | Outside the immutable 2025-26 archive: no live, future, injury, trade, betting or out-of-range evidence. Do not invent current facts. |
