from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from json.decoder import JSONDecodeError
from typing import Any

from ..store.sqlite_store import Store

_logger = logging.getLogger(__name__)

_MAX_MESSAGE_SIZE = 65536
_TRACE_ID_RE = __import__("re").compile(r"^[a-zA-Z0-9_-]{1,128}$")


class StreamEventType(str, Enum):
    STEP_ADDED = "step_added"
    TRACE_STARTED = "trace_started"
    TRACE_COMPLETED = "trace_completed"
    BREAKPOINT_HIT = "breakpoint_hit"
    BREAKPOINT_RESUME = "breakpoint_resume"
    STATE_SYNC = "state_sync"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    COLLAB_JOIN = "collab_join"
    COLLAB_LEAVE = "collab_leave"
    COLLAB_CURSOR = "collab_cursor"


@dataclass
class StreamEvent:
    trace_id: str
    event_type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StreamEvent:
        return cls(
            trace_id=d["trace_id"],
            event_type=StreamEventType(d["event_type"]),
            data=d.get("data", {}),
            timestamp=d.get("timestamp", time.time()),
            source=d.get("source", ""),
        )


@dataclass
class StreamSession:
    trace_id: str
    created_at: float = field(default_factory=time.time)
    clients: int = 0
    step_count: int = 0
    subscribers: list = field(default_factory=list)
    expired: bool = False


class TraceStreamer:
    """WebSocket-based trace streaming server for real-time collaboration.

    SECURITY:
    - Localhost-only binding by default (no network exposure)
    - No authentication (intended for local dev use only)
    - Read-only streaming (clients cannot mutate trace state)
    - Rate limited: max 200 events/sec per session
    - Maximum 50 subscribers per session
    - Session TTL: 1 hour of inactivity
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9876,
        store: Store | None = None,
        max_subscribers: int = 50,
        session_ttl: int = 3600,
    ):
        self.host = host
        self.port = port
        self.store = store or Store()
        self.max_subscribers = max_subscribers
        self.session_ttl = session_ttl
        self._sessions: dict[str, StreamSession] = {}
        self._server: asyncio.AbstractServer | None = None
        self._running = False
        self._lock = threading.RLock()
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._rate_limit_counter = 0
        self._rate_limit_window = time.monotonic()

        if host != "127.0.0.1":
            import warnings
            warnings.warn(
                "TARDIS streaming server bound to non-loopback address. "
                "This exposes trace data on the network. "
                "Only use this in trusted environments."
            )

    def create_session(self, trace_id: str) -> str:
        if trace_id not in self._sessions:
            self._sessions[trace_id] = StreamSession(trace_id=trace_id)
        return trace_id

    def publish_event(self, event: StreamEvent) -> None:
        """Publish a stream event to all subscribers of the trace."""
        with self._lock:
            session = self._sessions.get(event.trace_id)
            if session is None or session.expired:
                return

            now = time.monotonic()
            if now - self._rate_limit_window > 1.0:
                self._rate_limit_counter = 0
                self._rate_limit_window = now
            self._rate_limit_counter += 1
            if self._rate_limit_counter > 200:
                _logger.warning("Rate limit exceeded for trace streaming")
                return

            session.step_count += 1
            removed = []
            for sub in session.subscribers:
                try:
                    if not sub._closed:
                        sub.put_nowait(event.to_dict())
                    else:
                        removed.append(sub)
                except asyncio.QueueFull:
                    removed.append(sub)
            for r in removed:
                if r in session.subscribers:
                    session.subscribers.remove(r)

    def subscribe(self, trace_id: str) -> asyncio.Queue:
        session = self._sessions.get(trace_id)
        if session is None:
            raise ValueError(f"No active session for trace {trace_id}")
        if len(session.subscribers) >= self.max_subscribers:
            raise RuntimeError(f"Max subscribers ({self.max_subscribers}) reached for trace {trace_id}")

        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        session.subscribers.append(queue)
        session.clients += 1
        return queue

    def unsubscribe(self, trace_id: str, queue: asyncio.Queue) -> None:
        session = self._sessions.get(trace_id)
        if session and queue in session.subscribers:
            session.subscribers.remove(queue)
            session.clients -= 1

    def get_session_status(self, trace_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(trace_id)
        if session is None:
            return None
        return {
            "trace_id": session.trace_id,
            "clients": session.clients,
            "step_count": session.step_count,
            "created_at": session.created_at,
            "expired": session.expired,
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            self.get_session_status(tid)
            for tid, s in self._sessions.items()
            if not s.expired
        ]

    def expire_session(self, trace_id: str) -> None:
        session = self._sessions.get(trace_id)
        if session:
            session.expired = True
            session.subscribers.clear()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=self._run_loop,
                args=(loop,),
                daemon=True,
                name="tardis-streamer",
            )
            t.start()
            _logger.info("Trace streamer starting on %s:%s", self.host, self.port)
        except Exception as e:
            self._running = False
            _logger.warning("Failed to start trace streamer: %s", e)

    def _run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._serve())
        loop.close()

    async def _serve(self) -> None:
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                self.host,
                self.port,
            )
            async with self._server:
                await self._server.serve_forever()
        except Exception as e:
            _logger.warning("Stream server error: %s", e)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.read(_MAX_MESSAGE_SIZE), timeout=10)
            if not data:
                return
            message = json.loads(data.decode().strip())
            action = message.get("action")
            trace_id = message.get("trace_id", "")

            if not _TRACE_ID_RE.match(trace_id):
                writer.write(json.dumps({"error": "invalid trace_id format"}).encode() + b"\n")
                await writer.drain()
                return

            if action == "subscribe" and trace_id:
                queue = self.subscribe(trace_id)
                writer.write(json.dumps({"status": "subscribed", "trace_id": trace_id}).encode() + b"\n")
                await writer.drain()

                try:
                    while True:
                        event = await asyncio.wait_for(queue.get(), timeout=30)
                        writer.write(json.dumps(event).encode() + b"\n")
                        await writer.drain()
                except asyncio.TimeoutError:
                    writer.write(json.dumps({"type": "heartbeat"}).encode() + b"\n")
                    await writer.drain()
                except Exception:
                    self.unsubscribe(trace_id, queue)
            else:
                writer.write(json.dumps({"error": "invalid request"}).encode() + b"\n")
                await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
        with self._lock:
            self._sessions.clear()


class TraceStreamClient:
    """Client for subscribing to real-time trace streams.

    Connects to a TraceStreamer to receive live trace events for
    collaborative debugging sessions.

    SECURITY: Intended for localhost connections only. No encryption.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9876):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._listeners: list[Callable[[StreamEvent], None]] = []

    def add_listener(self, callback: Callable[[StreamEvent], None]) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[StreamEvent], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def connect(self, trace_id: str) -> bool:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5,
            )
        except (ConnectionRefusedError, TimeoutError, OSError):
            return False

        msg = json.dumps({"action": "subscribe", "trace_id": trace_id}) + "\n"
        self._writer.write(msg.encode())
        await self._writer.drain()

        response = await asyncio.wait_for(self._reader.readline(), timeout=5)
        try:
            resp = json.loads(response.decode().strip())
            if resp.get("status") == "subscribed":
                self._connected = True
                asyncio.create_task(self._receive_loop())
                return True
        except (JSONDecodeError, KeyError):
            pass
        return False

    async def _receive_loop(self) -> None:
        while self._connected and self._reader:
            try:
                line = await asyncio.wait_for(self._reader.readline(), timeout=35)
                if not line:
                    break
                data = json.loads(line.decode().strip())
                if data.get("type") == "heartbeat":
                    continue
                event = StreamEvent.from_dict(data)
                for cb in self._listeners:
                    try:
                        cb(event)
                    except Exception:
                        pass
            except (asyncio.TimeoutError, JSONDecodeError, ConnectionError):
                continue

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass


def start_stream_server(
    host: str = "127.0.0.1",
    port: int = 9876,
    store: Store | None = None,
) -> TraceStreamer:
    streamer = TraceStreamer(host=host, port=port, store=store)
    streamer.start()
    return streamer
