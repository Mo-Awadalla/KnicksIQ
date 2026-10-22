"""Ephemeral server authority, atomic leases, revisions and replayable commits."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from app.core.config import get_settings

TTL = 86_400
# Session authority is correctness-critical, unlike the fail-fast rate-limit and cache
# calls: a 0.2 s socket timeout turned a busy Redis into a lost commit. The commit also
# retries once, and the script is idempotent by turn digest, so a lost reply is not a
# lost answer.
SOCKET_SECONDS = 2.0
logger = logging.getLogger(__name__)


async def _session_redis():
    settings = get_settings()
    if not settings.redis_url:
        return None
    from redis.asyncio import Redis

    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=SOCKET_SECONDS,
        socket_timeout=SOCKET_SECONDS,
    )


_BEGIN = """
if redis.call('EXISTS', KEYS[1]) == 0 and ARGV[6] == '1' then
  return {'conflict', 'session_expired'}
end
local old = redis.call('HGET', KEYS[1], 'turn:' .. ARGV[1])
if old then
  local t = cjson.decode(old)
  if t.digest ~= ARGV[2] then return {'conflict', 'turn_id_reused'} end
  redis.call('EXPIRE', KEYS[1], ARGV[5])
  return {'replay', t.response}
end
local revision = tonumber(redis.call('HGET', KEYS[1], 'revision') or '0')
if revision ~= tonumber(ARGV[3]) then return {'conflict', tostring(revision)} end
if redis.call('SET', KEYS[2], ARGV[4], 'NX', 'EX', 35) == false then
  return {'conflict', 'turn_in_progress'}
end
return {'execute', redis.call('HGET', KEYS[1], 'state') or '{}'}
"""
_COMMIT = """
local old = redis.call('HGET', KEYS[1], 'turn:' .. ARGV[4])
if old then
  local t = cjson.decode(old)
  if t.digest == ARGV[7] then return 1 end
  return 0
end
local owner = redis.call('GET', KEYS[2])
if owner and owner ~= ARGV[1] then return 0 end
local revision = tonumber(redis.call('HGET', KEYS[1], 'revision') or '0')
if revision ~= tonumber(ARGV[2]) then return 0 end
redis.call('HSET', KEYS[1], 'revision', revision + 1, 'state', ARGV[3],
           'turn:' .. ARGV[4], ARGV[5])
redis.call('EXPIRE', KEYS[1], ARGV[6])
redis.call('DEL', KEYS[2])
return 1
"""
_ABORT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class SessionConflict(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class SessionUnavailable(Exception):
    pass


class SessionTurn:
    def __init__(self, token: str, turn_id: str, revision: int, digest: str):
        self.token, self.turn_id, self.revision, self.digest = token, turn_id, revision, digest
        self.owner = secrets.token_hex(24)
        self.key = f"analyst:{{{token}}}"
        self.state: dict[str, Any] = {}
        self.replay: dict[str, Any] | None = None

    @classmethod
    async def begin(
        cls, token: str | None, turn_id: str, revision: int, request: dict[str, Any]
    ) -> SessionTurn:
        supplied_token = token is not None
        # Deterministic opaque token makes first-turn transport retries replayable too.
        token = (
            token
            or hmac.new(
                get_settings().ip_hash_secret.encode(),
                ("analyst-session:" + turn_id).encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        turn = cls(token, turn_id, revision, digest)
        redis = await _session_redis()
        if redis is None:
            raise SessionUnavailable()
        try:
            status, value = await redis.eval(
                _BEGIN,
                2,
                turn.key,
                turn.key + ":lease",
                turn_id,
                digest,
                revision,
                turn.owner,
                TTL,
                1 if supplied_token else 0,
            )
            status, value = status.decode(), value.decode()
            if status == "conflict":
                raise SessionConflict(value)
            if status == "replay":
                turn.replay = json.loads(value)
            else:
                turn.state = json.loads(value)
            return turn
        except SessionConflict:
            raise
        except Exception as exc:
            raise SessionUnavailable() from exc
        finally:
            await redis.aclose()

    async def commit(self, response: dict[str, Any], state: dict[str, Any]) -> bool:
        record = json.dumps({"digest": self.digest, "response": json.dumps(response)})
        for attempt in range(2):
            redis = await _session_redis()
            if redis is None:
                return False
            try:
                return bool(
                    await redis.eval(
                        _COMMIT,
                        2,
                        self.key,
                        self.key + ":lease",
                        self.owner,
                        self.revision,
                        json.dumps(state),
                        self.turn_id,
                        record,
                        TTL,
                        self.digest,
                    )
                )
            except Exception as exc:
                # A dropped reply is not a failed commit: the script is idempotent by
                # digest, so the retry reports the stored turn instead of losing it.
                if attempt:
                    logger.warning(
                        "analyst_session_commit_failed request_id=%s error_type=%s",
                        self.turn_id,
                        type(exc).__name__,
                        extra={"request_id": self.turn_id, "error_type": type(exc).__name__},
                    )
                    return False
                await asyncio.sleep(0.05)
            finally:
                await redis.aclose()
        return False

    async def abort(self) -> None:
        redis = await _session_redis()
        if redis is None:
            return
        try:
            await redis.eval(_ABORT, 1, self.key + ":lease", self.owner)
        except Exception:
            pass
        finally:
            await redis.aclose()
