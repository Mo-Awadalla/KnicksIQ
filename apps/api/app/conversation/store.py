from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

from app.conversation.domain import (
    Exchange,
    MessageCommand,
    Rejected,
    RejectionCode,
    Reply,
    RetryCommand,
    Snapshot,
    command_digest,
)
from app.core.config import get_settings
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

RETENTION_SECONDS = 86_400
MAX_EXCHANGES = 40
MAX_COMMANDS = 120
MAX_FACT_STATE_BYTES = 16_384

_COMMON = f"""
local key, lease = KEYS[1], KEYS[2]
local function snapshot()
  local out = {{redis.call('HGET', key, 'revision') or '0'}}
  local count = tonumber(redis.call('HGET', key, 'count') or '0')
  for i = 1, count do out[#out + 1] = redis.call('HGET', key, 'x:' .. i) end
  return out
end
local function finish(status, reason, text)
  local pending = cjson.decode(redis.call('HGET', key, 'pending'))
  local field = 'x:' .. pending.index
  local exchange = cjson.decode(redis.call('HGET', key, field))
  local reply = {{status = status, id = pending.attempt, text = text or exchange.reply.text}}
  if reason ~= '' then reply.reason = reason end
  exchange.reply = reply
  local revision = tonumber(redis.call('HGET', key, 'revision')) + 1
  redis.call('HSET', key, field, cjson.encode(exchange), 'revision', revision)
  redis.call('HDEL', key, 'pending')
  redis.call('DEL', lease)
  redis.call('EXPIRE', key, {RETENTION_SECONDS})
end
local function reconcile()
  if redis.call('HEXISTS', key, 'pending') == 1 and redis.call('EXISTS', lease) == 0 then
    finish('interrupted', 'expired', nil)
  end
end
local function pending_attempt()
  local pending = redis.call('HGET', key, 'pending')
  if not pending then return nil end
  return cjson.decode(pending)
end
"""

BEGIN = (
    _COMMON
    + f"""
local request_id, digest, kind, expected_revision = ARGV[1], ARGV[2], ARGV[3], ARGV[4]
local message, exchange_id, owner, lease_ms = ARGV[5], ARGV[6], ARGV[7], ARGV[8]
reconcile()
local recorded = redis.call('HGET', key, 'cmd:' .. request_id)
if recorded then
  if recorded ~= digest then return {{'rejected', 'request_conflict'}} end
  local pending = pending_attempt()
  if pending and pending.attempt == request_id then return {{'rejected', 'reply_pending'}} end
  return {{'replay', snapshot()}}
end
if redis.call('HEXISTS', key, 'pending') == 1 then return {{'rejected', 'conversation_busy'}} end
local revision = tonumber(redis.call('HGET', key, 'revision') or '0')
if revision ~= tonumber(expected_revision) then
  return {{'rejected', 'revision_conflict', revision}}
end
if tonumber(redis.call('HGET', key, 'commands') or '0') >= {MAX_COMMANDS} then
  return {{'rejected', 'conversation_full'}}
end
local count = tonumber(redis.call('HGET', key, 'count') or '0')
local index, exchange
if kind == 'message' then
  if count >= {MAX_EXCHANGES} then return {{'rejected', 'conversation_full'}} end
  index = count + 1
  exchange = {{id = request_id, message = message}}
  redis.call('HSET', key, 'count', index)
else
  if count == 0 then return {{'rejected', 'not_retryable'}} end
  index = count
  exchange = cjson.decode(redis.call('HGET', key, 'x:' .. index))
  local status = exchange.reply.status
  if exchange.id ~= exchange_id or (status ~= 'stopped' and status ~= 'interrupted') then
    return {{'rejected', 'not_retryable'}}
  end
end
exchange.reply = {{status = 'writing', id = request_id, text = ''}}
revision = revision + 1
redis.call('HSET', key, 'x:' .. index, cjson.encode(exchange), 'revision', revision,
  'pending', cjson.encode({{attempt = request_id, index = index}}), 'cmd:' .. request_id, digest)
redis.call('HINCRBY', key, 'commands', 1)
redis.call('SET', lease, owner, 'PX', lease_ms)
redis.call('EXPIRE', key, {RETENTION_SECONDS})
return {{'begun', revision, redis.call('HGET', key, 'facts') or '', snapshot()}}
"""
)

CHECKPOINT = (
    _COMMON
    + f"""
local attempt, owner, base_revision, text = ARGV[1], ARGV[2], ARGV[3], ARGV[4]
if redis.call('GET', lease) ~= owner then return 0 end
local pending = pending_attempt()
if not pending or pending.attempt ~= attempt then return 0 end
if tonumber(redis.call('HGET', key, 'revision')) ~= tonumber(base_revision) then return 0 end
local field = 'x:' .. pending.index
local exchange = cjson.decode(redis.call('HGET', key, field))
exchange.reply.text = text
redis.call('HSET', key, field, cjson.encode(exchange))
redis.call('EXPIRE', key, {RETENTION_SECONDS})
return 1
"""
)

SETTLE = (
    _COMMON
    + """
local attempt, owner, base_revision = ARGV[1], ARGV[2], ARGV[3]
local status, reason, text, facts = ARGV[4], ARGV[5], ARGV[6], ARGV[7]
local pending = pending_attempt()
if not pending or pending.attempt ~= attempt then
  local count = tonumber(redis.call('HGET', key, 'count') or '0')
  if count > 0 then
    local last = cjson.decode(redis.call('HGET', key, 'x:' .. count))
    if last.reply.id == attempt and last.reply.status == status and last.reply.text == text then
      return {'settled', snapshot()}
    end
  end
  return {'fenced'}
end
if redis.call('GET', lease) ~= owner then return {'fenced'} end
if tonumber(redis.call('HGET', key, 'revision')) ~= tonumber(base_revision) then
  return {'fenced'}
end
if facts ~= '' then redis.call('HSET', key, 'facts', facts) end
finish(status, reason, text)
return {'settled', snapshot()}
"""
)

CANCEL = (
    _COMMON
    + """
local attempt, expected_revision = ARGV[1], ARGV[2]
reconcile()
local pending = pending_attempt()
if not pending or pending.attempt ~= attempt then return {'rejected', 'not_pending'} end
local revision = tonumber(redis.call('HGET', key, 'revision'))
if revision ~= tonumber(expected_revision) then
  return {'rejected', 'revision_conflict', revision}
end
finish('stopped', '', nil)
return {'stopped', snapshot()}
"""
)

READ = (
    _COMMON
    + """
reconcile()
return snapshot()
"""
)


class StoreUnavailable(Exception):
    pass


class Fenced(Exception):
    pass


@dataclass(frozen=True)
class Attempt:
    key: str
    request_id: str
    exchange_id: str
    owner: str
    revision: int
    message: str
    history: tuple[Exchange, ...]
    facts_state: dict[str, Any]


def session_key(token: str) -> str:
    return "chat:session:" + hashlib.sha256(token.encode()).hexdigest()


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


_REJECTION_CODE = TypeAdapter[RejectionCode](RejectionCode)


def _rejection_code(value: Any) -> RejectionCode:
    try:
        return _REJECTION_CODE.validate_python(_text(value))
    except ValidationError as exc:
        raise StoreUnavailable() from exc


def parse_snapshot(raw: list[Any]) -> Snapshot:
    exchanges = []
    for item in raw[1:]:
        data = json.loads(item)
        reply = data["reply"]
        exchanges.append(
            Exchange(
                id=data["id"],
                message=data["message"],
                reply=Reply(
                    status=reply["status"],
                    id=reply["id"],
                    text=reply["text"],
                    reason=reply.get("reason"),
                ),
            )
        )
    return Snapshot(revision=int(_text(raw[0])), exchanges=tuple(exchanges))


class ConversationStore:
    def __init__(self, redis: Redis):
        self.redis = redis
        self._begin = redis.register_script(BEGIN)
        self._checkpoint = redis.register_script(CHECKPOINT)
        self._settle = redis.register_script(SETTLE)
        self._cancel = redis.register_script(CANCEL)
        self._read = redis.register_script(READ)

    async def _run(self, script: Any, key: str, *args: Any) -> Any:
        try:
            return await script(keys=[key, key + ":lease"], args=list(args))
        except Exception as exc:
            raise StoreUnavailable() from exc

    async def current(self, token: str) -> Snapshot:
        return parse_snapshot(await self._run(self._read, session_key(token)))

    async def begin(
        self, token: str, command: MessageCommand | RetryCommand, lease_seconds: float
    ) -> Attempt | Snapshot:
        key = session_key(token)
        owner = secrets.token_hex(16)
        result = await self._run(
            self._begin,
            key,
            command.request_id,
            command_digest(command),
            command.kind,
            command.expected_revision,
            command.message if isinstance(command, MessageCommand) else "",
            command.exchange_id if isinstance(command, RetryCommand) else "",
            owner,
            int(lease_seconds * 1000),
        )
        status = _text(result[0])
        if status == "rejected":
            revision = int(result[2]) if len(result) > 2 else None
            raise Rejected(_rejection_code(result[1]), revision)
        if status == "replay":
            return parse_snapshot(result[1])
        snapshot = parse_snapshot(result[3])
        current = snapshot.exchanges[-1]
        facts = _text(result[2])
        return Attempt(
            key=key,
            request_id=command.request_id,
            exchange_id=current.id,
            owner=owner,
            revision=int(result[1]),
            message=current.message,
            history=snapshot.exchanges[:-1],
            facts_state=json.loads(facts) if facts else {},
        )

    async def checkpoint(self, attempt: Attempt, text: str) -> None:
        saved = await self._run(
            self._checkpoint, attempt.key, attempt.request_id, attempt.owner, attempt.revision, text
        )
        if not saved:
            raise Fenced()

    async def settle(
        self,
        attempt: Attempt,
        status: str,
        reason: str,
        text: str,
        facts_state: dict[str, Any] | None,
    ) -> Snapshot:
        facts = json.dumps(facts_state, separators=(",", ":")) if facts_state else ""
        if len(facts.encode()) > MAX_FACT_STATE_BYTES:
            facts = ""
        result = await self._run(
            self._settle,
            attempt.key,
            attempt.request_id,
            attempt.owner,
            attempt.revision,
            status,
            reason,
            text,
            facts,
        )
        if _text(result[0]) != "settled":
            raise Fenced()
        return parse_snapshot(result[1])

    async def cancel(self, token: str, request_id: str, expected_revision: int) -> Snapshot:
        result = await self._run(self._cancel, session_key(token), request_id, expected_revision)
        if _text(result[0]) == "rejected":
            revision = int(result[2]) if len(result) > 2 else None
            raise Rejected(_rejection_code(result[1]), revision)
        return parse_snapshot(result[1])


_store: ConversationStore | None = None


def conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        url = get_settings().redis_url
        if not url:
            raise StoreUnavailable()
        _store = ConversationStore(
            Redis.from_url(
                url,
                socket_connect_timeout=1.0,
                socket_timeout=5.0,
                retry=Retry(NoBackoff(), 0),
            )
        )
    return _store
