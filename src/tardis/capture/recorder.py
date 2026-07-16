import threading
from typing import Optional
from ..models import Trace, Step, StepType
from ..store.sqlite_store import Store
from ..utils.hashing import stable_hash

_current = threading.local()

def get_current_recorder():
    return getattr(_current, "recorder", None)

class Recorder:
    def __init__(self):
        self.trace = Trace()
        self.store = Store()
        self.active = False

    def start(self):
        self.active = True
        _current.recorder = self
        return self

    def stop(self):
        self.active = False
        self.store.save_trace(self.trace)
        return self.trace

    def log(self, type: StepType, input: dict, output: dict, duration_ms=None, metadata=None):
        if not self.active:
            return None
        step = Step(
            trace_id=self.trace.id,
            index=len(self.trace.steps),
            type=type,
            input=input,
            output=output,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
        step.hash = stable_hash({"in": input, "out": output})
        # Extract enhanced metadata
        if metadata:
            if 'token_count' in metadata:
                step.token_count = metadata['token_count']
            if 'cost_usd' in metadata:
                step.cost_usd = metadata['cost_usd']
            if 'model' in metadata:
                step.model_name = metadata['model']
        step.success = type != StepType.error
        self.trace.add_step(step)
        self.store.save_step(step)
        self.store.save_trace(self.trace)
        return step

    def log_dom_snapshot(self, snapshot: dict, url: Optional[str] = None):
        """Log a DOM snapshot step."""
        return self.log(
            StepType.dom_snapshot,
            input={"url": url or snapshot.get("url")},
            output=snapshot,
            metadata={"method": snapshot.get("method"), "schema": snapshot.get("schema")},
        )

    def log_accessibility_snapshot(self, snapshot: dict):
        """Log an accessibility snapshot step."""
        return self.log(
            StepType.accessibility_snapshot,
            input={"desktop_name": snapshot.get("desktop_name")},
            output=snapshot,
            metadata={"method": snapshot.get("method"), "schema": snapshot.get("schema")},
        )

def record():
    return Recorder().start()

# context manager
class tardis_context:
    def __enter__(self):
        self.rec = Recorder().start()
        return self.rec
    def __exit__(self, *args):
        self.rec.stop()

# alias
def init():
    from pathlib import Path
    Path(".tardis").mkdir(exist_ok=True)
    print("Initialized .tardis/")
