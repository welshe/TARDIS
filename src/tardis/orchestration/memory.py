"""
Shared blackboard memory for multi-agent coordination.

Agents read and write to the shared memory, enabling inter-agent
communication without direct message passing. The Orchestrator can
also use it to store global context and results.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class SharedMemory:
    """
    Thread-safe shared memory/blackboard for multi-agent coordination.

    Supports namespaced key-value storage with optional TTL, versioning
    for optimistic concurrency, and snapshot/restore for checkpointing.
    """

    def __init__(self, max_entries: int = 10000):
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.RLock()
        self._max_entries = max_entries
        self._version: int = 0

    def put(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
        namespace: str = "default",
    ) -> str:
        full_key = f"{namespace}:{key}"
        with self._lock:
            if len(self._data) >= self._max_entries and full_key not in self._data:
                self._data.popitem(last=False)
            self._version += 1
            self._data[full_key] = {
                "value": value,
                "ttl": time.time() + ttl if ttl else None,
                "version": self._version,
                "updated_at": time.time(),
                "updated_by": namespace,
            }
            self._data.move_to_end(full_key)
        return full_key

    def get(self, key: str, namespace: str = "default", default: Any = None) -> Any:
        full_key = f"{namespace}:{key}"
        with self._lock:
            entry = self._data.get(full_key)
            if entry is None:
                return default
            if entry["ttl"] and time.time() > entry["ttl"]:
                del self._data[full_key]
                return default
            return entry["value"]

    def get_meta(self, key: str, namespace: str = "default") -> dict | None:
        full_key = f"{namespace}:{key}"
        with self._lock:
            entry = self._data.get(full_key)
            if entry is None:
                return None
            if entry["ttl"] and time.time() > entry["ttl"]:
                del self._data[full_key]
                return None
            return {
                "version": entry["version"],
                "updated_at": entry["updated_at"],
                "updated_by": entry["updated_by"],
            }

    def cas(
        self,
        key: str,
        expected_version: int,
        new_value: Any,
        ttl: float | None = None,
        namespace: str = "default",
    ) -> bool:
        full_key = f"{namespace}:{key}"
        with self._lock:
            entry = self._data.get(full_key)
            current_version = entry["version"] if entry else 0
            if current_version != expected_version:
                return False
            self._data[full_key]["value"] = new_value
            self._data[full_key]["ttl"] = time.time() + ttl if ttl else None
            self._version += 1
            self._data[full_key]["version"] = self._version
            self._data[full_key]["updated_at"] = time.time()
            return True

    def delete(self, key: str, namespace: str = "default"):
        full_key = f"{namespace}:{key}"
        with self._lock:
            self._data.pop(full_key, None)

    def list_keys(self, namespace: str | None = None) -> list[str]:
        prefix = f"{namespace}:" if namespace else ""
        with self._lock:
            return [k for k in self._data if k.startswith(prefix)]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "data": {
                    k: {"value": v["value"], "version": v["version"]}
                    for k, v in self._data.items()
                },
                "version": self._version,
            }

    def restore(self, snapshot: dict):
        with self._lock:
            self._data.clear()
            for k, v in snapshot["data"].items():
                self._data[k] = {
                    "value": v["value"],
                    "ttl": None,
                    "version": v["version"],
                    "updated_at": time.time(),
                    "updated_by": "restore",
                }
            self._version = snapshot["version"]

    def clear(self, namespace: str | None = None):
        with self._lock:
            if namespace is None:
                self._data.clear()
                self._version = 0
            else:
                prefix = f"{namespace}:"
                keys = [k for k in self._data if k.startswith(prefix)]
                for k in keys:
                    del self._data[k]

    def __contains__(self, key: str) -> bool:
        ns_key = f"default:{key}"
        with self._lock:
            return ns_key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    @property
    def version(self) -> int:
        return self._version
