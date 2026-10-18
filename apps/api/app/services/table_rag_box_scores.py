"""Table rag box scores."""

from __future__ import annotations

import re

from app.models.box_score import PeriodScore, PlayerGameStat, TeamGameStat
from app.models.game import Game
from app.models.player import Player
from app.services.table_rag_types import TableRagResult, _game_evidence
from app.services.team_scope import score_summary
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_STAT_TERMS = {
    "points": "points",
    "scoring": "points",
    "rebounds": "rebounds",
    "rebound": "rebounds",
    "assists": "assists",
    "assist": "assists",
    "turnovers": "turnovers",
    "turnover": "turnovers",
    "steals": "steals",
    "steal": "steals",
    "blocks": "blocks",
    "block": "blocks",
}


def _requested_stat(question: str) -> str | None:
    q = question.lower()
    return next((column for term, column in _STAT_TERMS.items() if term in q), None)


async def _answer_box_score_question(
    db: AsyncSession,
    question: str,
    season: str,
    games: list[Game],
) -> TableRagResult | None:
    """Authoritative SQL for facts that require complete box-score tables."""
    q = question.lower()
    stat = _requested_stat(question)
    game_ids = [game.id for game in games]
    if not game_ids:
        return None
    evidence = [_game_evidence(game) for game in games]

    if (
        stat
        and "beat the knicks" not in q
        and any(term in q for term in ("who led", "leader", "most", "which player"))
    ):
        stat_column = getattr(PlayerGameStat, stat)
        row = (
            await db.execute(
                select(Player.full_name, func.sum(stat_column).label("total"))
                .join(PlayerGameStat, PlayerGameStat.player_id == Player.id)
                .where(
                    PlayerGameStat.game_id.in_(game_ids),
                    PlayerGameStat.team_id == "NYK",
                )
                .group_by(Player.id, Player.full_name)
                .order_by(func.sum(stat_column).desc(), Player.full_name)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return TableRagResult(
                answer=f"No complete player {stat} facts are available for {season}.",
                evidence=evidence,
                warnings=["Complete player box scores are unavailable."],
            )
        return TableRagResult(
            answer=(
                f"{row.full_name} led the Knicks with {int(row.total)} total {stat} in {season}."
            ),
            evidence=evidence,
            warnings=[],
        )

    if "quarter" in q or any(f"q{period}" in q for period in range(1, 5)):
        period_names = {1: "first", 2: "second", 3: "third", 4: "fourth"}
        normalized = q.replace("-", " ")
        requested_periods = [
            period
            for period in range(1, 5)
            if re.search(
                rf"\b(?:q{period}|{period}(?:st|nd|rd|th)? quarter|"
                rf"{period_names[period]} quarter)\b",
                normalized,
            )
        ]
        stmt = select(PeriodScore.period, func.sum(PeriodScore.points), func.count()).where(
            PeriodScore.game_id.in_(game_ids), PeriodScore.team_id == "NYK"
        )
        if requested_periods:
            stmt = stmt.where(PeriodScore.period.in_(requested_periods))
        rows = (
            await db.execute(stmt.group_by(PeriodScore.period).order_by(PeriodScore.period))
        ).all()
        if not rows:
            return None
        totals = ", ".join(
            f"Q{period}: {int(points)} total points "
            f"({points / count:.1f} per game across {count} games)"
            for period, points, count in rows
        )
        return TableRagResult(
            answer=f"Knicks quarter scoring across available {season} games — {totals}.",
            evidence=evidence,
            warnings=[],
        )

    if "bench" in q:
        total = (
            await db.execute(
                select(func.sum(PlayerGameStat.points)).where(
                    PlayerGameStat.game_id.in_(game_ids),
                    PlayerGameStat.team_id == "NYK",
                    PlayerGameStat.starter.is_(False),
                )
            )
        ).scalar_one()
        if total is None:
            return None
        return TableRagResult(
            answer=(
                f"The Knicks bench scored {int(total)} total points across "
                f"available {season} games."
            ),
            evidence=evidence,
            warnings=[],
        )

    if any(term in q for term in ("shooting split", "from three", "three-point", "free throw")):
        made_attempted = (
            await db.execute(
                select(
                    func.sum(TeamGameStat.field_goals_made),
                    func.sum(TeamGameStat.field_goals_attempted),
                    func.sum(TeamGameStat.three_pointers_made),
                    func.sum(TeamGameStat.three_pointers_attempted),
                    func.sum(TeamGameStat.free_throws_made),
                    func.sum(TeamGameStat.free_throws_attempted),
                ).where(TeamGameStat.game_id.in_(game_ids), TeamGameStat.team_id == "NYK")
            )
        ).one()
        if made_attempted[1] is None:
            return None

        def pct(made: int, attempted: int) -> float:
            return 100 * made / attempted if attempted else 0.0

        fg_m, fg_a, three_m, three_a, ft_m, ft_a = map(int, made_attempted)
        return TableRagResult(
            answer=(
                f"Across available {season} games, NYK shot {fg_m}/{fg_a} "
                f"({pct(fg_m, fg_a):.1f}%) overall, {three_m}/{three_a} "
                f"({pct(three_m, three_a):.1f}%) from three, and {ft_m}/{ft_a} "
                f"({pct(ft_m, ft_a):.1f}%) at the line."
            ),
            evidence=evidence,
            warnings=[],
        )

    if stat and any(term in q for term in ("average", "total", "how many", "per game")):
        stat_column = getattr(TeamGameStat, stat)
        total = (
            await db.execute(
                select(func.sum(stat_column)).where(
                    TeamGameStat.game_id.in_(game_ids), TeamGameStat.team_id == "NYK"
                )
            )
        ).scalar_one()
        if total is None:
            return None
        total_value = int(total)
        if "average" in q or "per game" in q:
            answer = (
                f"The Knicks averaged {total_value / len(games):.1f} {stat} per game "
                f"in available {season} games."
            )
        else:
            answer = f"The Knicks recorded {total_value} total {stat} in available {season} games."
        return TableRagResult(answer=answer, evidence=evidence, warnings=[])
    return None


async def _answer_team_comparison(
    db: AsyncSession, question: str, groups: list[tuple[str, list[Game]]]
) -> TableRagResult:
    q = question.lower()
    games_by_id = {game.id: game for _, games in groups for game in games}
    evidence = [_game_evidence(game) for game in games_by_id.values()]
    answers: list[str] = []
    for label, games in groups:
        if not games:
            answers.append(f"{label}: no matching games.")
            continue
        ids = [game.id for game in games]
        if "bench" in q:
            count, points = (
                await db.execute(
                    select(func.count(), func.sum(PlayerGameStat.points)).where(
                        PlayerGameStat.game_id.in_(ids),
                        PlayerGameStat.team_id == "NYK",
                        PlayerGameStat.starter.is_(False),
                    )
                )
            ).one()
            answers.append(
                (
                    f"{label}: {int(points or 0)} bench points, "
                    f"{float(points or 0) / len(games):.1f} per game across {len(games)} games."
                )
                if count
                else f"{label}: no bench box-score data."
            )
        elif "turnover" in q or "shoot" in q:
            rows = list(
                (
                    await db.execute(
                        select(TeamGameStat).where(
                            TeamGameStat.game_id.in_(ids), TeamGameStat.team_id == "NYK"
                        )
                    )
                ).scalars()
            )
            if len(rows) != len(games):
                answers.append(f"{label}: complete team box scores are unavailable.")
            elif "turnover" in q:
                total = sum(row.turnovers or 0 for row in rows)
                answers.append(
                    f"{label}: {total / len(rows):.1f} turnovers per game "
                    f"({total} across {len(rows)} games)."
                )
            else:
                made = sum(row.field_goals_made or 0 for row in rows)
                attempts = sum(row.field_goals_attempted or 0 for row in rows)
                answers.append(
                    f"{label}: {100 * made / attempts:.1f}% field-goal shooting "
                    f"({made}/{attempts})."
                    if attempts
                    else f"{label}: no field-goal attempts."
                )
        else:
            answers.append(score_summary(label, games))
    return TableRagResult(
        answer="Knicks comparison\n" + "\n".join(answers), evidence=evidence, warnings=[]
    )
