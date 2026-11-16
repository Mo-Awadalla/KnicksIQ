from __future__ import annotations

import asyncio
import hashlib

from redis.asyncio import Redis


async def read_resp(reader: asyncio.StreamReader) -> tuple[object, bytes]:
    line = await reader.readuntil(b"\r\n")
    kind, body = line[:1], line[1:-2]
    if kind in (b"+", b"-", b":", b",", b"#", b"(", b"_"):
        return None if kind == b"_" else body, line
    if kind in (b"$", b"!", b"="):
        size = int(body)
        if size == -1:
            return None, line
        data = await reader.readexactly(size + 2)
        return data[:-2], line + data
    if kind in (b"*", b"%", b"~", b">", b"|"):
        count = int(body) * (2 if kind in (b"%", b"|") else 1)
        if count == -1:
            return None, line
        values, raw = [], bytearray(line)
        for _ in range(count):
            value, part = await read_resp(reader)
            values.append(value)
            raw.extend(part)
        if kind == b"|":
            value, part = await read_resp(reader)
            raw.extend(part)
            return value, bytes(raw)
        return values, bytes(raw)
    raise ValueError(f"Unsupported RESP type {kind!r}")


class RedisFaultProxy:
    def __init__(self, redis_port: int):
        self.redis_port = redis_port
        self.server: asyncio.Server | None = None
        self.port = 0
        self.armed = False
        self.session_keys: set[bytes] = set()
        self.block_reads = False
        self.fired = asyncio.Event()
        self.reads_held = asyncio.Event()
        self.released = asyncio.Event()
        self.released.set()
        self.connections: set[asyncio.Task] = set()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    def arm_terminal_response_loss(self, token: str) -> None:
        key = b"chat:session:" + hashlib.sha256(token.encode()).hexdigest().encode()
        self.session_keys = {key, key + b":lease"}
        self.armed = True
        self.block_reads = True
        self.fired.clear()
        self.reads_held.clear()
        self.released.clear()

    def release(self) -> None:
        self.block_reads = False
        self.released.set()

    async def expire_lease(self, token: str) -> None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        redis = Redis(host="127.0.0.1", port=self.redis_port)
        try:
            key = f"chat:session:{digest}:lease"
            if not await redis.pexpire(key, 1):
                raise RuntimeError("Expected an active owned conversation lease")
        finally:
            await redis.aclose()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self.connections.add(task)
        upstream_writer = None
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", self.redis_port
            )
            while True:
                command, raw = await read_resp(reader)
                if not isinstance(command, list) or not command:
                    raise ValueError("Expected RESP command array")
                name = command[0].upper() if isinstance(command[0], bytes) else b""
                session = any(
                    value in self.session_keys for value in command[1:] if isinstance(value, bytes)
                )
                mutation = session and name in (b"EVAL", b"EVALSHA")
                if session and self.block_reads and self.fired.is_set():
                    self.reads_held.set()
                    await self.released.wait()
                upstream_writer.write(raw)
                await upstream_writer.drain()
                _, response = await read_resp(upstream_reader)
                if mutation and self.armed and not response.startswith(b"-"):
                    self.armed = False
                    self.fired.set()
                    return
                writer.write(response)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError):
            pass
        finally:
            if upstream_writer is not None:
                upstream_writer.close()
                await upstream_writer.wait_closed()
            writer.close()
            await writer.wait_closed()
            if task is not None:
                self.connections.discard(task)

    async def stop(self) -> None:
        self.release()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self.connections):
            task.cancel()
        await asyncio.gather(*list(self.connections), return_exceptions=True)
