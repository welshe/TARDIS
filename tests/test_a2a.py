import threading
import time

from tardis.a2a import (
    A2ACoordinator,
    A2AMessage,
    AgentProtocol,
    Blackboard,
    MessageBus,
    MessagePriority,
    MessageType,
)


def _drain_bus(mbus: MessageBus) -> None:
    with mbus._lock:
        for q in mbus._queues.values():
            q.clear()


class TestA2AMessage:
    def test_create_default(self):
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="alice",
            subject="hello",
            payload={"text": "hi"},
        )
        assert msg.type == MessageType.REQUEST
        assert msg.from_agent == "alice"
        assert msg.subject == "hello"
        assert msg.payload == {"text": "hi"}
        assert msg.to_agent is None
        assert msg.priority == MessagePriority.NORMAL
        assert msg.ttl == 300.0
        assert msg.id is not None
        assert msg.timestamp > 0

    def test_to_dict_roundtrip(self):
        orig = A2AMessage(
            type=MessageType.TASK_RESULT,
            from_agent="bob",
            to_agent="alice",
            subject="task_done",
            payload={"status": "ok"},
            priority=MessagePriority.HIGH,
            reply_to="req-1",
            correlation_id="corr-1",
            ttl=60.0,
        )
        d = orig.to_dict()
        restored = A2AMessage.from_dict(d)
        assert restored.id == orig.id
        assert restored.type == orig.type
        assert restored.from_agent == orig.from_agent
        assert restored.to_agent == orig.to_agent
        assert restored.subject == orig.subject
        assert restored.payload == orig.payload
        assert restored.priority == orig.priority
        assert restored.reply_to == orig.reply_to
        assert restored.correlation_id == orig.correlation_id
        assert restored.ttl == orig.ttl
        assert restored.timestamp == orig.timestamp

    def test_is_expired_false(self):
        msg = A2AMessage(
            type=MessageType.HEARTBEAT,
            from_agent="alice",
            subject="hb",
            payload={},
            ttl=3600.0,
        )
        assert not msg.is_expired

    def test_is_expired_true(self):
        msg = A2AMessage(
            type=MessageType.HEARTBEAT,
            from_agent="alice",
            subject="hb",
            payload={},
            ttl=-1.0,
        )
        assert msg.is_expired

    def test_validate_ok(self):
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="alice",
            subject="test",
            payload={},
        )
        assert msg.validate()

    def test_validate_empty_agent_fails(self):
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="",
            subject="test",
            payload={},
        )
        assert not msg.validate()

    def test_validate_empty_subject_fails(self):
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="alice",
            subject="",
            payload={},
        )
        assert not msg.validate()

    def test_ttl_expires_message(self):
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="alice",
            subject="exp",
            payload={},
            ttl=0.01,
        )
        assert not msg.is_expired
        time.sleep(0.02)
        assert msg.is_expired

    def test_priority_values(self):
        assert MessagePriority.LOW.value == 0
        assert MessagePriority.NORMAL.value == 5
        assert MessagePriority.HIGH.value == 10
        assert MessagePriority.URGENT.value == 20

    def test_message_type_values(self):
        assert MessageType.REQUEST.value == "request"
        assert MessageType.RESPONSE.value == "response"
        assert MessageType.ERROR.value == "error"


class TestBlackboard:
    def test_write_read_delete(self):
        bb = Blackboard()
        assert bb.write("ns", "key", "val")
        assert bb.read("ns", "key") == "val"
        assert bb.delete("ns", "key")
        assert bb.read("ns", "key") is None

    def test_namespace_isolation(self):
        bb = Blackboard()
        bb.write("ns1", "k", "v1")
        bb.write("ns2", "k", "v2")
        assert bb.read("ns1", "k") == "v1"
        assert bb.read("ns2", "k") == "v2"

    def test_list_keys(self):
        bb = Blackboard()
        bb.write("ns", "a", 1)
        bb.write("ns", "b", 2)
        bb.write("ns", "c", 3)
        keys = bb.list_keys("ns")
        assert sorted(keys) == ["a", "b", "c"]

    def test_list_namespaces(self):
        bb = Blackboard()
        bb.write("x", "k", 1)
        bb.write("y", "k", 2)
        nss = bb.list_namespaces()
        assert sorted(nss) == ["x", "y"]

    def test_search_substring(self):
        bb = Blackboard()
        bb.write("ns", "apple", "fruit")
        bb.write("ns", "application", "software")
        bb.write("ns", "banana", "yellow")
        results = bb.search("app")
        keys_found = {k for _, k, _ in results}
        assert "apple" in keys_found
        assert "application" in keys_found
        assert "banana" not in keys_found

    def test_get_stats(self):
        bb = Blackboard()
        bb.write("ns", "a", "hello")
        bb.write("ns", "b", "world")
        stats = bb.get_stats()
        assert stats["total_entries"] == 2
        assert stats["namespaces"]["ns"]["count"] == 2
        assert stats["namespaces"]["ns"]["size_estimate"] > 0

    def test_ttl_expiry(self):
        bb = Blackboard()
        bb.write("ns", "ephemeral", "data", ttl=0.01)
        assert bb.read("ns", "ephemeral") == "data"
        time.sleep(0.02)
        assert bb.read("ns", "ephemeral") is None

    def test_lru_eviction(self):
        bb = Blackboard(max_entries_per_ns=3)
        bb.write("ns", "a", 1)
        bb.write("ns", "b", 2)
        bb.write("ns", "c", 3)
        bb.write("ns", "d", 4)
        assert bb.read("ns", "a") is None
        assert bb.read("ns", "d") == 4

    def test_lru_read_updates_order(self):
        bb = Blackboard(max_entries_per_ns=3)
        bb.write("ns", "a", 1)
        bb.write("ns", "b", 2)
        bb.write("ns", "c", 3)
        bb.read("ns", "a")
        bb.write("ns", "d", 4)
        assert bb.read("ns", "b") is None
        assert bb.read("ns", "a") == 1
        assert bb.read("ns", "d") == 4

    def test_max_value_size_rejected(self):
        bb = Blackboard(max_value_size=10)
        assert not bb.write("ns", "big", "x" * 11)
        assert bb.read("ns", "big") is None

    def test_watch_callback(self):
        bb = Blackboard()
        events = []

        def cb(namespace, key, value):
            events.append((namespace, key, value))

        bb.watch("ns", "k", cb)
        bb.write("ns", "k", "v")
        assert events == [("ns", "k", "v")]

    def test_thread_safety(self):
        bb = Blackboard()
        n_threads = 10
        writes_per = 50
        barrier = threading.Barrier(n_threads)

        def worker(worker_id):
            barrier.wait()
            for i in range(writes_per):
                bb.write("shared", f"k-{worker_id}-{i}", worker_id)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        keys = bb.list_keys("shared")
        assert len(keys) == n_threads * writes_per
        stats = bb.get_stats()
        assert stats["namespaces"]["shared"]["count"] == n_threads * writes_per

    def test_delete_nonexistent(self):
        bb = Blackboard()
        assert not bb.delete("nonexistent", "nope")

    def test_read_nonexistent(self):
        bb = Blackboard()
        assert bb.read("nonexistent", "nope") is None

    def test_search_across_namespaces(self):
        bb = Blackboard()
        bb.write("ns1", "shared_key", "v1")
        bb.write("ns2", "shared_key", "v2")
        results = bb.search("shared_key")
        assert len(results) == 2

    def test_clear_namespace(self):
        bb = Blackboard()
        bb.write("ns1", "a", 1)
        bb.write("ns2", "b", 2)
        bb.clear(namespace="ns1")
        assert bb.read("ns1", "a") is None
        assert bb.read("ns2", "b") == 2

    def test_clear_all(self):
        bb = Blackboard()
        bb.write("ns1", "a", 1)
        bb.write("ns2", "b", 2)
        bb.clear()
        assert bb.list_namespaces() == []


class TestAgentProtocol:
    class TestAgent(AgentProtocol):
        def handle_message(self, message):
            return A2AMessage(
                type=MessageType.RESPONSE,
                from_agent=self.agent_id,
                to_agent=message.from_agent,
                subject=message.subject,
                payload={"echo": message.payload},
            )

        def get_capabilities(self):
            return list(self.capabilities)

    def test_handle_message_returns_reply(self):
        agent = self.TestAgent("agent-1", "Test Agent", capabilities={"ping"})
        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="caller",
            subject="ping",
            payload={"data": 1},
        )
        reply = agent.handle_message(msg)
        assert reply.type == MessageType.RESPONSE
        assert reply.to_agent == "caller"
        assert reply.subject == "ping"
        assert reply.payload == {"echo": {"data": 1}}

    def test_send_message(self):
        bus = MessageBus()
        agent = self.TestAgent("sender", "Sender")
        receiver = self.TestAgent("receiver", "Receiver")
        bus.register(agent)
        bus.register(receiver)
        ok = agent.send_message(bus, "receiver", "hello", {"m": 1})
        assert ok
        msg = bus.receive("receiver")
        assert msg is not None
        assert msg.subject == "hello"
        assert msg.from_agent == "sender"

    def test_broadcast(self):
        bus = MessageBus()
        a1 = self.TestAgent("a1", "A1")
        a2 = self.TestAgent("a2", "A2")
        a3 = self.TestAgent("a3", "A3")
        for a in (a1, a2, a3):
            bus.register(a)
        a1.broadcast(bus, "announce", {"msg": "hi"})
        assert bus.receive("a2") is not None
        assert bus.receive("a3") is not None
        assert bus.receive("a1") is None

    def test_to_dict(self):
        agent = self.TestAgent("id-007", "James", capabilities={"stealth", "charm"})
        d = agent.to_dict()
        assert d["agent_id"] == "id-007"
        assert d["name"] == "James"
        assert "stealth" in d["capabilities"]
        assert "charm" in d["capabilities"]


class TestMessageBus:
    def test_register_unregister(self):
        bus = MessageBus()

        class FakeAgent(AgentProtocol):
            def handle_message(self, message):
                return None

            def get_capabilities(self):
                return []

        agent = FakeAgent("fab", "Fake")
        bus.register(agent)
        assert bus.get_queue_size("fab") == 0
        bus.unregister("fab")
        assert bus.get_queue_size("fab") == 0
        bus.send(
            A2AMessage(MessageType.REQUEST, "fab", "s", {}, to_agent="fab")
        )
        assert bus.get_queue_size("fab") == 0

    def test_send_routes_to_correct_inbox(self):
        bus = MessageBus()

        class FakeAgent(AgentProtocol):
            def handle_message(self, message):
                return None

            def get_capabilities(self):
                return []

        a1 = FakeAgent("alpha", "Alpha")
        a2 = FakeAgent("beta", "Beta")
        bus.register(a1)
        bus.register(a2)

        msg = A2AMessage(
            type=MessageType.REQUEST,
            from_agent="alpha",
            to_agent="beta",
            subject="data",
            payload={},
        )
        assert bus.send(msg)
        assert bus.receive("beta") is not None
        assert bus.receive("alpha") is None

    def test_receive_fifo(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        a1 = FA("a1", "A1")
        a2 = FA("a2", "A2")
        bus.register(a1)
        bus.register(a2)

        bus.send(A2AMessage(MessageType.REQUEST, "a1", "s1", {}, to_agent="a2"))
        bus.send(A2AMessage(MessageType.REQUEST, "a1", "s2", {}, to_agent="a2"))
        assert bus.receive("a2").subject == "s1"
        assert bus.receive("a2").subject == "s2"
        assert bus.receive("a2") is None

    def test_broadcast_all_except_sender(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        for aid in ("x", "y", "z"):
            bus.register(FA(aid, aid))

        msg = A2AMessage(MessageType.BROADCAST, "x", "topic", {})
        bus.broadcast(msg)
        assert bus.receive("y") is not None
        assert bus.receive("z") is not None
        assert bus.receive("x") is None

    def test_subscribe_publish(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("pub", "Pub"))
        bus.register(FA("sub1", "Sub1"))
        bus.register(FA("sub2", "Sub2"))
        bus.subscribe("sub1", "news")
        bus.subscribe("sub2", "news")

        msg = A2AMessage(MessageType.BROADCAST, "pub", "news", {"item": "test"})
        delivered = bus.publish(msg)
        assert delivered == 2
        assert bus.receive("sub1") is not None
        assert bus.receive("sub2") is not None

    def test_rate_limit_exceeded(self):
        bus = MessageBus(max_rate=3)

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("spammy", "Spammy"))
        bus.register(FA("victim", "Victim"))

        for i in range(3):
            ok = bus.send(
                A2AMessage(MessageType.REQUEST, "spammy", f"s{i}", {}, to_agent="victim")
            )
            assert ok
        ok = bus.send(
            A2AMessage(MessageType.REQUEST, "spammy", "s4", {}, to_agent="victim")
        )
        assert not ok

    def test_queue_size_limit_oldest_dropped(self):
        bus = MessageBus(queue_size=3)

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("snd", "Snd"))
        bus.register(FA("rcv", "Rcv"))
        for i in range(5):
            bus.send(
                A2AMessage(
                    MessageType.REQUEST, "snd", f"s{i}", {}, to_agent="rcv"
                )
            )
        assert bus.get_queue_size("rcv") == 3
        subjects = []
        while True:
            m = bus.receive("rcv")
            if m is None:
                break
            subjects.append(m.subject)
        assert subjects == ["s2", "s3", "s4"]

    def test_history_tracking(self):
        bus = MessageBus(history_size=10)

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("a", "A"))
        bus.register(FA("b", "B"))
        for i in range(5):
            bus.send(A2AMessage(MessageType.REQUEST, "a", f"m{i}", {}, to_agent="b"))
        hist = bus.get_history()
        assert len(hist) == 5

    def test_shutdown_clears_everything(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("a", "A"))
        bus.register(FA("b", "B"))
        bus.subscribe("a", "t")
        bus.flush()
        bus.shutdown()
        bus.send(
            A2AMessage(MessageType.REQUEST, "a", "s", {}, to_agent="b")
        )
        assert bus.get_queue_size("b") == 0
        assert len(bus.get_history()) == 0

    def test_send_expired_message_fails(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("a", "A"))
        bus.register(FA("b", "B"))
        msg = A2AMessage(
            MessageType.REQUEST, "a", "old", {}, to_agent="b", ttl=-1.0
        )
        assert not bus.send(msg)

    def test_send_unregistered_sender_fails(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("b", "B"))
        msg = A2AMessage(
            MessageType.REQUEST, "unknown", "s", {}, to_agent="b"
        )
        assert not bus.send(msg)

    def test_receive_skips_expired(self):
        bus = MessageBus()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return []

        bus.register(FA("a", "A"))
        bus.register(FA("b", "B"))
        bus.send(
            A2AMessage(MessageType.REQUEST, "a", "fresh", {}, to_agent="b")
        )
        bus.send(
            A2AMessage(MessageType.REQUEST, "a", "stale", {}, to_agent="b", ttl=-1.0)
        )
        msg = bus.receive("b")
        assert msg is not None
        assert msg.subject == "fresh"
        assert bus.receive("b") is None


class TestA2ACoordinator:
    def test_register_agent(self):
        coord = A2ACoordinator()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return ["skill"]

        agent = FA("agent-1", "Agent 1", capabilities={"skill"})
        coord.register_agent(agent)
        assert coord.bus.get_queue_size("agent-1") == 0

    def test_share_and_get_shared_state(self):
        coord = A2ACoordinator()
        assert coord.share_state("ns", "k", "v")
        assert coord.get_shared_state("ns", "k") == "v"

    def test_get_agent_status(self):
        coord = A2ACoordinator()

        class FA(AgentProtocol):
            def handle_message(self, m):
                return None

            def get_capabilities(self):
                return list(self.capabilities)

        coord.register_agent(FA("alpha", "Alpha", capabilities={"a", "b"}))
        status = coord.get_agent_status()
        assert "alpha" in status
        assert status["alpha"]["name"] == "Alpha"
        assert "a" in status["alpha"]["capabilities"]
