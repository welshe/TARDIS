"""
Multi-agent Orchestrator.

Manages a pool of Agents, distributes Tasks based on capability matching
and priority, coordinates via SharedMemory, and records all orchestration
events through TARDIS for full traceability.
"""
from __future__ import annotations
from typing import Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
import threading
import time
import uuid

from .agent import Agent, AgentState, AgentCapability
from .task import Task, TaskStatus, TaskPriority
from .memory import SharedMemory

from ..models import StepType


@dataclass
class Orchestrator:
    """
    Multi-agent orchestrator with task routing and shared memory.

    Manages a pool of Agents, distributes Tasks based on capability
    matching and priority, and records orchestration decisions as TARDIS
    Steps for full traceability.

    Usage:
        orch = Orchestrator(max_workers=4)
        orch.register(agent_a)
        orch.register(agent_b)

        task = Task("fix the build", required_capabilities={"terminal"})
        orch.submit(task, fn=my_agent_fn)

        results = orch.run()
    """

    agents: dict[str, Agent] = field(default_factory=dict)
    max_workers: int = 4

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    memory: SharedMemory = field(default_factory=SharedMemory)
    _pending: list[Task] = field(default_factory=list)
    _completed: list[Task] = field(default_factory=list)
    _failed: list[Task] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _executor: Optional[ThreadPoolExecutor] = None
    _recorder: Optional[Any] = field(default=None, repr=False)

    def register(self, agent: Agent) -> "Orchestrator":
        with self._lock:
            self.agents[agent.id] = agent
        return self

    def unregister(self, agent_id: str):
        with self._lock:
            self.agents.pop(agent_id, None)

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    def submit(self, task: Task, fn: Optional[Callable] = None):
        with self._lock:
            self._pending.append(task)

    def submit_many(self, tasks: list[Task]):
        with self._lock:
            self._pending.extend(tasks)

    def _find_agent(self, task: Task) -> Optional[Agent]:
        required = {AgentCapability(c) for c in task.required_capabilities}
        # First try to find an idle agent with required capabilities
        for agent in self.agents.values():
            if agent.state == AgentState.idle and required.issubset(agent.capabilities):
                return agent
        # Fallback: assign to any idle agent (may lack capabilities - caller should handle)
        for agent in self.agents.values():
            if agent.state == AgentState.idle:
                return agent
        # Last resort: try waiting agents with required capabilities
        for agent in self.agents.values():
            if agent.state == AgentState.waiting and required.issubset(agent.capabilities):
                return agent
        return None

    def _log_event(self, event_type: str, data: dict):
        if self._recorder:
            self._recorder.log(
                StepType.orchestration_event,
                input={"event": event_type, "orchestrator_id": self.id},
                output=data,
                metadata={"source": "orchestrator"},
            )

    def _execute_task(self, task: Task, agent: Agent, fn: Callable) -> Any:
        agent.assign(task)
        task.mark_running()
        self._log_event("task_started", {
            "task_id": task.id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "task_description": task.description,
        })

        try:
            result = fn(task)
            task.mark_completed(result)
            self._log_event("task_completed", {
                "task_id": task.id,
                "agent_id": agent.id,
                "duration_ms": int(task.duration_seconds * 1000) if task.duration_seconds else 0,
            })
            agent.state = AgentState.idle
            return result
        except Exception as e:
            task.mark_failed(str(e))
            self._log_event("task_failed", {
                "task_id": task.id,
                "agent_id": agent.id,
                "error": str(e),
            })
            agent.state = AgentState.error
            agent.error_message = str(e)
            raise

    def run_parallel(self, fn_map: dict[str, Callable] = None, strict_capabilities: bool = False) -> list[Task]:
        """
        Run all pending tasks in parallel using the thread pool.

        fn_map maps capability strings to agent functions.
        Tasks are routed to idle agents based on capability matching.
        
        Args:
            fn_map: Dictionary mapping agent names or task descriptions to callables
            strict_capabilities: If True, tasks without capable agents will fail immediately
                               instead of falling back to any available agent
        """
        fn_map = fn_map or {}
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        futures: dict[Future, tuple[Task, Agent]] = {}

        with self._lock:
            tasks_to_run = self._pending[:]
            self._pending = []

        tasks_to_run.sort(key=lambda t: t.priority.value if isinstance(t.priority, TaskPriority) else t.priority, reverse=True)

        for task in tasks_to_run:
            required = {AgentCapability(c) for c in task.required_capabilities}
            agent = None
            
            # Find agent with required capabilities
            for a in self.agents.values():
                if a.state == AgentState.idle and required.issubset(a.capabilities):
                    agent = a
                    break
            
            # If no capable agent found and strict mode enabled, fail the task
            if agent is None and strict_capabilities:
                task.mark_failed("No agent with required capabilities")
                with self._lock:
                    self._failed.append(task)
                self._log_event("task_failed", {"task_id": task.id, "reason": "no_capable_agent_strict_mode"})
                continue
            
            # Fallback: find any idle agent (non-strict mode)
            if agent is None:
                for a in self.agents.values():
                    if a.state == AgentState.idle:
                        agent = a
                        self._log_event("capability_mismatch", {
                            "task_id": task.id,
                            "required": list(required),
                            "assigned_agent": a.id,
                            "agent_capabilities": list(a.capabilities)
                        })
                        break
            
            if agent is None:
                with self._lock:
                    self._pending.append(task)
                self._log_event("task_queued", {"task_id": task.id, "reason": "no_idle_agent"})
                continue

            fn = fn_map.get(agent.name) or fn_map.get(task.description)
            if fn is None:
                task.mark_failed("No function mapped for agent")
                with self._lock:
                    self._failed.append(task)
                continue

            task.mark_assigned(agent.id)
            future = self._executor.submit(self._execute_task, task, agent, fn)
            futures[future] = (task, agent)

        for future in as_completed(futures):
            task, agent = futures[future]
            try:
                future.result()
                with self._lock:
                    self._completed.append(task)
            except Exception:
                with self._lock:
                    self._failed.append(task)

        self._executor.shutdown(wait=True)
        self._executor = None

        all_done = self._completed + self._failed
        self._log_event("run_completed", {
            "total": len(all_done),
            "completed": len(self._completed),
            "failed": len(self._failed),
        })

        return all_done

    def run_sequential(self, fn_map: dict[str, Callable] = None) -> list[Task]:
        """
        Run pending tasks sequentially in priority order.
        """
        fn_map = fn_map or {}

        with self._lock:
            tasks_to_run = sorted(
                self._pending,
                key=lambda t: t.priority.value if isinstance(t.priority, TaskPriority) else t.priority,
                reverse=True,
            )
            self._pending = []

        results = []

        for task in tasks_to_run:
            agent = self._find_agent(task)
            if agent is None:
                self._log_event("task_skipped", {"task_id": task.id, "reason": "no_available_agent"})
                task.mark_failed("No available agent")
                with self._lock:
                    self._failed.append(task)
                results.append(task)
                continue

            fn = fn_map.get(agent.name) or fn_map.get(task.description)
            if fn is None:
                task.mark_failed("No function mapped")
                with self._lock:
                    self._failed.append(task)
                results.append(task)
                continue

            task.mark_assigned(agent.id)
            try:
                self._execute_task(task, agent, fn)
                with self._lock:
                    self._completed.append(task)
            except Exception:
                with self._lock:
                    self._failed.append(task)
            results.append(task)

        return results

    def get_status(self) -> dict:
        with self._lock:
            return {
                "orchestrator_id": self.id,
                "agents": {aid: a.to_dict() for aid, a in self.agents.items()},
                "pending_tasks": len(self._pending),
                "completed_tasks": len(self._completed),
                "failed_tasks": len(self._failed),
                "tasks": {
                    "pending": [t.to_dict() for t in self._pending],
                    "completed": [t.to_dict() for t in self._completed],
                    "failed": [t.to_dict() for t in self._failed],
                },
                "memory_keys": len(self.memory),
            }

    def set_recorder(self, recorder):
        self._recorder = recorder
        for agent in self.agents.values():
            agent.set_recorder(recorder)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._executor:
            self._executor.shutdown(wait=False)


def orchestrate(
    tasks: list[Task],
    agents: list[Agent],
    fn_map: dict[str, Callable] = None,
    max_workers: int = 4,
    recorder=None,
    parallel: bool = True,
) -> tuple[Orchestrator, list[Task]]:
    """
    Convenience function: register agents, submit tasks, run, return results.

    Usage:
        tasks = [Task("browse page", required_capabilities={"browser"})]
        agents = [Agent("browser_agent", {AgentCapability.browser})]
        orch, results = orchestrate(tasks, agents, fn_map={"browser_agent": my_fn})
    """
    orch = Orchestrator(max_workers=max_workers)
    if recorder:
        orch.set_recorder(recorder)

    for agent in agents:
        orch.register(agent)

    orch.submit_many(tasks)

    if parallel:
        results = orch.run_parallel(fn_map)
    else:
        results = orch.run_sequential(fn_map)

    return orch, results
