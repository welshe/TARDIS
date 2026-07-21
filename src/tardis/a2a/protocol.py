"""
Agent-to-Agent (A2A) communication protocol for TARDIS.

Enables structured inter-agent messaging, capability negotiation,
and shared state coordination within the multi-agent orchestration system.
"""

from __future__ import annotations

import collections
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_MAX_AGENT_ID_LEN = 128
_MAX_SUBJECT_LEN = 256
_MAX_NAMESPACE_LEN = 128
_MAX_KEY_LEN = 256
_MAX_TTL = 86400.0  # 24 hours max
_MAX_BLACKBOARD_NAMESPACES = 10_000
_MAX_SEARCH_RESULTS = 1000
_MAX_WATCHERS_PER_KEY = 100
_RATE_LIMIT_WINDOW = 60.0


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    CAPABILITY_QUERY = "capability_query"
    CAPABILITY_ADVERTISE = "capability_advertise"
    HEARTBEAT = "heartbeat"
    TASK_DELEGATE = "task_delegate"
    TASK_RESULT = "task_result"
    ERROR = "error"


class MessagePriority(int, Enum):
    LOW = 0
    NORMAL = 5
    HIGH = 10
    URGENT = 20


@dataclass
class A2AMessage:
    type: MessageType
    from_agent: str
    subject: str
    payload: dict[str, Any]
    to_agent: str | None = None
    priority: MessagePriority = MessagePriority.NORMAL
    reply_to: str | None = None
    ttl: float = 300.0
    correlation_id: str | None = None
    id: str = field(default_factory=lambda: secrets.token_hex(4))
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.ttl, (int, float)):
            self.ttl = 300.0
        if self.ttl > _MAX_TTL:
            self.ttl = float(_MAX_TTL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "subject": self.subject,
            "payload": self.payload,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "reply_to": self.reply_to,
            "ttl": self.ttl,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> A2AMessage:
        """Deserialize with validation. Raises ValueError on malformed input."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        try:
            msg_type = MessageType(data["type"])
            prio = MessagePriority(data["priority"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid message type or priority: {exc}") from exc
        required_fields = ("id", "from_agent", "subject", "payload", "timestamp")
        for field_name in required_fields:
            if field_name not in data:
                raise ValueError(f"Missing required field: {field_name}")
        return cls(
            id=str(data["id"]),
            type=msg_type,
            from_agent=str(data["from_agent"]),
            to_agent=data.get("to_agent"),
            subject=str(data["subject"]),
            payload=data["payload"] if isinstance(data["payload"], dict) else {},
            priority=prio,
            timestamp=float(data["timestamp"]),
            reply_to=data.get("reply_to"),
            ttl=float(data.get("ttl", 300.0)),
            correlation_id=data.get("correlation_id"),
        )

    @property
    def is_expired(self) -> bool:
        return time.time() > self.timestamp + self.ttl

    def validate(self) -> bool:
        return bool(self.from_agent) and bool(self.subject)


class Blackboard:
    """Thread-safe shared workspace with namespaced keys for inter-agent state."""

    def __init__(
        self,
        max_entries_per_ns: int = 1000,
        max_value_size: int = 10240,
    ):
        self._data: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._global_lock: threading.RLock = threading.RLock()
        self._max_entries_per_ns: int = max_entries_per_ns
        self._max_value_size: int = max_value_size
        self._ttl: dict[str, dict[str, float]] = {}
        self._access_order: dict[str, collections.OrderedDict] = {}
        self._watchers: dict[str, dict[str, list[Callable]]] = {}

    def _get_ns_lock(self, namespace: str) -> threading.RLock:
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("namespace must be a non-empty string")
        if len(namespace) > _MAX_NAMESPACE_LEN:
            raise ValueError(f"namespace too long ({len(namespace)} > {_MAX_NAMESPACE_LEN})")
        with self._global_lock:
            if namespace not in self._locks:
                # Prevent namespace exhaustion DoS
                if len(self._locks) >= _MAX_BLACKBOARD_NAMESPACES:
                    raise ValueError(f"Maximum number of namespaces ({_MAX_BLACKBOARD_NAMESPACES}) reached")
                self._locks[namespace] = threading.RLock()
                self._data[namespace] = {}
                self._ttl[namespace] = {}
                self._access_order[namespace] = collections.OrderedDict()
                self._watchers[namespace] = {}
            return self._locks[namespace]

    def _is_expired(self, namespace: str, key: str) -> bool:
        expiry = self._ttl.get(namespace, {}).get(key)
        if expiry is None:
            return False
        if time.time() > expiry:
            self._data[namespace].pop(key, None)
            self._ttl[namespace].pop(key, None)
            self._access_order.get(namespace, {}).pop(key, None)
            return True
        return False

    def _notify_watchers(self, namespace: str, key: str, value: Any) -> None:
        watchers = self._watchers.get(namespace, {}).get(key, [])
        for cb in watchers:
            try:
                cb(namespace, key, value)
            except Exception:
                pass

    def write(
        self,
        namespace: str,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> bool:
        if not isinstance(key, str) or not key.strip():
            return False
        if len(key) > _MAX_KEY_LEN:
            return False
        if ttl is not None and (not isinstance(ttl, (int, float)) or ttl < 0):
            return False
        value_size = len(str(value).encode("utf-8"))
        if value_size > self._max_value_size:
            return False
        lock = self._get_ns_lock(namespace)
        with lock:
            if key not in self._data[namespace] and len(self._data[namespace]) >= self._max_entries_per_ns:
                lru_key, _ = self._access_order[namespace].popitem(last=False)
                self._data[namespace].pop(lru_key, None)
                self._ttl[namespace].pop(lru_key, None)
            self._data[namespace][key] = value
            self._ttl[namespace][key] = time.time() + ttl if ttl is not None else None
            if key in self._access_order[namespace]:
                self._access_order[namespace].move_to_end(key)
            else:
                self._access_order[namespace][key] = True
            self._notify_watchers(namespace, key, value)
        return True

    def read(self, namespace: str, key: str) -> Any | None:
        if not isinstance(key, str) or not key.strip():
            return None
        lock = self._get_ns_lock(namespace)
        with lock:
            if key not in self._data.get(namespace, {}):
                return None
            if self._is_expired(namespace, key):
                return None
            if key in self._access_order.get(namespace, {}):
                self._access_order[namespace].move_to_end(key)
            return self._data[namespace][key]

    def delete(self, namespace: str, key: str) -> bool:
        if not isinstance(key, str) or not key.strip():
            return False
        lock = self._get_ns_lock(namespace)
        with lock:
            if key in self._data.get(namespace, {}):
                self._data[namespace].pop(key, None)
                self._ttl[namespace].pop(key, None)
                self._access_order.get(namespace, {}).pop(key, None)
                return True
            return False

    def list_keys(self, namespace: str) -> list[str]:
        lock = self._get_ns_lock(namespace)
        with lock:
            self._is_expired(namespace, "__scan__")  # trigger sweep
            expired = [k for k in self._data.get(namespace, {}) if self._is_expired(namespace, k)]
            for k in expired:
                self._data[namespace].pop(k, None)
                self._access_order.get(namespace, {}).pop(k, None)
            return list(self._data.get(namespace, {}).keys())

    def list_namespaces(self) -> list[str]:
        with self._global_lock:
            return list(self._data.keys())

    def clear(self, namespace: str | None = None) -> None:
        with self._global_lock:
            if namespace is None:
                self._data.clear()
                self._ttl.clear()
                self._access_order.clear()
                self._locks.clear()
                self._watchers.clear()
            else:
                if namespace in self._data:
                    self._data[namespace].clear()
                    self._ttl[namespace].clear()
                    self._access_order[namespace].clear()
                    self._watchers.pop(namespace, None)
                    self._locks.pop(namespace, None)

    def search(self, key_pattern: str, max_results: int = _MAX_SEARCH_RESULTS) -> list[tuple[str, str, Any]]:
        """Search all namespaces for keys matching pattern, with result cap."""
        max_results = min(max_results, _MAX_SEARCH_RESULTS)
        results: list[tuple[str, str, Any]] = []
        with self._global_lock:
            for namespace in list(self._data.keys()):
                if len(results) >= max_results:
                    break
                lock = self._get_ns_lock(namespace)
                with lock:
                    for key, value in list(self._data[namespace].items()):
                        if self._is_expired(namespace, key):
                            continue
                        if key_pattern in key:
                            results.append((namespace, key, value))
                            if len(results) >= max_results:
                                break
        return results

    def get_stats(self) -> dict[str, Any]:
        with self._global_lock:
            stats: dict[str, Any] = {"namespaces": {}, "total_entries": 0, "total_size_estimate": 0}
            for namespace, ns_data in self._data.items():
                count = len(ns_data)
                size = sum(len(str(v).encode("utf-8")) for v in ns_data.values())
                stats["namespaces"][namespace] = {"count": count, "size_estimate": size}
                stats["total_entries"] += count
                stats["total_size_estimate"] += size
            return stats

    def watch(self, namespace: str, key: str, callback: Callable) -> None:
        lock = self._get_ns_lock(namespace)
        with lock:
            if key not in self._watchers[namespace]:
                self._watchers[namespace][key] = []
            # Prevent unbounded watcher list growth
            if len(self._watchers[namespace][key]) >= _MAX_WATCHERS_PER_KEY:
                return
            self._watchers[namespace][key].append(callback)


class AgentProtocol(ABC):
    """Abstract base for A2A-capable agents."""

    def __init__(
        self,
        agent_id: str,
        name: str,
        capabilities: set[str] | None = None,
        supported_message_types: set[MessageType] | None = None,
    ):
        self.agent_id: str = agent_id
        self.name: str = name
        self.capabilities: set[str] = capabilities or set()
        self.supported_message_types: set[MessageType] = supported_message_types or set(MessageType)
        self._message_bus: MessageBus | None = None

    @abstractmethod
    def handle_message(self, message: A2AMessage) -> A2AMessage | None:
        ...

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        ...

    def send_message(
        self,
        bus: MessageBus,
        to_agent: str,
        subject: str,
        payload: dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
        reply_to: str | None = None,
        correlation_id: str | None = None,
        ttl: float = 300.0,
    ) -> bool:
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent=self.agent_id,
            to_agent=to_agent,
            subject=subject,
            payload=payload,
            priority=priority,
            reply_to=reply_to,
            correlation_id=correlation_id,
            ttl=ttl,
        )
        return bus.send(msg)

    def broadcast(
        self,
        bus: MessageBus,
        subject: str,
        payload: dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
        ttl: float = 300.0,
    ) -> None:
        msg = A2AMessage(
            type=MessageType.BROADCAST,
            from_agent=self.agent_id,
            subject=subject,
            payload=payload,
            priority=priority,
            ttl=ttl,
        )
        bus.broadcast(msg)

    def register_with_bus(self, bus: MessageBus) -> None:
        self._message_bus = bus
        bus.register(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "capabilities": list(self.capabilities),
            "supported_message_types": [mt.value for mt in self.supported_message_types],
        }


class MessageBus:
    """In-process message routing with rate limiting, queuing, and pub/sub."""

    def __init__(
        self,
        queue_size: int = 100,
        max_rate: int = 100,
        history_size: int = 500,
    ):
        self._agents: dict[str, AgentProtocol] = {}
        self._queues: dict[str, collections.deque[A2AMessage]] = {}
        self._queue_size: int = queue_size
        self._lock: threading.RLock = threading.RLock()
        self._history: collections.deque[A2AMessage] = collections.deque(maxlen=history_size)
        self._rate_limits: dict[str, list[float]] = {}
        self._max_rate: int = max_rate
        self._subscribers: dict[str, set[str]] = {}

    def register(self, agent: AgentProtocol) -> None:
        if not agent.agent_id:
            raise ValueError("Agent must have a non-empty agent_id")
        with self._lock:
            self._agents[agent.agent_id] = agent
            if agent.agent_id not in self._queues:
                self._queues[agent.agent_id] = collections.deque(maxlen=self._queue_size)

    def unregister(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)
            self._queues.pop(agent_id, None)
            self._rate_limits.pop(agent_id, None)
            for topic_subs in self._subscribers.values():
                topic_subs.discard(agent_id)

    def _check_rate_limit(self, agent_id: str) -> bool:
        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW
        timestamps = self._rate_limits.get(agent_id, [])
        self._rate_limits[agent_id] = [t for t in timestamps if t > window_start]
        if len(self._rate_limits[agent_id]) >= self._max_rate:
            return False
        self._rate_limits[agent_id].append(now)
        return True

    def send(self, message: A2AMessage) -> bool:
        if message.is_expired:
            return False
        if not message.validate():
            return False
        with self._lock:
            if message.from_agent not in self._agents:
                return False
            if not self._check_rate_limit(message.from_agent):
                return False
            self._history.append(message)
            if message.to_agent is None:
                return True
            if message.to_agent not in self._queues:
                return False
            self._queues[message.to_agent].append(message)
            return True

    def receive(self, agent_id: str) -> A2AMessage | None:
        with self._lock:
            queue = self._queues.get(agent_id)
            if not queue:
                return None
            while queue:
                msg = queue.popleft()
                if not msg.is_expired:
                    return msg
            return None

    def broadcast(self, message: A2AMessage) -> None:
        with self._lock:
            self._history.append(message)
            for aid, queue in self._queues.items():
                if aid != message.from_agent:
                    queue.append(message)

    def subscribe(self, agent_id: str, topic: str) -> None:
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
            self._subscribers[topic].add(agent_id)

    def publish(self, message: A2AMessage) -> int:
        delivered = 0
        with self._lock:
            self._history.append(message)
            subscribers = self._subscribers.get(message.subject, set())
            for aid in subscribers:
                if aid == message.from_agent:
                    continue
                if aid in self._queues:
                    self._queues[aid].append(message)
                    delivered += 1
            return delivered

    def get_history(self, limit: int = 50) -> list[A2AMessage]:
        with self._lock:
            history = list(self._history)
            return history[-limit:] if limit > 0 else []

    def get_queue_size(self, agent_id: str) -> int:
        with self._lock:
            queue = self._queues.get(agent_id)
            return len(queue) if queue else 0

    def flush(self) -> None:
        with self._lock:
            for queue in self._queues.values():
                queue.clear()

    def shutdown(self) -> None:
        with self._lock:
            self._agents.clear()
            self._queues.clear()
            self._rate_limits.clear()
            self._subscribers.clear()
            self._history.clear()


class A2ACoordinator:
    """High-level orchestrator for A2A messaging and coordination."""

    def __init__(
        self,
        heartbeat_interval: float = 30.0,
        queue_size: int = 100,
        max_rate: int = 100,
    ):
        self.bus: MessageBus = MessageBus(queue_size=queue_size, max_rate=max_rate)
        self.blackboard: Blackboard = Blackboard()
        self._heartbeat_interval: float = heartbeat_interval
        self._heartbeat_thread: threading.Thread | None = None
        self._running: bool = False
        self._callbacks: dict[str, Callable] = {}

    def start(self) -> None:
        self._running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="a2a-heartbeat"
        )
        self._heartbeat_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=self._heartbeat_interval + 5)
        self.bus.shutdown()

    def _heartbeat_loop(self) -> None:
        while self._running:
            time.sleep(self._heartbeat_interval)
            if not self._running:
                break
            with self.bus._lock:
                for aid, agent in list(self.bus._agents.items()):
                    hb = A2AMessage(
                        type=MessageType.HEARTBEAT,
                        from_agent=aid,
                        subject="heartbeat",
                        payload={"status": "alive"},
                        to_agent="__coordinator__",
                    )
                    self.bus._history.append(hb)

    def register_agent(self, agent: AgentProtocol) -> None:
        self.bus.register(agent)

    def discover_agents(self, capability: str, timeout: float = 10.0) -> list[str]:
        # Cap timeout to prevent extended blocking
        timeout = min(max(timeout, 0.0), 30.0)
        query = A2AMessage(
            type=MessageType.CAPABILITY_QUERY,
            from_agent="__coordinator__",
            subject="capability_query",
            payload={"capability": capability},
        )
        self.bus.broadcast(query)
        time.sleep(timeout)
        found: list[str] = []
        # Hold lock while iterating agents to avoid race with register/unregister
        with self.bus._lock:
            for aid, agent in self.bus._agents.items():
                if capability in agent.get_capabilities():
                    found.append(aid)
        return found

    def delegate_task(
        self,
        task_description: str,
        required_capability: str,
        timeout: float = 30.0,
    ) -> A2AMessage | None:
        # Cap timeout to prevent extended blocking
        timeout = min(max(timeout, 1.0), 120.0)
        candidates = self.discover_agents(required_capability, timeout=min(timeout / 2, 5.0))
        if not candidates:
            return None
        target = candidates[0]
        delegate_msg = A2AMessage(
            type=MessageType.TASK_DELEGATE,
            from_agent="__coordinator__",
            to_agent=target,
            subject="task_delegate",
            payload={"description": task_description, "capability": required_capability},
            correlation_id=secrets.token_hex(4),
        )
        self.bus.send(delegate_msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.bus._lock:
                queue = self.bus._queues.get(target)
                if queue:
                    for i, msg in enumerate(queue):
                        if msg.type == MessageType.TASK_RESULT and msg.correlation_id == delegate_msg.correlation_id:
                            queue.remove(msg)
                            return msg
            time.sleep(0.1)
        return None

    def get_agent_status(self) -> dict[str, dict[str, Any]]:
        status: dict[str, dict[str, Any]] = {}
        with self.bus._lock:
            for aid, agent in self.bus._agents.items():
                status[aid] = {
                    "name": agent.name,
                    "capabilities": list(agent.get_capabilities()),
                    "queue_size": self.bus.get_queue_size(aid),
                    "last_heartbeat": self._last_heartbeat(aid),
                }
        return status

    def _last_heartbeat(self, agent_id: str) -> float | None:
        # Caller must hold self.bus._lock
        for msg in reversed(self.bus._history):
            if msg.type == MessageType.HEARTBEAT and msg.from_agent == agent_id:
                return msg.timestamp
        return None

    def share_state(self, namespace: str, key: str, value: Any, ttl: float | None = None) -> bool:
        return self.blackboard.write(namespace, key, value, ttl=ttl)

    def get_shared_state(self, namespace: str, key: str) -> Any | None:
        return self.blackboard.read(namespace, key)
