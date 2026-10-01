"""Durable, private cumulative verification caps, in integer nanodollars.

This supplemental journal is not monthly budget authority or a pricing verifier.
Live execution must first verify real Redis allowance and a conservative provider
bound, then keep normal application reservations enabled. No network is performed
here. Unknown spend stays reserved; any execution/accounting failure stops work.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Awaitable, Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

# Exact retained owner instruction for this verification goal. This journal
# cannot use an unrelated approval or change production monthly accounting.
SPENDING_DIRECTION_SHA256 = "23fb2fdecaabe72e38c7944b9566d1ac9358748a85f84fb5c5f4e653b28acda2"


class VerificationBudget:
    @staticmethod
    def create(path: Path, *, binding: str, shadow_selected: int) -> None:
        if not binding or type(shadow_selected) is not int or not 0 <= shadow_selected <= 120:
            raise ValueError("Missing binding or invalid fixed shadow membership")
        # Exclusive file creation: never reinitialize a previous goal attempt.
        with path.open("xb"):
            pass
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE identity (binding TEXT NOT NULL, stopped INTEGER NOT NULL);
                CREATE TABLE stages (name TEXT PRIMARY KEY, request_cap INTEGER, cost_cap INTEGER);
                CREATE TABLE calls (id INTEGER PRIMARY KEY, stage TEXT, amount INTEGER,
                                    status TEXT, error TEXT);
            """)
            db.execute("INSERT INTO identity VALUES (?, 0)", (binding,))
            db.executemany(
                "INSERT INTO stages VALUES (?, ?, ?)",
                [
                    ("smoke", 9, 100_000_000),
                    ("primary", 720, 500_000_000),
                    ("shadow", min(720, 6 * shadow_selected), 500_000_000),
                ],
            )

    def __init__(self, path: Path, *, binding: str):
        self.path = path.resolve()
        with self._connect() as db:
            identity = db.execute("SELECT binding FROM identity").fetchone()
            if identity != (binding,):
                raise ValueError("Verification preflight identity mismatch")
            if db.execute("SELECT count(*) FROM calls WHERE status = 'pending'").fetchone()[0]:
                raise ValueError("Unreconciled in-flight verification request")
            self._spending_direction(db)

    @staticmethod
    def _spending_direction(db: sqlite3.Connection) -> str | None:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='spending_direction'"
        ).fetchone()
        if not exists:
            return None
        rows = db.execute("SELECT sha256 FROM spending_direction").fetchall()
        if rows != [(SPENDING_DIRECTION_SHA256,)]:
            raise ValueError("Invalid verification spending-direction binding")
        return SPENDING_DIRECTION_SHA256

    def apply_spending_direction(self, path: Path) -> None:
        """Lift only historical testing dollar caps, without resetting history."""
        if hashlib.sha256(path.read_bytes()).hexdigest() != SPENDING_DIRECTION_SHA256:
            raise ValueError("Spending direction differs from the retained owner instruction")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT stopped FROM identity").fetchone()[0]:
                raise ValueError("Cannot change a stopped verification journal")
            if db.execute("SELECT 1 FROM calls WHERE status='pending' LIMIT 1").fetchone():
                raise ValueError("Cannot change an in-flight verification journal")
            if self._spending_direction(db) is None:
                db.execute("CREATE TABLE spending_direction (sha256 TEXT NOT NULL)")
                db.execute(
                    "INSERT INTO spending_direction VALUES (?)", (SPENDING_DIRECTION_SHA256,)
                )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, stage: str, bound_nusd: int) -> int:
        if type(bound_nusd) is not int or bound_nusd <= 0:
            raise ValueError("A positive conservative integer bound is required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT stopped FROM identity").fetchone()[0]:
                raise ValueError("Verification execution is stopped")
            cap = db.execute(
                "SELECT request_cap, cost_cap FROM stages WHERE name=?", (stage,)
            ).fetchone()
            count, cost = db.execute(
                "SELECT count(*), coalesce(sum(amount), 0) FROM calls WHERE stage=?", (stage,)
            ).fetchone()
            total = db.execute("SELECT coalesce(sum(amount), 0) FROM calls").fetchone()[0]
            enforce_dollars = self._spending_direction(db) is None
            if (
                not cap
                or count >= cap[0]
                or (enforce_dollars and cost + bound_nusd > cap[1])
                or (enforce_dollars and total + bound_nusd > 1_100_000_000)
            ):
                raise ValueError("Cumulative verification request or cost cap exceeded")
            cursor = db.execute(
                "INSERT INTO calls(stage, amount, status) VALUES (?, ?, 'pending')",
                (stage, bound_nusd),
            )
            ticket = cursor.lastrowid
            assert ticket is not None
            return ticket

    def settle(self, ticket: int, cost_nusd: int | None) -> None:
        invalid = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT amount, status FROM calls WHERE id=?", (ticket,)).fetchone()
            if not row or row[1] != "pending":
                raise ValueError("Missing or already settled request")
            valid_cost = type(cost_nusd) is int and cost_nusd >= 0
            invalid = not valid_cost or cost_nusd > row[0]
            amount = cost_nusd if valid_cost else row[0]
            db.execute(
                "UPDATE calls SET amount=?, status=?, error=? WHERE id=?",
                (
                    amount,
                    "failed" if invalid else "settled",
                    "invalid_or_overbound_cost" if invalid else None,
                    ticket,
                ),
            )
            if invalid:
                db.execute("UPDATE identity SET stopped=1")
        if invalid:
            raise ValueError("Unknown or over-bound provider cost; verification stopped")

    def fail(self, ticket: int, error: str) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE calls SET status='failed', error=? WHERE id=? AND status='pending'",
                (error, ticket),
            )
            db.execute("UPDATE identity SET stopped=1")

    async def call(
        self, stage: str, bound_nusd: int, send: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict:
        ticket = self.reserve(stage, bound_nusd)
        try:
            response = await send()
            self.settle(ticket, response.get("cost_nusd"))
            return response
        except BaseException as exc:
            # Includes cancellation after transmission; retain the full reservation.
            self.fail(ticket, type(exc).__name__)
            raise

    def request_cap(self, stage: str) -> int:
        with self._connect() as db:
            row = db.execute("SELECT request_cap FROM stages WHERE name=?", (stage,)).fetchone()
            if row is None:
                raise ValueError("Unknown verification stage")
            return row[0]

    def snapshot(self) -> dict:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, stage, amount, status, error FROM calls ORDER BY id"
            ).fetchall()
            return {
                "stopped": bool(db.execute("SELECT stopped FROM identity").fetchone()[0]),
                "spending_direction_sha256": self._spending_direction(db),
                "historical_dollar_caps_enforced": self._spending_direction(db) is None,
                "reserved_or_spent_nusd": sum(row[2] for row in rows),
                "stages": {
                    name: {
                        "requests": sum(row[1] == name for row in rows),
                        "reserved_or_spent_nusd": sum(row[2] for row in rows if row[1] == name),
                    }
                    for (name,) in db.execute("SELECT name FROM stages")
                },
                "calls": [
                    dict(zip(("id", "stage", "amount_nusd", "status", "error"), row, strict=True))
                    for row in rows
                ],
            }
