-- Populated legacy tables needed to exercise the expand-only upgrade path.
CREATE TABLE teams (
    id VARCHAR(8) PRIMARY KEY,
    nba_team_id INTEGER NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    abbreviation VARCHAR(8) NOT NULL UNIQUE,
    conference VARCHAR(16),
    division VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE games (
    id SERIAL PRIMARY KEY,
    nba_game_id VARCHAR(32) NOT NULL,
    season VARCHAR(16) NOT NULL,
    game_date DATE NOT NULL,
    home_team_id VARCHAR(8) NOT NULL REFERENCES teams(id),
    away_team_id VARCHAR(8) NOT NULL REFERENCES teams(id),
    home_score INTEGER NOT NULL DEFAULT 0,
    away_score INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL,
    season_type VARCHAR(16) NOT NULL,
    data_status VARCHAR(32) NOT NULL,
    source_name VARCHAR(64),
    source_url VARCHAR(512),
    source_game_id VARCHAR(64),
    source_fetched_at TIMESTAMPTZ,
    source_payload_hash VARCHAR(128),
    game_label VARCHAR(128),
    series_name VARCHAR(128),
    series_game_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ix_games_nba_game_id ON games (nba_game_id);

CREATE TABLE game_events (
    id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    period INTEGER NOT NULL,
    clock VARCHAR(8) NOT NULL,
    team_id VARCHAR(8) REFERENCES teams(id),
    player_id INTEGER,
    event_type VARCHAR(32) NOT NULL,
    description VARCHAR(512) NOT NULL DEFAULT '',
    home_score INTEGER NOT NULL DEFAULT 0,
    away_score INTEGER NOT NULL DEFAULT 0,
    score_margin INTEGER NOT NULL DEFAULT 0,
    shot_type VARCHAR(16),
    shot_result VARCHAR(16),
    shot_distance_ft INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    report_type VARCHAR(64) NOT NULL DEFAULT 'postgame',
    title VARCHAR(256) NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    turning_point TEXT NOT NULL DEFAULT '',
    best_stretch TEXT NOT NULL DEFAULT '',
    worst_stretch TEXT NOT NULL DEFAULT '',
    player_notes TEXT NOT NULL DEFAULT '[]',
    suggested_adjustments TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    tool_trace_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(32) NOT NULL,
    title VARCHAR(256) NOT NULL,
    body TEXT NOT NULL,
    game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
    team_id VARCHAR(8) REFERENCES teams(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO teams (id, nba_team_id, name, city, abbreviation)
VALUES ('NYK', 1610612752, 'Knicks', 'New York', 'NYK'),
       ('BOS', 1610612738, 'Celtics', 'Boston', 'BOS');
INSERT INTO games (
    nba_game_id, season, game_date, home_team_id, away_team_id,
    home_score, away_score, status, season_type, data_status
) VALUES (
    'legacy-game', '2025-26', '2026-01-01', 'NYK', 'BOS',
    100, 90, 'final', 'regular', 'events_ready'
);
INSERT INTO reports (game_id, title, summary)
VALUES (1, 'Legacy report', 'Legacy report survives migration.');
INSERT INTO documents (source_type, title, body, game_id, team_id)
VALUES ('play_by_play', 'Legacy document', 'Legacy document survives migration.', 1, 'NYK');
