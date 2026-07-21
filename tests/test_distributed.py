"""Tests for the distributed tracing module."""

import threading
from unittest.mock import MagicMock

from tardis.distributed.tracer import (
    Span,
    SpanContext,
    SpanKind,
    StatusCode,
    TardisSpanExporter,
    TextMapPropagator,
    Tracer,
    _sanitize_resource,
    _valid_hex,
    get_global_tracer,
    set_global_tracer,
)


class TestSpanContext:
    def test_create_generates_valid_ids(self):
        ctx = SpanContext.create()
        assert ctx.is_valid is True
        assert len(ctx.trace_id) == 32
        assert len(ctx.span_id) == 16

    def test_create_with_parent(self):
        ctx = SpanContext.create(parent_span_id="a" * 16)
        assert ctx.parent_span_id == "a" * 16

    def test_create_without_parent(self):
        ctx = SpanContext.create()
        assert ctx.parent_span_id is None

    def test_frozen_dataclass(self):
        ctx = SpanContext.create()
        try:
            ctx.trace_id = "bad"
            assert False, "Should be frozen"
        except Exception:
            pass

    def test_manual_construction(self):
        ctx = SpanContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="c" * 16,
            is_valid=True,
            trace_flags=1,
        )
        assert ctx.trace_id == "a" * 32
        assert ctx.trace_flags == 1


class TestSpan:
    def test_lifecycle(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        assert span.is_recording is True
        assert span.end_time is None
        assert span.get_duration_ms() is None
        span.end()
        assert span.is_recording is False
        assert span.end_time is not None
        assert span.get_duration_ms() >= 0

    def test_set_attribute(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        span.set_attribute("key", "val")
        assert span.attributes["key"] == "val"

    def test_set_attribute_none_key_ignored(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        span.set_attribute(None, "val")
        assert None not in span.attributes

    def test_add_event(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        span.add_event("click", {"x": 1})
        assert len(span.events) == 1
        assert span.events[0]["name"] == "click"
        assert span.events[0]["attributes"]["x"] == 1

    def test_set_status(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        span.set_status(StatusCode.ERROR, "boom")
        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description == "boom"

    def test_no_op_after_end(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        span.end()
        span.set_attribute("x", 1)
        span.add_event("e")
        span.set_status(StatusCode.OK)
        assert span.attributes == {}
        assert span.events == []

    def test_context_manager_no_exception(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        with span as s:
            s.set_attribute("inside", True)
        assert span.is_recording is False
        assert span.attributes["inside"] is True
        assert span.status.status_code == StatusCode.UNSET

    def test_context_manager_with_exception(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        try:
            with span:
                raise ValueError("test err")
        except ValueError:
            pass
        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description == "test err"
        assert any(e["name"] == "exception" for e in span.events)
        assert span.is_recording is False

    def test_to_dict_serialization(self):
        ctx = SpanContext.create(parent_span_id="a" * 16)
        span = Span("my_op", ctx, kind=SpanKind.CLIENT, attributes={"a": 1})
        span.add_event("evt")
        span.end()
        d = span.to_dict()
        assert d["name"] == "my_op"
        assert d["trace_id"] == ctx.trace_id
        assert d["span_id"] == ctx.span_id
        assert d["parent_span_id"] == "a" * 16
        assert d["kind"] == "client"
        assert d["attributes"] == {"a": 1}
        assert d["status"]["status_code"] == "UNSET"
        assert d["duration_ms"] >= 0
        assert len(d["events"]) == 1

    def test_resource_sanitized_on_init(self):
        ctx = SpanContext.create()
        span = Span("op", ctx, resource={None: "bad", "good": "val"})
        assert None not in span.resource
        assert span.resource["good"] == "val"

    def test_default_kind_is_internal(self):
        ctx = SpanContext.create()
        span = Span("op", ctx)
        assert span.kind == SpanKind.INTERNAL


class TestTracer:
    def test_start_span(self):
        tracer = Tracer("test")
        span = tracer.start_span("op1")
        assert span.name == "op1"
        assert span.context.is_valid is True
        assert span.context.span_id in tracer._active_spans

    def test_start_span_with_parent(self):
        tracer = Tracer("test")
        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent=parent.context)
        assert child.context.parent_span_id == parent.context.span_id

    def test_start_as_current_span_context_manager(self):
        tracer = Tracer("test")
        with tracer.start_as_current_span("op") as span:
            assert span.name == "op"
            assert span.is_recording is True
        assert span.is_recording is False
        assert len(tracer.get_finished_spans()) == 1

    def test_finished_spans_tracked_via_context_manager(self):
        tracer = Tracer("test")
        with tracer.start_as_current_span("a"):
            pass
        with tracer.start_as_current_span("b"):
            pass
        assert len(tracer.get_finished_spans()) == 2

    def test_finished_spans_tracked_via_manual_on_span_end(self):
        tracer = Tracer("test")
        s1 = tracer.start_span("a")
        s2 = tracer.start_span("b")
        s1.end()
        tracer.on_span_end(s1)
        s2.end()
        tracer.on_span_end(s2)
        assert len(tracer.get_finished_spans()) == 2

    def test_get_trace_filters_by_trace_id(self):
        tracer = Tracer("test")
        with tracer.start_as_current_span("a") as s1:
            pass
        with tracer.start_as_current_span("b"):
            pass
        trace_id = s1.context.trace_id
        result = tracer.get_trace(trace_id)
        assert len(result) == 1
        assert result[0].context.trace_id == trace_id

    def test_get_trace_empty(self):
        tracer = Tracer("test")
        assert tracer.get_trace("nonexistent") == []

    def test_clear(self):
        tracer = Tracer("test")
        s = tracer.start_span("a")
        s.end()
        tracer.clear()
        assert tracer.get_finished_spans() == []
        assert tracer._active_spans == {}

    def test_exporter_called_on_end(self):
        mock_exporter = MagicMock()
        tracer = Tracer("test", exporter=mock_exporter)
        with tracer.start_as_current_span("op"):
            pass
        mock_exporter.export.assert_called_once()

    def test_exporter_exception_suppressed(self):
        def bad_export(spans):
            raise RuntimeError("export failed")

        tracer = Tracer("test", exporter=MagicMock(export=bad_export))
        with tracer.start_as_current_span("op"):
            pass
        assert len(tracer.get_finished_spans()) == 1

    def test_start_span_with_kind_and_attributes(self):
        tracer = Tracer("test")
        span = tracer.start_span(
            "op", kind=SpanKind.CLIENT, attributes={"k": "v"}
        )
        assert span.kind == SpanKind.CLIENT
        assert span.attributes["k"] == "v"

    def test_concurrent_starts(self):
        tracer = Tracer("test")
        spans = []

        def start_and_end():
            with tracer.start_as_current_span("t") as s:
                pass
            spans.append(s)

        threads = [threading.Thread(target=start_and_end) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(tracer.get_finished_spans()) == 20


class TestTextMapPropagator:
    def test_inject_extract_roundtrip(self):
        prop = TextMapPropagator()
        ctx = SpanContext.create()
        carrier = {}
        prop.inject(ctx, carrier)
        extracted = prop.extract(carrier)
        assert extracted.trace_id == ctx.trace_id
        assert extracted.span_id == ctx.span_id
        assert extracted.is_valid is True
        assert extracted.trace_flags == ctx.trace_flags

    def test_extract_missing_header(self):
        prop = TextMapPropagator()
        ctx = prop.extract({})
        assert ctx.is_valid is False

    def test_extract_bad_header(self):
        prop = TextMapPropagator()
        ctx = prop.extract({"traceparent": "garbage"})
        assert ctx.is_valid is False

    def test_extract_wrong_version(self):
        prop = TextMapPropagator()
        carrier = {"traceparent": f"01-{('a'*32)}-{('b'*16)}-00"}
        ctx = prop.extract(carrier)
        assert ctx.is_valid is False

    def test_extract_bad_trace_id(self):
        prop = TextMapPropagator()
        carrier = {"traceparent": f"00-{'g'*32}-{'b'*16}-00"}
        ctx = prop.extract(carrier)
        assert ctx.is_valid is False

    def test_extract_bad_span_id(self):
        prop = TextMapPropagator()
        carrier = {"traceparent": f"00-{'a'*32}-{'g'*16}-00"}
        ctx = prop.extract(carrier)
        assert ctx.is_valid is False

    def test_extract_bad_flags(self):
        prop = TextMapPropagator()
        carrier = {"traceparent": f"00-{'a'*32}-{'b'*16}-zz"}
        ctx = prop.extract(carrier)
        assert ctx.is_valid is False

    def test_inject_format(self):
        prop = TextMapPropagator()
        ctx = SpanContext(trace_id="a" * 32, span_id="b" * 16, trace_flags=1)
        carrier = {}
        prop.inject(ctx, carrier)
        assert carrier["traceparent"] == f"00-{'a'*32}-{'b'*16}-01"


class TestTardisSpanExporter:
    def _make_span(self, trace_id="t" * 32, kind=SpanKind.INTERNAL, status=StatusCode.UNSET):
        ctx = SpanContext(trace_id=trace_id, span_id="s" * 16, is_valid=True)
        span = Span("op", ctx, kind=kind)
        span.set_status(status)
        span.end()
        return span

    def test_span_to_step_internal(self):
        step = TardisSpanExporter._span_to_step(
            self._make_span(kind=SpanKind.INTERNAL)
        )
        assert step.type.value == "orchestration_event"

    def test_span_to_step_client(self):
        step = TardisSpanExporter._span_to_step(
            self._make_span(kind=SpanKind.CLIENT)
        )
        assert step.type.value == "tool_call"

    def test_span_to_step_consumer(self):
        step = TardisSpanExporter._span_to_step(
            self._make_span(kind=SpanKind.CONSUMER)
        )
        assert step.type.value == "tool_result"

    def test_span_to_step_error_overrides(self):
        step = TardisSpanExporter._span_to_step(
            self._make_span(kind=SpanKind.CLIENT, status=StatusCode.ERROR)
        )
        assert step.type.value == "error"
        assert step.success is False

    def test_span_to_step_extracts_input_output(self):
        ctx = SpanContext(trace_id="t" * 32, span_id="s" * 16, is_valid=True)
        span = Span("op", ctx, attributes={"input": {"q": 1}, "output": {"a": 2}, "extra": "x"})
        span.end()
        step = TardisSpanExporter._span_to_step(span)
        assert step.input == {"q": 1}
        assert step.output == {"a": 2}
        assert step.metadata == {"extra": "x"}

    def test_export_buffers_and_saves(self):
        mock_store = MagicMock()
        exporter = TardisSpanExporter(store=mock_store)
        span = self._make_span(trace_id="a" * 32)
        exporter.export([span])
        mock_store.save_trace.assert_called_once()

    def test_shutdown_flushes_buffer(self):
        mock_store = MagicMock()
        exporter = TardisSpanExporter(store=mock_store)
        span = self._make_span(trace_id="a" * 32)
        with exporter._lock:
            exporter._buffer.append(span)
        exporter.shutdown()
        mock_store.save_trace.assert_called_once()

    def test_shutdown_empty_buffer(self):
        mock_store = MagicMock()
        exporter = TardisSpanExporter(store=mock_store)
        exporter.shutdown()
        mock_store.save_trace.assert_not_called()

    def test_grouping_by_trace_id(self):
        mock_store = MagicMock()
        exporter = TardisSpanExporter(store=mock_store)
        s1 = self._make_span(trace_id="a" * 32)
        s2 = self._make_span(trace_id="a" * 32)
        s3 = self._make_span(trace_id="b" * 32)
        exporter.export([s1, s2, s3])
        assert mock_store.save_trace.call_count == 2


class TestGlobalTracer:
    def setup_method(self):
        import tardis.distributed.tracer as mod
        mod._global_tracer = None

    def teardown_method(self):
        import tardis.distributed.tracer as mod
        mod._global_tracer = None

    def test_get_creates_default(self):
        t = get_global_tracer()
        assert isinstance(t, Tracer)
        assert t.name == "tardis"

    def test_get_returns_same_instance(self):
        t1 = get_global_tracer()
        t2 = get_global_tracer()
        assert t1 is t2

    def test_set_and_get(self):
        custom = Tracer("custom")
        set_global_tracer(custom)
        assert get_global_tracer() is custom

    def test_get_with_custom_name(self):
        t = get_global_tracer(name="my_service")
        assert t.name == "my_service"


class TestSecurityAndSanitization:
    def test_valid_hex_32(self):
        assert _valid_hex("a" * 32, 32)
        assert not _valid_hex("g" * 32, 32)
        assert not _valid_hex("a" * 31, 32)

    def test_valid_hex_16(self):
        assert _valid_hex("a" * 16, 16)
        assert not _valid_hex("g" * 16, 16)
        assert not _valid_hex("a" * 15, 16)

    def test_resource_max_bytes_limit(self):
        big_val = "x" * 2000
        resource = {"key1": big_val, "key2": "ok"}
        result = _sanitize_resource(resource)
        assert "key2" not in result

    def test_resource_none_keys_skipped(self):
        resource = {None: "bad", "good": "val"}
        result = _sanitize_resource(resource)
        assert None not in result
        assert result["good"] == "val"

    def test_resource_empty(self):
        assert _sanitize_resource({}) == {}

    def test_span_attribute_none_key_filtered_on_init(self):
        ctx = SpanContext.create()
        span = Span("op", ctx, attributes={None: "bad", "k": "v"})
        assert None not in span.attributes
        assert span.attributes["k"] == "v"

    def test_span_started_with_invalid_context_accepted(self):
        ctx = SpanContext(trace_id="", span_id="", is_valid=False)
        span = Span("op", ctx)
        assert span.context.is_valid is False
        span.end()
