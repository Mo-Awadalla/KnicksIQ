"""CI migration commands against disposable local PostgreSQL only."""
import os
import subprocess
from pathlib import Path

out=Path(__file__).resolve().parent
base=['/opt/homebrew/opt/postgresql@16/bin/psql','-h','127.0.0.1','-p','55440','-U','mohamedawadalla','-v','ON_ERROR_STOP=1']
with (out/'migration-ci.txt').open('w') as log:
    def run(args, env=None): subprocess.run(args,env=env,check=True,stdout=log,stderr=log)
    for name in ['ci_empty','ci_legacy']:
        run(['/opt/homebrew/opt/postgresql@16/bin/createdb','-h','127.0.0.1','-p','55440',name])
    def migrate(db, direction, target):
        run(['uv','run','alembic',direction,target],{**os.environ,'DB_URL':f'postgresql+asyncpg://mohamedawadalla@127.0.0.1:55440/{db}','TEST_MODE':'false','UV_CACHE_DIR':'/tmp/knicksiq-uv-cache'})
    migrate('ci_empty','upgrade','head');migrate('ci_empty','downgrade','base');migrate('ci_empty','upgrade','head')
    run(base+['-d','ci_legacy','-f','migrations/fixtures/pre_alembic_minimal.sql'])
    migrate('ci_legacy','upgrade','head')
    sql="""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM reports WHERE title='Legacy report' AND reviewed=false) THEN RAISE EXCEPTION 'Missing preserved legacy report'; END IF; END $$;
INSERT INTO dataset_releases (version,season,source,manifest_sha256,manifest_json,validation_json,validation_passed,status) VALUES ('migration-test','2025-26','fixture',repeat('a',64),'{}','{}',true,'staged');
INSERT INTO games (nba_game_id,season,game_date,home_team_id,away_team_id,home_score,away_score,status,season_type,data_status,release_id) SELECT nba_game_id,season,game_date,home_team_id,away_team_id,home_score,away_score,status,season_type,data_status,(SELECT id FROM dataset_releases WHERE version='migration-test') FROM games WHERE nba_game_id='legacy-game' AND release_id IS NULL;"""
    run(base+['-d','ci_legacy','-c',sql])
print('Empty/legacy migration, expand-only rollback, and preserved legacy rows passed.')
