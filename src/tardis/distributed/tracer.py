from __future__ import annotations

import re
import secrets
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SpanKind(Enum):
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class StatusCode(Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


@dataclass
class SpanStatus:
    status_code: StatusCode = StatusCode.UNSET
    description: str | None = None


_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
_RESOURCE_MAX_BYTES = 1024
_MAX_ACTIVE_SPANS = 10_000
_MAX_FINISHED_SPANS = 50_000
_MAX_EXPORT_BUFFER = 10_000
_MAX_SPAN_ATTRIBUTES = 128
_MAX_EVENT_ATTRIBUTES = 32


def _valid_hex(s: str, length: int) -> bool:
    """Validate hex string against fixed-length regex to prevent ReDoS."""
    pattern = _HEX32_RE if length == 32 else _HEX16_RE
    return bool(pattern.match(s))


@dataclass(frozen=True)
class SpanContext:
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    is_valid: bool = True
    trace_flags: int = 0

    @classmethod
    def create(cls, parent_span_id: str | None = None) -> SpanContext:
        trace_id = secrets.token_hex(16)
        span_id = secrets.token_hex(8)
        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            is_valid=True,
        )


class Span:
    def __init__(
        self,
        name: str,
        context: SpanContext,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
        resource: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.context = context
        self.kind = kind
        self.start_time: float = time.time()
        self.end_time: float | None = None
        self.status: SpanStatus = SpanStatus()
        self.attributes: dict[str, Any] = {k: v for k, v in (attributes or {}).items() if k is not None}
        self.events: list[dict] = []
        self.links: list[SpanContext] = []
        self.resource: dict[str, Any] = _sanitize_resource(resource or {})
        self._recording = True

    @property
    def is_recording(self) -> bool:
        return self._recording

    def set_attribute(self, key: str, value: Any) -> None:
        if self._recording and key is not None:
            # Prevent unbounded attribute growth from untrusted inputs
            if len(self.attributes) >= _MAX_SPAN_ATTRIBUTES and key not in self.attributes:
                return
            self.attributes[key] = value

    def set_status(self, code: StatusCode, description: str | None = None) -> None:
        if self._recording:
            self.status = SpanStatus(status_code=code, description=description)

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        if self._recording:
            # Prevent unbounded event list growth
            if len(self.events) >= _MAX_EVENT_ATTRIBUTES:
                return
            self.events.append({
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            })

    def end(self) -> None:
        if self._recording:
            self.end_time = time.time()
            self._recording = False

    def get_duration_ms(self) -> float | None:
        if self.end_time is not None:
            return (self.end_time - self.start_time) * 1000
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_span_id": self.context.parent_span_id,
            "kind": self.kind.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": {
                "status_code": self.status.status_code.value,
                "description": self.status.description,
            },
            "attributes": self.attributes,
            "events": self.events,
            "links": [
                {"trace_id": link.trace_id, "span_id": link.span_id}
                for link in self.links
            ],
            "resource": self.resource,
            "duration_ms": self.get_duration_ms(),
        }

    def __enter__(self) -> Span:
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        if exc_type is not None:
            # Sanitize exception message to avoid leaking sensitive data (credentials, paths, tokens)
            exc_msg = str(exc_val)[:512] if exc_val is not None else ""
            self.set_status(StatusCode.ERROR, exc_msg or exc_type.__name__)
            self.add_event("exception", {
                "exception.type": exc_type.__name__,
                "exception.message": exc_msg,
            })
        self.end()


class Tracer:
    def __init__(
        self,
        name: str = "tardis",
        resource: dict[str, Any] | None = None,
        exporter: SpanExporter | None = None,
    ) -> None:
        self.name = name
        self.resource: dict[str, Any] = _sanitize_resource(resource or {})
        self._exporter: SpanExporter | None = exporter
        self._active_spans: dict[str, Span] = {}
        self._finished_spans: list[Span] = []
        self._lock = threading.RLock()

    def start_span(
        self,
        name: str,
        parent: SpanContext | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        parent_id = parent.span_id if parent else None
        ctx = SpanContext.create(parent_span_id=parent_id)
        span = Span(
            name=name,
            context=ctx,
            kind=kind,
            attributes=attributes,
            resource=self.resource,
        )
        with self._lock:
            # Evict oldest active span if at capacity to prevent memory exhaustion
            if len(self._active_spans) >= _MAX_ACTIVE_SPANS:
                oldest_id = next(iter(self._active_spans))
                evicted = self._active_spans.pop(oldest_id)
                self._finished_spans.append(evicted)
                if len(self._finished_spans) > _MAX_FINISHED_SPANS:
                    self._finished_spans.pop(0)
            self._active_spans[ctx.span_id] = span
        return span

    def start_as_current_span(
        self,
        name: str,
        parent: SpanContext | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ) -> _SpanToken:
        span = self.start_span(name, parent=parent, kind=kind, attributes=attributes)
        return _SpanToken(tracer=self, span=span)

    def on_span_end(self, span: Span) -> None:
        with self._lock:
            self._active_spans.pop(span.context.span_id, None)
            self._finished_spans.append(span)
            # Evict oldest finished spans to prevent unbounded memory growth
            while len(self._finished_spans) > _MAX_FINISHED_SPANS:
                self._finished_spans.pop(0)
        if self._exporter is not None:
            try:
                self._exporter.export([span])
            except Exception:
                pass

    def get_finished_spans(self) -> list[Span]:
        with self._lock:
            return list(self._finished_spans)

    def get_trace(self, trace_id: str) -> list[Span]:
        with self._lock:
            return [s for s in self._finished_spans if s.context.trace_id == trace_id]

    def clear(self) -> None:
        with self._lock:
            self._finished_spans.clear()
            self._active_spans.clear()


class _SpanToken:
    def __init__(self, tracer: Tracer, span: Span) -> None:
        self._tracer = tracer
        self.span = span

    def __enter__(self) -> Span:
        return self.span

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        self.span.__exit__(exc_type, exc_val, exc_tb)
        self._tracer.on_span_end(self.span)


class TextMapPropagator:
    _HEADER = "traceparent"

    def inject(self, context: SpanContext, carrier: dict[str, str]) -> None:
        flags = format(context.trace_flags, "02x")
        carrier[self._HEADER] = f"00-{context.trace_id}-{context.span_id}-{flags}"

    def extract(self, carrier: dict[str, str]) -> SpanContext:
        raw = carrier.get(self._HEADER, "")
        parts = raw.split("-")
        if len(parts) != 4 or parts[0] != "00":
            return SpanContext(trace_id="", span_id="", is_valid=False)
        _, trace_id, span_id, flags = parts
        if not (_valid_hex(trace_id, 32) and _valid_hex(span_id, 16)):
            return SpanContext(trace_id="", span_id="", is_valid=False)
        try:
            trace_flags = int(flags, 16)
        except ValueError:
            return SpanContext(trace_id="", span_id="", is_valid=False)
        return SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            is_valid=True,
            trace_flags=trace_flags,
        )


class SpanExporter(ABC):
    @abstractmethod
    def export(self, spans: list[Span]) -> None: ...

    @abstractmethod
    def shutdown(self) -> None: ...


class TardisSpanExporter(SpanExporter):
    def __init__(self, store: Any = None) -> None:
        from ..store.sqlite_store import Store
        self._store = store or Store()
        self._buffer: list[Span] = []
        self._lock = threading.RLock()

    def export(self, spans: list[Span]) -> None:
        from ..models import Trace

        with self._lock:
            self._buffer.extend(spans)
            # Cap buffer size to prevent memory exhaustion under backpressure
            if len(self._buffer) > _MAX_EXPORT_BUFFER:
                self._buffer = self._buffer[-_MAX_EXPORT_BUFFER:]

        traces: dict[str, list[Span]] = {}
        with self._lock:
            for span in self._buffer:
                traces.setdefault(span.context.trace_id, []).append(span)
            self._buffer.clear()

        for trace_id, trace_spans in traces.items():
            trace = Trace(id=trace_id)
            for span in trace_spans:
                step = self._span_to_step(span)
                trace.add_step(step)
            try:
                self._store.save_trace(trace)
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._lock:
            if self._buffer:
                remaining = list(self._buffer)
                self._buffer.clear()
            else:
                remaining = []
        if remaining:
            self.export(remaining)

    @staticmethod
    def _span_to_step(span: Span) -> Any:
        from ..models import Step, StepType

        kind_map = {
            SpanKind.INTERNAL: StepType.orchestration_event,
            SpanKind.SERVER: StepType.orchestration_event,
            SpanKind.CLIENT: StepType.tool_call,
            SpanKind.PRODUCER: StepType.orchestration_event,
            SpanKind.CONSUMER: StepType.tool_result,
        }
        step_type = kind_map.get(span.kind, StepType.orchestration_event)
        if span.status.status_code == StatusCode.ERROR:
            step_type = StepType.error

        attrs = dict(span.attributes)
        step_input = attrs.pop("input", {}) if isinstance(attrs.get("input"), dict) else {}
        step_output = attrs.pop("output", {}) if isinstance(attrs.get("output"), dict) else {}

        success = span.status.status_code != StatusCode.ERROR
        duration_ms = span.get_duration_ms()

        return Step(
            trace_id=span.context.trace_id,
            index=0,
            type=step_type,
            timestamp=span.start_time,
            parent_id=span.context.parent_span_id,
            duration_ms=int(duration_ms) if duration_ms is not None else None,
            input=step_input,
            output=step_output,
            metadata=attrs,
            success=success,
        )


_global_tracer: Tracer | None = None
_global_lock = threading.Lock()


def get_global_tracer(name: str = "tardis") -> Tracer:
    global _global_tracer
    if _global_tracer is None:
        with _global_lock:
            if _global_tracer is None:
                _global_tracer = Tracer(name=name)
    return _global_tracer


def set_global_tracer(tracer: Tracer) -> None:
    global _global_tracer
    with _global_lock:
        _global_tracer = tracer


def _sanitize_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """Sanitize resource dict to limit total size and filter invalid keys."""
    result: dict[str, Any] = {}
    total = 0
    for k, v in resource.items():
        # Only allow string keys to prevent type confusion
        if k is None or not isinstance(k, str):
            continue
        serialized = len(k) + len(str(v))
        if total + serialized > _RESOURCE_MAX_BYTES:
            break
        result[k] = v
        total += serialized
    return result
