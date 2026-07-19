import threading
import logging
from typing import Optional
from ..models import Trace, Step, StepType
from ..store.sqlite_store import Store
from ..utils.hashing import stable_hash

_logger = logging.getLogger(__name__)
_current = threading.local()

def get_current_recorder():
    return getattr(_current, "recorder", None)

class Recorder:
    def __init__(self):
        self.trace = Trace()
        self.store = Store()
        self.active = False
        self._lock = threading.Lock()
        self._batch_size = 10  # Batch trace persistence every N steps
        self._step_count = 0

    def start(self):
        self.active = True
        _current.recorder = self
        return self

    def stop(self):
        self.active = False
        try:
            self.store.save_trace(self.trace)
        except Exception as e:
            _logger.warning(f"Failed to save trace on stop: {e}")
        return self.trace

    def log(self, step_type: StepType, input: dict, output: dict, duration_ms=None, metadata=None):
        if not self.active:
            return None
        try:
            step = Step(
                trace_id=self.trace.id,
                index=len(self.trace.steps),
                type=step_type,
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
            step.success = step_type != StepType.error
            self.trace.add_step(step)
            self.store.save_step(step)
            
            # Batch trace persistence
            self._step_count += 1
            if self._step_count >= self._batch_size:
                self.store.save_trace(self.trace)
                self._step_count = 0
            
            return step
        except Exception as e:
            _logger.warning(f"Recorder.log failed silently: {e}")
            return None

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
class TardisContext:
    def __enter__(self):
        self.rec = Recorder().start()
        return self.rec
    def __exit__(self, *args):
        self.rec.stop()

# Backward compatibility alias
tardis_context = TardisContext

# alias
def init():
    from pathlib import Path
    Path(".tardis").mkdir(exist_ok=True)
    print("Initialized .tardis/")
