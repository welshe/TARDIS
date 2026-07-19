import sqlite3, pathlib, json, os
from ..models import Trace, Step
from ..config import load

class Store:
    def __init__(self):
        cfg = load()
        self.db_path = pathlib.Path(cfg.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, data TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS steps (id TEXT PRIMARY KEY, trace_id TEXT, idx INTEGER, data TEXT)")
        self.conn.commit()

    def save_trace(self, trace: Trace):
        self.conn.execute("INSERT OR REPLACE INTO traces VALUES (?, ?)", (trace.id, trace.model_dump_json()))
        for s in trace.steps:
            self.conn.execute("INSERT OR REPLACE INTO steps VALUES (?, ?, ?, ?)", (s.id, s.trace_id, s.index, s.model_dump_json()))
        self.conn.commit()

    def save_step(self, step: Step):
        self.conn.execute("INSERT OR REPLACE INTO steps VALUES (?, ?, ?, ?)", (step.id, step.trace_id, step.index, step.model_dump_json()))
        self.conn.commit()

    def list_traces(self):
        cur = self.conn.execute("SELECT data FROM traces ORDER BY rowid DESC LIMIT 50")
        return [json.loads(r[0]) for r in cur.fetchall()]

    def get_trace(self, trace_id: str) -> Trace | None:
        cur = self.conn.execute("SELECT data FROM traces WHERE id=?", (trace_id,))
        row = cur.fetchone()
        if not row:
            # try prefix match
            cur = self.conn.execute("SELECT data FROM traces WHERE id LIKE ?", (f"{trace_id}%",))
            row = cur.fetchone()
            if not row:
                return None
        data = json.loads(row[0])
        # load steps
        cur = self.conn.execute("SELECT data FROM steps WHERE trace_id=? ORDER BY idx", (data["id"],))
        steps = [Step.model_validate(json.loads(r[0])) for r in cur.fetchall()]
        trace = Trace.model_validate(data)
        trace.steps = steps
        return trace
