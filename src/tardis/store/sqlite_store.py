import json
import pathlib
import sqlite3
import threading

from ..config import load
from ..models import Step, Trace


class Store:
    def __init__(self):
        cfg = load()
        db_path = pathlib.Path(cfg.db_path).resolve()
        allowed_root = pathlib.Path.cwd().resolve()
        # Use is_relative_to for cross-platform path traversal prevention.
        # Falls back to string prefix check for Python < 3.9 compatibility.
        try:
            db_path.relative_to(allowed_root)
        except ValueError:
            raise ValueError(
                f"Database path {db_path} is outside working directory {allowed_root}. "
                "Path traversal blocked for security."
            )
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, data TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS steps (id TEXT PRIMARY KEY, trace_id TEXT, idx INTEGER, data TEXT)"
        )
        self.conn.commit()
        # Serialize all access to the shared connection. SQLite connections are
        # not safe for concurrent use from multiple threads even with
        # check_same_thread=False, and multiple Recorder/Store instances may
        # write to the same DB from different threads (screen buffer, hooks,
        # main thread).
        self._lock = threading.RLock()

    def save_trace(self, trace: Trace):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO traces VALUES (?, ?)",
                (trace.id, trace.model_dump_json()),
            )
            for s in trace.steps:
                self.conn.execute(
                    "INSERT OR REPLACE INTO steps VALUES (?, ?, ?, ?)",
                    (s.id, s.trace_id, s.index, s.model_dump_json()),
                )
            self.conn.commit()

    def save_step(self, step: Step):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO steps VALUES (?, ?, ?, ?)",
                (step.id, step.trace_id, step.index, step.model_dump_json()),
            )
            self.conn.commit()

    def list_traces(self):
        with self._lock:
            cur = self.conn.execute(
                "SELECT data FROM traces ORDER BY rowid DESC LIMIT 50"
            )
            return [json.loads(r[0]) for r in cur.fetchall()]

    def get_trace(self, trace_id: str) -> Trace | None:
        with self._lock:
            cur = self.conn.execute("SELECT data FROM traces WHERE id=?", (trace_id,))
            row = cur.fetchone()
            if not row:
                # try prefix match
                cur = self.conn.execute(
                    "SELECT data FROM traces WHERE id LIKE ?", (f"{trace_id}%",)
                )
                row = cur.fetchone()
                if not row:
                    return None
            data = json.loads(row[0])
            # load steps
            cur = self.conn.execute(
                "SELECT data FROM steps WHERE trace_id=? ORDER BY idx", (data["id"],)
            )
            steps = [Step.model_validate(json.loads(r[0])) for r in cur.fetchall()]
        trace = Trace.model_validate(data)
        trace.steps = steps
        return trace
