import pytest

from tardis.orchestration import (
    Agent,
    AgentCapability,
    AgentState,
    Orchestrator,
    SharedMemory,
    Task,
    TaskPriority,
    TaskStatus,
    orchestrate,
)


class TestAgent:
    def test_agent_creation(self):
        agent = Agent("test_agent", capabilities={AgentCapability.browser})
        assert agent.name == "test_agent"
        assert agent.state == AgentState.idle
        assert agent.has_capability(AgentCapability.browser)
        assert not agent.has_capability(AgentCapability.terminal)

    def test_agent_state_transitions(self):
        agent = Agent("test")
        assert agent.state == AgentState.idle

        agent.assign(Task("do something"))
        assert agent.state == AgentState.running

    def test_agent_run_success(self):
        agent = Agent("test")
        task = Task("echo")

        def echo_fn(task):
            return f"done: {task.description}"

        agent.assign(task, fn=echo_fn)
        result = agent.run()
        assert result == "done: echo"
        assert agent.state == AgentState.idle

    def test_agent_run_error(self):
        agent = Agent("test")
        task = Task("fail")

        def fail_fn(task):
            raise ValueError("intentional")

        agent.assign(task, fn=fail_fn)
        with pytest.raises(ValueError, match="intentional"):
            agent.run()
        assert agent.state == AgentState.error
        assert "intentional" in agent.error_message

    def test_agent_stop(self):
        agent = Agent("test")
        agent.stop()
        assert agent.state == AgentState.stopped

    def test_agent_wait(self):
        agent = Agent("test")
        agent.wait()
        assert agent.state == AgentState.waiting

    def test_agent_to_dict(self):
        agent = Agent(
            "browser",
            capabilities={AgentCapability.browser, AgentCapability.vision},
            model="gpt-4o",
        )
        d = agent.to_dict()
        assert d["name"] == "browser"
        assert d["state"] == "idle"
        assert "browser" in d["capabilities"]
        assert d["model"] == "gpt-4o"
        assert d["current_task"] is None

    def test_agent_recorder(self):
        agent = Agent("test")
        rec = object()
        agent.set_recorder(rec)
        assert agent.recorder is rec


class TestTask:
    def test_task_creation(self):
        task = Task(
            "browse page", required_capabilities={"browser"}, priority=TaskPriority.high
        )
        assert task.description == "browse page"
        assert task.status == TaskStatus.pending
        assert task.priority == TaskPriority.high
        assert "browser" in task.required_capabilities

    def test_task_lifecycle(self):
        task = Task("run tests")
        assert task.status == TaskStatus.pending

        task.mark_assigned("agent-1")
        assert task.status == TaskStatus.assigned
        assert task.assigned_agent == "agent-1"

        task.mark_running()
        assert task.status == TaskStatus.running
        assert task.started_at is not None

        task.mark_completed({"pass": True})
        assert task.status == TaskStatus.completed
        assert task.result == {"pass": True}
        assert task.completed_at is not None
        assert task.duration_seconds is not None

    def test_task_failure(self):
        task = Task("failing task")
        task.mark_failed("something broke")
        assert task.status == TaskStatus.failed
        assert task.error == "something broke"
        assert task.completed_at is not None

    def test_task_cancel(self):
        task = Task("cancelled")
        task.mark_cancelled()
        assert task.status == TaskStatus.cancelled

    def test_task_dependencies(self):
        task = Task("dep task", dependencies={"other-task-id"})
        assert "other-task-id" in task.dependencies

    def test_task_retries(self):
        task = Task("retry task")
        assert task.can_retry()
        task.retries = 3
        assert not task.can_retry()

    def test_task_to_dict(self):
        task = Task("test", priority=TaskPriority.critical)
        d = task.to_dict()
        assert d["description"] == "test"
        assert d["status"] == "pending"
        assert d["priority"] == 20

    def test_task_duration_none_before_start(self):
        task = Task("not started")
        assert task.duration_seconds is None


class TestSharedMemory:
    def test_put_get(self):
        mem = SharedMemory()
        mem.put("key1", "value1")
        assert mem.get("key1") == "value1"

    def test_namespace_isolation(self):
        mem = SharedMemory()
        mem.put("x", 1, namespace="a")
        mem.put("x", 2, namespace="b")
        assert mem.get("x", namespace="a") == 1
        assert mem.get("x", namespace="b") == 2

    def test_default_value(self):
        mem = SharedMemory()
        assert mem.get("nonexistent", default=42) == 42

    def test_delete(self):
        mem = SharedMemory()
        mem.put("key", "val")
        assert mem.get("key") == "val"
        mem.delete("key")
        assert mem.get("key") is None

    def test_list_keys(self):
        mem = SharedMemory()
        mem.put("a", 1, namespace="ns1")
        mem.put("b", 2, namespace="ns1")
        mem.put("c", 3, namespace="ns2")
        keys = mem.list_keys("ns1")
        assert len(keys) == 2

    def test_snapshot_restore(self):
        mem = SharedMemory()
        mem.put("x", 100)
        snap = mem.snapshot()

        mem.put("y", 200)
        assert mem.get("y") == 200

        mem.restore(snap)
        assert mem.get("x") == 100
        assert mem.get("y") is None

    def test_cas_success(self):
        mem = SharedMemory()
        mem.put("x", "old")
        meta = mem.get_meta("x")
        assert mem.cas("x", meta["version"], "new")
        assert mem.get("x") == "new"

    def test_cas_conflict(self):
        mem = SharedMemory()
        mem.put("x", "old")
        assert not mem.cas("x", 9999, "new")
        assert mem.get("x") == "old"

    def test_clear_namespace(self):
        mem = SharedMemory()
        mem.put("a", 1, namespace="ns")
        mem.put("b", 2, namespace="other")
        mem.clear(namespace="ns")
        assert mem.get("a", namespace="ns") is None
        assert mem.get("b", namespace="other") == 2

    def test_clear_all(self):
        mem = SharedMemory()
        mem.put("a", 1)
        mem.put("b", 2)
        mem.clear()
        assert len(mem) == 0

    def test_contains(self):
        mem = SharedMemory()
        mem.put("exists", True)
        assert "exists" in mem
        assert "nope" not in mem

    def test_version_increment(self):
        mem = SharedMemory()
        v1 = mem.version
        mem.put("x", 1)
        v2 = mem.version
        assert v2 > v1

    def test_ttl_expiry(self):
        mem = SharedMemory()
        mem.put("ephemeral", "gone", ttl=-1.0)
        assert mem.get("ephemeral") is None


class TestOrchestrator:
    def test_register_agent(self):
        orch = Orchestrator()
        agent = Agent("a1")
        orch.register(agent)
        assert "a1" in [a.name for a in orch.agents.values()]

    def test_unregister_agent(self):
        orch = Orchestrator()
        agent = Agent("a1")
        orch.register(agent)
        orch.unregister(agent.id)
        assert len(orch.agents) == 0

    def test_submit_task(self):
        orch = Orchestrator()
        task = Task("do work")
        orch.submit(task)
        assert len(orch._pending) == 1

    def test_run_sequential(self):
        orch = Orchestrator()
        agent = Agent("worker", capabilities={AgentCapability.terminal})
        orch.register(agent)

        task = Task("run tests", required_capabilities={"terminal"})
        orch.submit(task)

        results = orch.run_sequential(
            fn_map={"worker": lambda t: f"ok: {t.description}"}
        )
        assert len(results) == 1
        assert results[0].status == TaskStatus.completed

    def test_run_parallel(self):
        orch = Orchestrator(max_workers=2)
        for i in range(2):
            orch.register(Agent(f"agent-{i}", capabilities={AgentCapability.terminal}))

        tasks = [
            Task(f"task-{i}", required_capabilities={"terminal"}) for i in range(4)
        ]
        for t in tasks:
            orch.submit(t)

        fn_map = {f"agent-{i}": lambda t: f"done {t.description}" for i in range(2)}
        results = orch.run_parallel(fn_map)
        assert len(results) == 4

    def test_no_agent_for_task(self):
        orch = Orchestrator()
        task = Task("needs browser", required_capabilities={"browser"})
        orch.submit(task)

        results = orch.run_sequential()
        assert len(results) == 1
        assert results[0].status == TaskStatus.failed

    def test_get_status(self):
        orch = Orchestrator()
        orch.register(Agent("a1"))
        status = orch.get_status()
        assert "agents" in status
        assert status["pending_tasks"] == 0

    def test_orchestrate_convenience(self):
        agents = [Agent("worker", capabilities={AgentCapability.terminal})]
        tasks = [Task("hello", required_capabilities={"terminal"})]

        orch, results = orchestrate(
            tasks,
            agents,
            fn_map={"worker": lambda t: t.description},
            max_workers=1,
            parallel=False,
        )

        assert len(results) == 1
        assert results[0].status == TaskStatus.completed
        assert results[0].result == "hello"

    def test_context_manager(self):
        with Orchestrator() as orch:
            orch.register(Agent("a1"))
            assert len(orch.agents) == 1

    def test_recorder_integration(self):
        class FakeRecorder:
            def __init__(self):
                self.events = []

            def log(self, step_type, input, output, metadata=None):
                self.events.append((step_type, input, output, metadata))

        rec = FakeRecorder()
        orch = Orchestrator()
        orch.set_recorder(rec)

        agent = Agent("worker", capabilities={AgentCapability.terminal})
        orch.register(agent)
        task = Task("test")
        orch.submit(task)
        orch.run_sequential(fn_map={"worker": lambda t: "ok"})

        assert len(rec.events) >= 2  # task_started + task_completed
