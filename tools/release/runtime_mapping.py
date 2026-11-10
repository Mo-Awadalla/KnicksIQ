"""Read-only verification of the approved bundle against the isolated local restore.

Every canonical row must still exist under one release with the same related NBA
identities. It selects rows read-only, refuses any database that is not on
loopback, and never imports, loads or activates a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
API_ROOT = REPO / "apps" / "api"

# A developer `.env` carries live provider keys, a Sentry DSN and a remote database
# URL. None of it may reach a verifier that only reads one explicit local database.
for _secret in (
    "SENTRY_DSN",
    "REDIS_URL",
    "OPENROUTER_API_KEY",
    "AI_API_KEY",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "ADMIN_API_KEY",
):
    os.environ.pop(_secret, None)
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

from app.models import (  # noqa: E402
    DatasetRelease,
    Game,
    PeriodScore,
    Player,
    PlayerGameStat,
    TeamGameStat,
)
from app.services.analyst_provenance import canonical_digest as digest  # noqa: E402
from app.services.analyst_provenance import row_receipt  # noqa: E402
from app.services.release_bundle import ReleaseValidationError, read_bundle  # noqa: E402
from runtime_mapping_rows import SqlRow, load_event_rows, verify_rows  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

DEFAULT_BUNDLE = REPO / "release-artifacts/2025-26/reliability-approved-20260928.json.gz"
DEFAULT_APPROVAL = REPO / "docs/release-evidence/report-review-20260928/approved-bundle.json"
DEFAULT_LABELS = REPO / "docs/release-evidence/evaluation-label-review-20260907/labels.jsonl"
OUTPUT_DIR = REPO / "release-artifacts/production-completion-20261030"
DEFAULT_OUTPUT = OUTPUT_DIR / "runtime-mapping.json"
DEFAULT_REPORT = OUTPUT_DIR / "runtime-mapping-verification.json"
SCOPE = (
    "isolated local PostgreSQL restore only; every row verified against the approved "
    "bundle; remote IDs must be remapped after staging"
)
COLLECTION_PREFIX = {
    "games": "game",
    "player_game_stats": "box",
    "team_game_stats": "team_box",
    "period_scores": "period",
    "game_events": "event",
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class VerificationError(ValueError):
    """The verifier cannot run without guessing."""


@dataclass(frozen=True)
class Verification:
    version: str
    release_id: int
    bundle_sha256: str
    problems: tuple[str, ...]
    rows: dict[str, SqlRow]
    players: dict[str, dict[str, Any]]
    counts: dict[str, int]
    verified_label_references: int


def loopback_dsn(value: str) -> URL:
    """Accept only an explicit PostgreSQL DSN that points at this machine."""
    if not value:
        raise VerificationError("--dsn is required; no default is read from settings or .env")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise VerificationError("only an explicit PostgreSQL DSN is supported")
    if (url.host or "").lower() not in LOOPBACK_HOSTS:
        raise VerificationError(f"refusing non-loopback database host {url.host!r}")
    return url.set(drivername="postgresql+asyncpg")


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _projection(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _json_value(getattr(row, field)) for field in fields}


def _related_projection(
    row: Any, fields: tuple[str, ...], game: Game, player: Player | None
) -> dict[str, Any]:
    """A stat row plus the related NBA identities the canonical row is keyed by."""
    projection: dict[str, Any] = {}
    for field in fields:
        if field == "nba_game_id":
            projection[field] = game.nba_game_id
        elif field == "nba_player_id" and player is not None:
            projection[field] = player.nba_player_id
        else:
            projection[field] = _json_value(getattr(row, field))
    return projection


def _canonical(collection: str, bundle_row: dict[str, Any]) -> str:
    prefix = COLLECTION_PREFIX[collection]
    if collection == "games":
        return f"{prefix}:{bundle_row['nba_game_id']}"
    if collection == "player_game_stats":
        return f"{prefix}:{bundle_row['nba_game_id']}:{bundle_row['nba_player_id']}"
    if collection == "team_game_stats":
        return f"{prefix}:{bundle_row['nba_game_id']}:{bundle_row['team_id']}"
    if collection == "period_scores":
        return (
            f"{prefix}:{bundle_row['nba_game_id']}:{bundle_row['team_id']}:{bundle_row['period']}"
        )
    return f"{prefix}:{bundle_row['nba_game_id']}:{bundle_row['sequence']}"


def _expected(
    bundle: dict[str, Any],
) -> tuple[dict[str, dict[str, dict[str, Any]]], list[str]]:
    """Canonical rows per collection, and any duplicate identity inside the bundle."""
    data = bundle.get("data") or {}
    expected: dict[str, dict[str, dict[str, Any]]] = {}
    duplicates: list[str] = []
    for collection in COLLECTION_PREFIX:
        rows: dict[str, dict[str, Any]] = {}
        source_collection = "events" if collection == "game_events" else collection
        for raw in data.get(source_collection) or []:
            canonical = _canonical(collection, raw)
            if canonical in rows:
                duplicates.append(f"{canonical}: duplicate canonical row in bundle")
                continue
            rows[canonical] = raw
        expected[collection] = rows
    return expected, duplicates


def _label_references(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    references: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        for source in json.loads(line).get("canonical_sources") or []:
            references.append((str(source["canonical_id"]), str(source["row_sha256"])))
    return references


async def verify_restore(
    session: AsyncSession,
    bundle: dict[str, Any],
    *,
    label_references: list[tuple[str, str]] | None = None,
) -> Verification:
    """Prove every approved canonical row is the same row in this database."""
    manifest = bundle.get("manifest") or {}
    bundle_sha256 = str(bundle.get("bundle_sha256") or "")
    problems: list[str] = []
    if manifest.get("version"):
        release = (
            await session.execute(
                select(DatasetRelease).where(DatasetRelease.version == manifest["version"])
            )
        ).scalar_one_or_none()
    else:
        releases = list((await session.execute(select(DatasetRelease))).scalars())
        release = releases[0] if len(releases) == 1 else None
        if release is None:
            problems.append("exactly one local release is required to identify the restore")
    if release is None:
        return Verification(
            version=str(manifest.get("version") or ""),
            release_id=0,
            bundle_sha256=bundle_sha256,
            problems=tuple([*problems, "release missing: the bundle version is not restored"]),
            rows={},
            players={},
            counts={},
            verified_label_references=0,
        )
    if bundle_sha256 and release.manifest_sha256 != bundle_sha256:
        problems.append("release manifest sha256 does not match the approved bundle")
    if not release.validation_passed:
        problems.append("release is not marked validation_passed")

    expected, duplicate_rows = _expected(bundle)
    problems.extend(duplicate_rows)
    games = list(
        (await session.execute(select(Game).where(Game.release_id == release.id))).scalars()
    )
    players_by_id = {
        player.id: player for player in (await session.execute(select(Player))).scalars()
    }
    game_by_id = {game.id: game for game in games}

    actual: dict[str, dict[str, list[SqlRow]]] = {name: {} for name in COLLECTION_PREFIX}

    def add(collection: str, canonical: str, row: SqlRow) -> None:
        actual[collection].setdefault(canonical, []).append(row)

    for game in games:
        canonical = f"game:{game.nba_game_id}"
        template = expected["games"].get(canonical)
        projection = _projection(game, tuple(template) if template is not None else tuple())
        add(
            "games",
            canonical,
            SqlRow(canonical, "games", projection, game.id, release.id, game.id, None),
        )

    rows: list[tuple[str, Any]] = [
        ("player_game_stats", row)
        for row in (await session.execute(select(PlayerGameStat))).scalars()
    ]
    rows += [
        ("team_game_stats", row) for row in (await session.execute(select(TeamGameStat))).scalars()
    ]
    rows += [
        ("period_scores", row) for row in (await session.execute(select(PeriodScore))).scalars()
    ]
    for collection, row in rows:
        if row.release_id != release.id:
            continue
        game = game_by_id.get(row.game_id)
        if game is None:
            problems.append(f"{collection}:{row.id}: game {row.game_id} is not in this release")
            continue
        player = None
        if collection == "player_game_stats":
            player = players_by_id.get(row.player_id)
            if player is None:
                problems.append(f"{collection}:{row.id}: player {row.player_id} does not exist")
                continue
            canonical = f"box:{game.nba_game_id}:{player.nba_player_id}"
            player_id: int | None = player.id
        elif collection == "team_game_stats":
            canonical = f"team_box:{game.nba_game_id}:{row.team_id}"
            player_id = None
        else:
            canonical = f"period:{game.nba_game_id}:{row.team_id}:{row.period}"
            player_id = None
        template = expected[collection].get(canonical)
        projection = _related_projection(
            row, tuple(template) if template is not None else tuple(), game, player
        )
        add(
            collection,
            canonical,
            SqlRow(canonical, collection, projection, row.id, row.release_id, game.id, player_id),
        )

    await load_event_rows(session, release.id, game_by_id, actual, problems)

    verified_rows, counts = verify_rows(expected, actual, problems)

    players = _verify_players(bundle, players_by_id, problems)
    verified_references = _verify_labels(label_references or [], verified_rows, problems)

    return Verification(
        version=release.version,
        release_id=release.id,
        bundle_sha256=bundle_sha256,
        problems=tuple(dict.fromkeys(problems)),
        rows=verified_rows if not problems else {},
        players=players,
        counts=counts,
        verified_label_references=verified_references,
    )


def _verify_players(
    bundle: dict[str, Any],
    players_by_id: dict[int, Player],
    problems: list[str],
) -> dict[str, dict[str, Any]]:
    expected = {
        str(row["nba_player_id"]): str(row["full_name"])
        for row in (bundle.get("data") or {}).get("players") or []
    }
    by_nba_id = {player.nba_player_id: player for player in players_by_id.values()}
    lookup: dict[str, dict[str, Any]] = {}
    for nba_player_id, full_name in expected.items():
        player = by_nba_id.get(int(nba_player_id))
        if player is None:
            problems.append(f"player:{nba_player_id}: missing SQL row")
            continue
        if player.full_name != full_name:
            problems.append(
                f"player:{nba_player_id}: field full_name differs "
                f"(sql={player.full_name!r}, bundle={full_name!r})"
            )
            continue
        lookup[nba_player_id] = {"id": player.id, "name": player.full_name}
    for nba_player_id in by_nba_id:
        if str(nba_player_id) not in expected:
            problems.append(f"player:{nba_player_id}: extra SQL row")
    return lookup


def _verify_labels(
    references: list[tuple[str, str]],
    rows: dict[str, SqlRow],
    problems: list[str],
) -> int:
    """Bind each recorded label reference to the row the database actually holds."""
    verified = 0
    for canonical, expected_sha256 in references:
        row = rows.get(canonical)
        if row is None:
            problems.append(f"{canonical}: label reference not mapped")
            continue
        if digest(row.projection) != expected_sha256:
            problems.append(f"{canonical}: label reference hash mismatch")
            continue
        verified += 1
    return verified


def build_mapping_payload(verification: Verification, bundle: dict[str, Any]) -> dict[str, Any]:
    """The mapping in the format ``app.evaluation.mapping.load_mapping`` reads."""
    if verification.problems:
        raise VerificationError("a failed verification never produces a mapping")
    version = verification.version
    rows: dict[str, dict[str, Any]] = {}
    for canonical, row in verification.rows.items():
        runtime_id = (
            int(row.projection["sequence"])
            if row.collection == "game_events"
            else row.player_id or row.row_id
        )
        receipt = row_receipt(version, row.collection, row.game_id, runtime_id)
        rows[canonical] = {
            "collection": row.collection,
            "row_sha256": digest(row.projection),
            "source_row": row.projection,
            "database_row_id": row.row_id,
            "game_id": row.game_id,
            "release_id": row.release_id,
            "runtime_receipt": receipt,
            "player_id": row.player_id,
        }
    return {
        "scope": SCOPE,
        "bundle_sha256": verification.bundle_sha256,
        "version": version,
        "release_id": verification.release_id,
        "verified_source_references": verification.verified_label_references,
        "rows": rows,
        "players": verification.players,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the approved bundle against the isolated local restore, read only."
    )
    parser.add_argument("--dsn", help="explicit loopback PostgreSQL DSN (required)")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--approval", type=Path, default=DEFAULT_APPROVAL)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--expected-sha256", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="verify only; write neither the mapping nor the report",
    )
    return parser


async def _run(url: URL, bundle: dict[str, Any], labels: Path) -> Verification:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                if connection.dialect.name == "postgresql":
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                session = AsyncSession(bind=connection, expire_on_commit=False)
                return await verify_restore(
                    session, bundle, label_references=_label_references(labels)
                )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        url = loopback_dsn(args.dsn or "")
    except VerificationError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if not args.bundle.exists():
        print(f"bundle not found: {args.bundle}", file=sys.stderr)
        return 1
    approved: dict[str, Any] = {}
    if args.approval.exists():
        approved = json.loads(args.approval.read_text(encoding="utf-8"))
    expected = args.expected_sha256 or str(approved.get("sha256") or "")
    if args.expected_sha256 and approved.get("sha256") and expected != approved["sha256"]:
        print("refused: --expected-sha256 disagrees with the approval record", file=sys.stderr)
        return 1
    if not expected:
        print("refused: no approved bundle sha256 is bound to this run", file=sys.stderr)
        return 1
    try:
        bundle = read_bundle(args.bundle, expected)
    except ReleaseValidationError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if approved.get("version") and bundle["manifest"].get("version") != approved["version"]:
        print("refused: bundle version disagrees with the approval record", file=sys.stderr)
        return 1

    import asyncio

    verification = asyncio.run(_run(url, bundle, args.labels))
    report = {
        "passed": not verification.problems,
        "scope": SCOPE,
        "bundle_sha256": verification.bundle_sha256,
        "version": verification.version,
        "release_id": verification.release_id,
        "database_host": url.host,
        "collections": verification.counts,
        "rows_verified": len(verification.rows),
        "players_verified": len(verification.players),
        "label_references_verified": verification.verified_label_references,
        "problems": list(verification.problems),
    }
    if not args.no_write:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if verification.problems:
        print(f"FAILED: {len(verification.problems)} problem(s)", file=sys.stderr)
        for problem in verification.problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    payload = build_mapping_payload(verification, bundle)
    text_output = json.dumps(payload, indent=2) + "\n"
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text_output, encoding="utf-8")
    counts = ", ".join(f"{name}={count}" for name, count in sorted(verification.counts.items()))
    print(
        f"verified {len(verification.rows)} rows ({counts}), "
        f"{len(verification.players)} players, "
        f"{verification.verified_label_references} label references "
        f"against release {verification.version} (id {verification.release_id})"
    )
    print(f"mapping sha256 {hashlib.sha256(text_output.encode()).hexdigest()}")
    if not args.no_write:
        print(f"wrote {args.output}")
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
