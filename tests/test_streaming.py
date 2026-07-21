import asyncio

import pytest

from tardis.streaming.streamer import (
    StreamEvent,
    StreamEventType,
    StreamSession,
    TraceStreamClient,
    TraceStreamer,
)


class TestStreamEventType:
    def test_values(self):
        assert StreamEventType.STEP_ADDED.value == "step_added"
        assert StreamEventType.TRACE_STARTED.value == "trace_started"
        assert StreamEventType.TRACE_COMPLETED.value == "trace_completed"
        assert StreamEventType.HEARTBEAT.value == "heartbeat"
        assert StreamEventType.COLLAB_JOIN.value == "collab_join"
        assert StreamEventType.COLLAB_CURSOR.value == "collab_cursor"


class TestStreamEvent:
    def test_creation(self):
        event = StreamEvent(
            trace_id="abc",
            event_type=StreamEventType.STEP_ADDED,
            data={"step_index": 5},
            source="recorder",
        )
        assert event.trace_id == "abc"
        assert event.event_type == StreamEventType.STEP_ADDED
        assert event.data["step_index"] == 5

    def test_default_timestamp(self):
        event = StreamEvent(trace_id="t", event_type=StreamEventType.HEARTBEAT)
        assert event.timestamp > 0

    def test_to_dict(self):
        event = StreamEvent(trace_id="abc", event_type=StreamEventType.STEP_ADDED,
                            data={"i": 1}, source="src")
        d = event.to_dict()
        assert d["trace_id"] == "abc"
        assert d["event_type"] == "step_added"
        assert d["data"]["i"] == 1
        assert d["source"] == "src"

    def test_from_dict(self):
        d = {"trace_id": "t1", "event_type": "step_added",
             "data": {"idx": 3}, "timestamp": 100.0, "source": "test"}
        event = StreamEvent.from_dict(d)
        assert event.trace_id == "t1"
        assert event.event_type == StreamEventType.STEP_ADDED
        assert event.data["idx"] == 3
        assert event.timestamp == 100.0

    def test_from_dict_defaults(self):
        d = {"trace_id": "t", "event_type": "heartbeat"}
        event = StreamEvent.from_dict(d)
        assert event.source == ""


class TestStreamSession:
    def test_creation(self):
        session = StreamSession(trace_id="abc")
        assert session.trace_id == "abc"
        assert session.clients == 0
        assert session.step_count == 0
        assert session.expired is False

    def test_defaults(self):
        session = StreamSession(trace_id="t")
        assert session.created_at > 0


class TestTraceStreamer:
    def test_create_session(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        sid = streamer.create_session("test_session")
        assert sid == "test_session"
        assert "test_session" in streamer._sessions

    def test_get_session_status(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        streamer.create_session("status_test")
        status = streamer.get_session_status("status_test")
        assert status is not None
        assert status["trace_id"] == "status_test"
        assert status["clients"] == 0

    def test_get_session_status_nonexistent(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        assert streamer.get_session_status("no_such") is None

    def test_list_sessions_empty(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        assert streamer.list_sessions() == []

    def test_list_sessions(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        streamer.create_session("session_a")
        streamer.create_session("session_b")
        sessions = streamer.list_sessions()
        assert len(sessions) == 2

    def test_publish_event_no_session(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        event = StreamEvent(trace_id="no_session", event_type=StreamEventType.HEARTBEAT)
        streamer.publish_event(event)

    def test_publish_event_updates_step_count(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        streamer.create_session("step_count_test")
        event = StreamEvent(trace_id="step_count_test", event_type=StreamEventType.STEP_ADDED)
        streamer.publish_event(event)
        status = streamer.get_session_status("step_count_test")
        assert status["step_count"] == 1

    def test_expire_session(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        streamer.create_session("expire_me")
        streamer.expire_session("expire_me")
        status = streamer.get_session_status("expire_me")
        assert status["expired"] is True

    def test_subscribe_nonexistent_session_raises(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19876)
        with pytest.raises(ValueError, match="No active session"):
            streamer.subscribe("no_session")

    def test_start_stop(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19877)
        streamer.start()
        assert streamer._running is True
        streamer.stop()
        assert streamer._running is False

    def test_start_idempotent(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19878)
        streamer.start()
        streamer.start()
        streamer.stop()

    def test_publish_to_expired_session(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19879)
        streamer.create_session("expired_pub")
        streamer.expire_session("expired_pub")
        event = StreamEvent(trace_id="expired_pub", event_type=StreamEventType.STEP_ADDED)
        streamer.publish_event(event)

    def test_subscribe_and_unsubscribe(self):
        streamer = TraceStreamer(host="127.0.0.1", port=19880)
        streamer.create_session("sub_test")
        q = streamer.subscribe("sub_test")
        assert q is not None
        streamer.unsubscribe("sub_test", q)
        assert q not in streamer._sessions["sub_test"].subscribers


class TestTraceStreamClient:
    def test_client_creation(self):
        client = TraceStreamClient(host="127.0.0.1", port=19999)
        assert client.host == "127.0.0.1"
        assert client.port == 19999
        assert client._connected is False

    def test_client_connect_refused(self):
        client = TraceStreamClient(host="127.0.0.1", port=19998)

        async def _test():
            result = await client.connect("test_trace")
            assert result is False

        asyncio.run(_test())

    def test_add_remove_listener(self):
        client = TraceStreamClient()

        def noop(event):
            pass

        client.add_listener(noop)
        assert noop in client._listeners
        client.remove_listener(noop)
        assert noop not in client._listeners

    def test_remove_nonexistent_listener(self):
        client = TraceStreamClient()
        client.remove_listener(lambda e: None)


class TestStreamEventSerialization:
    def test_roundtrip(self):
        event = StreamEvent(trace_id="rt", event_type=StreamEventType.TRACE_COMPLETED,
                            data={"steps": 42}, source="rec")
        d = event.to_dict()
        restored = StreamEvent.from_dict(d)
        assert restored.trace_id == "rt"
        assert restored.event_type == StreamEventType.TRACE_COMPLETED
        assert restored.data["steps"] == 42
        assert restored.source == "rec"

    def test_all_event_types_serialize(self):
        for etype in StreamEventType:
            event = StreamEvent(trace_id="t", event_type=etype)
            d = event.to_dict()
            restored = StreamEvent.from_dict(d)
            assert restored.event_type == etype
