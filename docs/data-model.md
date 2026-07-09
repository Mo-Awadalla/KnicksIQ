# Data Model

This document describes the canonical schema KnicksIQ uses to store
NBA data. Production runs on PostgreSQL; tests run on SQLite. Both
share the same SQLAlchemy models.

## Tables

### `teams`

| Column         | Type         | Notes                          |
| -------------- | ------------ | ------------------------------ |
| id             | varchar(8)   | Primary key, e.g. `NYK`        |
| nba_team_id    | int          | Unique, NBA's internal id      |
| name           | varchar(100) | e.g. "Knicks"                  |
| city           | varchar(100) | e.g. "New York"                |
| abbreviation   | varchar(8)   | e.g. "NYK"                     |
| conference     | varchar(16)  | "East" / "West"                |
| division       | varchar(32)  | e.g. "Atlantic"                |
| created_at     | timestamptz  |                                |
| updated_at     | timestamptz  |                                |

### `players`

| Column         | Type         | Notes                          |
| -------------- | ------------ | ------------------------------ |
| id             | int          | Primary key                    |
| nba_player_id  | int          | Unique                         |
| full_name      | varchar(128) |                                |
| team_id        | varchar(8)   | FK → teams.id, nullable        |
| position       | varchar(8)   | PG / SG / SF / PF / C          |
| jersey_number  | varchar(8)   |                                |
| created_at     | timestamptz  |                                |
| updated_at     | timestamptz  |                                |

### `games`

| Column         | Type         | Notes                                  |
| -------------- | ------------ | -------------------------------------- |
| id             | int          | Primary key                            |
| nba_game_id    | varchar(32)  | Unique, NBA's id (e.g. `0022400001`)   |
| season         | varchar(16)  | e.g. `2024-25`                         |
| game_date      | date         |                                        |
| home_team_id   | varchar(8)   | FK → teams.id                          |
| away_team_id   | varchar(8)   | FK → teams.id                          |
| home_score     | int          | Default 0                              |
| away_score     | int          | Default 0                              |
| status         | enum         | scheduled / live / final / postponed  |
| created_at     | timestamptz  |                                        |
| updated_at     | timestamptz  |                                        |

### `game_events`

| Column            | Type         | Notes                                       |
| ----------------- | ------------ | ------------------------------------------- |
| id                | int          | Primary key                                 |
| game_id           | int          | FK → games.id, CASCADE                      |
| sequence          | int          | 1-indexed position in the game              |
| period            | int          | 1-4 (regulation)                            |
| clock             | varchar(8)   | e.g. `8:41`                                 |
| team_id           | varchar(8)   | FK → teams.id, nullable (neutral events)    |
| player_id         | int          | FK → players.id, nullable                   |
| event_type        | enum         | 11 canonical event types                    |
| description       | varchar(512) | Original play text                          |
| home_score        | int          | Score after the event                       |
| away_score        | int          | Score after the event                       |
| score_margin      | int          | home - away                                 |
| shot_type         | enum         | 2pt / 3pt / ft / unknown, nullable          |
| shot_result       | enum         | made / missed, nullable                     |
| shot_distance_ft  | int          | Nullable                                    |
| created_at        | timestamptz  |                                             |
| updated_at        | timestamptz  |                                             |

Index: `(game_id, period, sequence)` for fast PBP reads.

### `scoring_runs` (precomputed)

| Column         | Type         | Notes                                  |
| -------------- | ------------ | -------------------------------------- |
| id             | int          | Primary key                            |
| game_id        | int          | FK → games.id, CASCADE                 |
| team_id        | varchar(8)   | FK → teams.id                          |
| period         | int          |                                        |
| start_sequence | int          | First event in the run                 |
| end_sequence   | int          | Last event in the run                  |
| start_clock    | varchar(8)   |                                        |
| end_clock      | varchar(8)   |                                        |
| points_for     | int          |                                        |
| points_against | int          |                                        |
| score_delta    | int          | points_for - points_against            |
| event_count    | int          |                                        |
| summary        | text         | Templated description                  |

Index: `(game_id, period)` for run queries.

### `bad_stretches` (precomputed)

| Column              | Type         | Notes                                  |
| ------------------- | ------------ | -------------------------------------- |
| id                  | int          | Primary key                            |
| game_id             | int          | FK → games.id, CASCADE                 |
| period              | int          |                                        |
| start_clock         | varchar(8)   |                                        |
| end_clock           | varchar(8)   |                                        |
| score_delta         | int          | Knicks POV (negative = bad)            |
| summary             | text         |                                        |
| likely_causes       | text         | JSON list of strings                   |
| knicks_turnovers    | int          |                                        |
| knicks_missed_shots | int          |                                        |
| opponent_fast_breaks| int          |                                        |

### `jobs`

| Column         | Type         | Notes                                |
| -------------- | ------------ | ------------------------------------ |
| id             | varchar(64)  | Primary key (uuid4 hex)              |
| job_type       | varchar(64)  | ingest_games / detect_runs / etc.    |
| status         | enum         | queued / started / finished / failed |
| queue          | varchar(64)  | RQ queue name                        |
| enqueued_by    | varchar(64)  | User/system id, nullable             |
| payload_json   | text         | Job input parameters                 |
| result_json    | text         | Job output, nullable                 |
| error_message  | text         | Set on failure                       |
| enqueued_at    | timestamptz  |                                      |
| started_at     | timestamptz  | Nullable                             |
| finished_at    | timestamptz  | Nullable                             |
| worker_name    | varchar(128) | hostname + worker id                 |

### `reports`

| Column                 | Type         | Notes                          |
| ---------------------- | ------------ | ------------------------------ |
| id                     | int          | Primary key                    |
| game_id                | int          | FK → games.id, CASCADE         |
| report_type            | varchar(64)  | `postgame`                     |
| title                  | varchar(256) |                                |
| summary                | text         |                                |
| turning_point          | text         |                                |
| best_stretch           | text         |                                |
| worst_stretch          | text         |                                |
| player_notes           | text         | JSON list of strings           |
| suggested_adjustments  | text         | JSON list of strings           |
| sources_json           | text         | JSON array of source records   |
| tool_trace_json        | text         | JSON array of tool-call records |

### `documents` and `chunks` (RAG)

`documents` represents a piece of source material (game recap, PBP
summary, etc.) and `chunks` are smaller pieces suitable for embedding
and retrieval. Phase 5 stores the chunk text and a JSON-serialized
embedding (placeholder); a future phase swaps in pgvector.

## Relationships

```
teams ──┬── players
        │
        └── games ──┬── game_events
                    ├── scoring_runs
                    ├── bad_stretches
                    └── reports
                          │
                          └── sources → { chunks → documents }

jobs (no FK; references games/game_id by id stored in payload_json)
```

## Conventions

- `id` columns are integers, except for `teams.id` and `jobs.id`
  which are strings (team abbreviations and UUIDs respectively).
- All `created_at` / `updated_at` columns are timezone-aware
  timestamps.
- Foreign keys with `ON DELETE CASCADE` ensure child rows go away
  with their parent. The exception is `jobs`, which has no FK — it
  is a log of work, not a domain entity.
- The `payload_json` and `result_json` columns are denormalized on
  purpose: they let the API serve job status without joining tables
  and they survive schema evolution.
