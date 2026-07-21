"""
Deterministic Time-Travel Replay Engine

Using eBPF/ETW tracing to record exact system states during interactions,
allowing developers to replay and debug specific issues deterministically.
Solves the major reproducibility problem in LLM development.
"""

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..os_integration.kernel_tracer import KernelEvent, KernelTracer

_HAS_PSUTIL = False
try:
    import psutil  # noqa: F401

    _HAS_PSUTIL = True
except ImportError:
    pass

_SENSITIVE_ENV_KEYS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "HUGGINGFACE_TOKEN",
    "HF_TOKEN",
    "REPLICATE_API_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "SECRET_KEY",
    "JWT_SECRET",
    "MAIL_PASSWORD",
    "SMTP_PASSWORD",
    "ENCRYPTION_KEY",
    "PRIVATE_KEY",
    "SIGNING_KEY",
    "OAUTH_CLIENT_SECRET",
}


def _redact_env_vars(env_dict: dict[str, str]) -> dict[str, str]:
    """Redact sensitive environment variables before storage."""
    redacted = {}
    for k, v in env_dict.items():
        k_upper = k.upper().replace("-", "_")
        if k_upper in _SENSITIVE_ENV_KEYS or any(
            s in k_upper for s in ("SECRET", "TOKEN", "PASSWORD", "KEY", "CREDENTIAL")
        ):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


@dataclass
class SystemState:
    """Snapshot of system state at a point in time."""

    timestamp: float
    step_id: str
    trace_id: str

    # Process state
    pid: int
    thread_id: int | None = None

    # Memory state (hashed for efficiency)
    memory_hash: str = ""
    heap_snapshot: bytes | None = None

    # Register state (for low-level debugging)
    registers: dict[str, Any] | None = None

    # File descriptors and handles
    open_files: list[str] = field(default_factory=list)
    network_connections: list[dict[str, Any]] = field(default_factory=list)

    # Environment
    env_vars: dict[str, str] = field(default_factory=dict)
    cwd: str = ""

    # LLM-specific state
    context_tokens: int = 0
    model_state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "step_id": self.step_id,
            "trace_id": self.trace_id,
            "pid": self.pid,
            "thread_id": self.thread_id,
            "memory_hash": self.memory_hash,
            "open_files": self.open_files,
            "network_connections": self.network_connections,
            "cwd": self.cwd,
            "env_vars": self.env_vars,
            "context_tokens": self.context_tokens,
        }


@dataclass
class ReplayEvent:
    """Recorded event for deterministic replay."""

    event_type: str
    timestamp: float
    step_id: str
    data: dict[str, Any]
    system_state: SystemState | None = None
    checksum: str | None = None

    def __post_init__(self):
        if not self.checksum:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute checksum for integrity verification."""
        content = (
            f"{self.event_type}{self.timestamp}{json.dumps(self.data, sort_keys=True)}"
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class TimeTravelTracer:
    """
    High-level tracer that wraps KernelTracer with system state capture
    for time-travel replay.
    """

    def __init__(self, backend: str = "auto", storage_dir: str = ".tardis/replay"):
        self._kernel_tracer = KernelTracer(backend=backend)
        self.events: list[ReplayEvent] = []
        self.running = False
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._trace_id = f"trace_{os.getpid()}"

    def start(self) -> "TimeTravelTracer":
        self.running = True
        self.events = []
        self._kernel_tracer.start(callback=self._on_kernel_event)
        return self

    def _on_kernel_event(self, kernel_event: KernelEvent) -> None:
        """Convert kernel events to replay events with system state."""
        state = self._capture_system_state(f"evt_{len(self.events)}")
        replay_event = ReplayEvent(
            event_type=kernel_event.event_type,
            timestamp=kernel_event.timestamp,
            step_id=f"step_{len(self.events)}",
            data=kernel_event.to_dict(),
            system_state=state,
        )
        self.events.append(replay_event)

    def _capture_system_state(self, step_id: str) -> SystemState:
        """Capture current system state cross-platform using psutil.

        The memory hash is a deterministic content hash of the process's
        runtime state (RSS, open file count, cwd) so that diff_states can
        meaningfully compare two snapshots rather than producing a fresh,
        always-different value on every capture.
        """
        pid = os.getpid()
        open_files = []
        rss = 0

        try:
            if _HAS_PSUTIL:
                import psutil

                proc = psutil.Process(pid)
                rss = proc.memory_info().rss
                for f in proc.open_files():
                    open_files.append(f.path)
        except Exception:
            # Cross-platform fallback: no /proc dependency
            try:
                open_files = [f for f in os.listdir(".") if os.path.isfile(f)][:20]
            except Exception:
                pass

        hasher = hashlib.md5()
        hasher.update(str(rss).encode())
        hasher.update(str(len(open_files)).encode())
        hasher.update(os.getcwd().encode())
        memory_hash = hasher.hexdigest()[:16]

        return SystemState(
            timestamp=time.time(),
            step_id=step_id,
            trace_id=self._trace_id,
            pid=pid,
            thread_id=threading.get_ident(),
            memory_hash=memory_hash,
            open_files=open_files,
            cwd=os.getcwd(),
            env_vars=_redact_env_vars(dict(os.environ)),
        )

    def stop(self) -> list[ReplayEvent]:
        self.running = False
        self._kernel_tracer.stop()
        return self.events

    def record_event(self, event_type: str, data: dict[str, Any], step_id: str) -> None:
        """Record an event manually."""
        if not self.running:
            return
        state = self._capture_system_state(step_id)
        event = ReplayEvent(
            event_type=event_type,
            timestamp=time.time(),
            step_id=step_id,
            data=data,
            system_state=state,
        )
        self.events.append(event)

    def save_trace(self, trace_id: str) -> Path:
        """Save trace to disk."""
        trace_file = self.storage_dir / f"{trace_id}.jsonl"

        with open(trace_file, "w") as f:
            for event in self.events:
                event_dict = {
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "step_id": event.step_id,
                    "data": event.data,
                    "checksum": event.checksum,
                }
                if event.system_state:
                    event_dict["system_state"] = event.system_state.to_dict()

                f.write(json.dumps(event_dict) + "\n")

        return trace_file

    def verify_integrity(self, trace_id: str) -> tuple[bool, list[str]]:
        """Verify trace integrity using checksums."""
        trace_file = self.storage_dir / f"{trace_id}.jsonl"

        if not trace_file.exists():
            return False, ["Trace file not found"]

        errors = []
        with open(trace_file) as f:
            for line_num, line in enumerate(f, 1):
                event_data = json.loads(line)

                # Recompute checksum
                content = f"{event_data['event_type']}{event_data['timestamp']}{json.dumps(event_data['data'], sort_keys=True)}"
                expected_checksum = hashlib.sha256(content.encode()).hexdigest()[:16]

                if event_data.get("checksum") != expected_checksum:
                    errors.append(f"Line {line_num}: Checksum mismatch")

        return len(errors) == 0, errors


class TimeTravelReplay:
    """
    Deterministic replay engine with time-travel debugging capabilities.
    """

    def __init__(self, storage_dir: str = ".tardis/replay"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.loaded_events: list[ReplayEvent] = []
        self.current_position = 0
        self.breakpoints: list[int] = []
        self.state_history: list[dict[str, Any]] = []

    def load_trace(self, trace_id: str) -> bool:
        """Load a trace from disk."""
        trace_file = self.storage_dir / f"{trace_id}.jsonl"

        if not trace_file.exists():
            return False

        self.loaded_events = []
        with open(trace_file) as f:
            for line in f:
                event_data = json.loads(line)

                system_state = None
                if event_data.get("system_state"):
                    state_data = event_data["system_state"]
                    system_state = SystemState(
                        timestamp=state_data["timestamp"],
                        step_id=state_data["step_id"],
                        trace_id=state_data["trace_id"],
                        pid=state_data["pid"],
                        thread_id=state_data.get("thread_id"),
                        memory_hash=state_data["memory_hash"],
                        open_files=state_data.get("open_files", []),
                        cwd=state_data.get("cwd", ""),
                    )

                event = ReplayEvent(
                    event_type=event_data["event_type"],
                    timestamp=event_data["timestamp"],
                    step_id=event_data["step_id"],
                    data=event_data["data"],
                    system_state=system_state,
                    checksum=event_data.get("checksum"),
                )

                self.loaded_events.append(event)

        self.current_position = 0
        self.state_history = []
        return True

    def rewind_to(self, step_index: int) -> bool:
        """Rewind replay to a specific step index."""
        if step_index < 0 or step_index >= len(self.loaded_events):
            return False

        self.current_position = step_index
        # Reset state history so it stays consistent with the new position.
        # State history only records positions reached via step_forward.
        self.state_history = []
        return True

    def step_forward(self) -> ReplayEvent | None:
        """Execute next event in replay."""
        if self.current_position >= len(self.loaded_events):
            return None

        event = self.loaded_events[self.current_position]
        self.current_position += 1

        # Record state for time-travel
        self.state_history.append(
            {
                "position": self.current_position,
                "event_type": event.event_type,
                "timestamp": event.timestamp,
            }
        )

        return event

    def step_backward(self) -> ReplayEvent | None:
        """Step backward in replay."""
        if self.current_position <= 0:
            return None

        self.current_position -= 1
        # Pop only if history is present; guards against desync if rewind_to
        # cleared it or stepping never advanced.
        if self.state_history:
            self.state_history.pop()

        return self.loaded_events[self.current_position]

    def add_breakpoint(self, step_index: int) -> None:
        """Add a breakpoint at a specific step."""
        if step_index not in self.breakpoints:
            self.breakpoints.append(step_index)
            self.breakpoints.sort()

    def run_to_breakpoint(self) -> tuple[int, ReplayEvent] | None:
        """Run forward until hitting a breakpoint.

        Returns the (position, event) at the breakpoint and advances the
        current position past it, so a subsequent call continues forward
        instead of returning the same breakpoint forever.
        """
        while self.current_position < len(self.loaded_events):
            if self.current_position in self.breakpoints:
                pos = self.current_position
                event = self.loaded_events[pos]
                self.current_position = pos + 1
                self.state_history.append(
                    {
                        "position": self.current_position,
                        "event_type": event.event_type,
                        "timestamp": event.timestamp,
                    }
                )
                return pos, event

            self.step_forward()

        return None

    def get_current_state(self) -> dict[str, Any] | None:
        """Get current replay state."""
        if not self.loaded_events or self.current_position >= len(self.loaded_events):
            return None

        event = self.loaded_events[self.current_position]
        return {
            "position": self.current_position,
            "total_events": len(self.loaded_events),
            "current_event_type": event.event_type,
            "current_timestamp": event.timestamp,
            "has_system_state": event.system_state is not None,
            "breakpoints": self.breakpoints,
        }

    def diff_states(self, index1: int, index2: int) -> dict[str, Any]:
        """Compare system states between two positions."""
        if not self.loaded_events:
            return {"error": "No trace loaded"}
        if index1 < 0 or index2 < 0:
            return {"error": "Negative indices are not valid positions"}
        if index1 >= len(self.loaded_events) or index2 >= len(self.loaded_events):
            return {"error": "Index out of range"}

        state1 = self.loaded_events[index1].system_state
        state2 = self.loaded_events[index2].system_state

        if not state1 or not state2:
            return {"error": "System states not available"}

        differences = {}

        if state1.memory_hash != state2.memory_hash:
            differences["memory_changed"] = True

        if state1.cwd != state2.cwd:
            differences["cwd_changed"] = {
                "from": state1.cwd,
                "to": state2.cwd,
            }

        files_added = set(state2.open_files) - set(state1.open_files)
        files_removed = set(state1.open_files) - set(state2.open_files)

        if files_added or files_removed:
            differences["file_changes"] = {
                "added": list(files_added),
                "removed": list(files_removed),
            }

        return {
            "index1": index1,
            "index2": index2,
            "differences": differences,
            "identical": len(differences) == 0,
        }

    def export_replay_script(self, output_path: str) -> None:
        """Export replay as executable script."""
        script_lines = [
            "#!/usr/bin/env python3",
            "# Auto-generated TARDIS replay script",
            f"# Generated: {datetime.now().isoformat()}",
            "",
            "import tardis",
            "",
            "def replay_trace():",
            "    rec = tardis.Recorder().start()",
            "",
        ]

        for i, event in enumerate(self.loaded_events):
            script_lines.append(f"    # Step {i}: {event.event_type}")
            script_lines.append(f"    # Data: {json.dumps(event.data)[:100]}...")
            script_lines.append("")

        script_lines.extend(
            [
                "    trace = rec.stop()",
                "    return trace",
                "",
                "if __name__ == '__main__':",
                "    replay_trace()",
            ]
        )

        with open(output_path, "w") as f:
            f.write("\n".join(script_lines))


# Convenience functions
def enable_time_travel_tracing(backend: str = "auto") -> TimeTravelTracer:
    """Enable kernel-level time-travel tracing."""
    return TimeTravelTracer(backend=backend).start()


def create_replay_engine(trace_id: str | None = None) -> "TimeTravelReplay":
    """Create a replay engine, optionally loading an existing trace."""
    engine = TimeTravelReplay()
    if trace_id:
        engine.load_trace(trace_id)
    return engine
