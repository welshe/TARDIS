import logging
import re
import threading

from ..models import Step, StepType, Trace
from ..store.sqlite_store import Store
from ..utils.hashing import stable_hash

_logger = logging.getLogger(__name__)
_current = threading.local()

_PII_KEYS = {
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "ssn",
    "credit_card",
    "creditcard",
    "card_number",
}
_PII_VALUE_RE = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
)


def _redact_dict(d: dict, redact_values: bool = True) -> dict:
    """Redact PII keys and values from a dict before storage."""
    if not isinstance(d, dict):
        return d
    result = {}
    for k, v in d.items():
        key_lower = str(k).lower().replace("-", "_")
        if key_lower in _PII_KEYS:
            result[k] = "***REDACTED***"
        elif isinstance(v, str) and redact_values:
            result[k] = _PII_VALUE_RE.sub("***REDACTED***", v)
        elif isinstance(v, dict):
            result[k] = _redact_dict(v, redact_values)
        else:
            result[k] = v
    return result


def get_current_recorder():
    return getattr(_current, "recorder", None)


class Recorder:
    def __init__(self, session_name: str = "", redact_pii: bool = True):
        self.trace = Trace()
        if session_name:
            self.trace.metadata["session_name"] = session_name
        self.store = Store()
        self.active = False
        self._lock = threading.RLock()
        self._batch_size = 10
        self._step_count = 0
        self._redact_pii = redact_pii

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

    def log(
        self,
        step_type: StepType,
        input: dict,
        output: dict,
        duration_ms=None,
        metadata=None,
    ):
        if not self.active:
            return None
        with self._lock:
            try:
                log_input = _redact_dict(input) if self._redact_pii else input
                log_output = _redact_dict(output) if self._redact_pii else output
                step = Step(
                    trace_id=self.trace.id,
                    index=len(self.trace.steps),
                    type=step_type,
                    input=log_input,
                    output=log_output,
                    duration_ms=duration_ms,
                    metadata=metadata or {},
                )
                step.hash = stable_hash({"in": log_input, "out": log_output})
                if metadata:
                    if "token_count" in metadata:
                        step.token_count = metadata["token_count"]
                    if "cost_usd" in metadata:
                        step.cost_usd = metadata["cost_usd"]
                    if "model" in metadata:
                        step.model_name = metadata["model"]
                step.success = step_type != StepType.error
                self.trace.add_step(step)
                self.store.save_step(step)

                self._step_count += 1
                if self._step_count >= self._batch_size:
                    self.store.save_trace(self.trace)
                    self._step_count = 0

                return step
            except Exception as e:
                _logger.warning(f"Recorder.log failed: {e}")
                return None

    def log_dom_snapshot(self, snapshot: dict, url: str | None = None):
        """Log a DOM snapshot step."""
        return self.log(
            StepType.dom_snapshot,
            input={"url": url or snapshot.get("url")},
            output=snapshot,
            metadata={
                "method": snapshot.get("method"),
                "schema": snapshot.get("schema"),
            },
        )

    def log_accessibility_snapshot(self, snapshot: dict):
        """Log an accessibility snapshot step."""
        return self.log(
            StepType.accessibility_snapshot,
            input={"desktop_name": snapshot.get("desktop_name")},
            output=snapshot,
            metadata={
                "method": snapshot.get("method"),
                "schema": snapshot.get("schema"),
            },
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
    import sys
    from pathlib import Path

    p = Path(".tardis")
    p.mkdir(exist_ok=True)
    if sys.platform != "win32":
        try:
            import os

            os.chmod(p, 0o700)
        except OSError:
            pass
    print("Initialized .tardis/")
