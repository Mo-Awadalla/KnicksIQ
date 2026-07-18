"""Add authoritative structured player analytics views.

Revision ID: 0005_player_analytics_views
Revises: 0004_archive_full_text
"""

from __future__ import annotations

from alembic import op

revision = "0005_player_analytics_views"
down_revision = "0004_archive_full_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW player_game_statistics AS
        SELECT pgs.*, g.game_date, g.season, g.season_type,
          CASE WHEN pgs.team_id = g.home_team_id THEN g.away_team_id
               ELSE g.home_team_id END AS opponent_id,
          CASE WHEN pgs.team_id = g.home_team_id THEN 'home' ELSE 'away' END AS home_away,
          CASE WHEN
            (CASE WHEN pgs.team_id = g.home_team_id THEN g.home_score ELSE g.away_score END)
            >
            (CASE WHEN pgs.team_id = g.home_team_id THEN g.away_score ELSE g.home_score END)
            THEN 'W' ELSE 'L' END AS game_result
        FROM player_game_stats pgs JOIN games g ON g.id = pgs.game_id
        """
    )
    op.execute(
        """
        CREATE VIEW team_game_statistics AS
        SELECT tgs.*, g.game_date, g.season, g.season_type,
          CASE WHEN tgs.team_id = g.home_team_id THEN g.away_team_id
               ELSE g.home_team_id END AS opponent_id,
          CASE WHEN tgs.team_id = g.home_team_id THEN 'home' ELSE 'away' END AS home_away
        FROM team_game_stats tgs JOIN games g ON g.id = tgs.game_id
        """
    )
    op.execute(
        """
        CREATE VIEW rolling_player_statistics AS
        SELECT pgs.*,
          AVG(points) OVER (
            PARTITION BY release_id, player_id ORDER BY game_date, game_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
          ) AS points_last_five_average,
          AVG(rebounds) OVER (
            PARTITION BY release_id, player_id ORDER BY game_date, game_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
          ) AS rebounds_last_five_average,
          AVG(assists) OVER (
            PARTITION BY release_id, player_id ORDER BY game_date, game_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
          ) AS assists_last_five_average
        FROM player_game_statistics pgs
        """
    )
    op.execute(
        """
        CREATE VIEW player_period_statistics AS
        SELECT g.release_id, ge.game_id, ge.player_id, ge.team_id, ge.period,
          SUM(CASE
            WHEN ge.event_type = 'made_shot' AND ge.shot_type = '3pt' THEN 3
            WHEN ge.event_type = 'made_shot' THEN 2
            WHEN ge.event_type = 'free_throw' AND ge.shot_result = 'made' THEN 1
            ELSE 0 END) AS points
        FROM game_events ge JOIN games g ON g.id = ge.game_id
        WHERE ge.player_id IS NOT NULL
        GROUP BY g.release_id, ge.game_id, ge.player_id, ge.team_id, ge.period
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS player_period_statistics")
    op.execute("DROP VIEW IF EXISTS rolling_player_statistics")
    op.execute("DROP VIEW IF EXISTS team_game_statistics")
    op.execute("DROP VIEW IF EXISTS player_game_statistics")
