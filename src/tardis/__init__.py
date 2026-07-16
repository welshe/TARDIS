from .capture.recorder import Recorder, record
from .capture.llm_proxy import wrap
from .capture.anthropic_proxy import wrap_anthropic
from .capture.dom_snapshot import capture_dom, capture_accessibility, diff_snapshots
from .capture.win32_hooks import Win32HookManager, hook_keyboard_and_mouse
from .orchestration import Agent, AgentState, AgentCapability, Task, TaskStatus, TaskPriority, SharedMemory, Orchestrator, orchestrate
from .store.lancedb_store import FailurePatternStore

__all__ = [
    "Recorder", "record", "wrap", "wrap_anthropic",
    "capture_dom", "capture_accessibility", "diff_snapshots",
    "Win32HookManager", "hook_keyboard_and_mouse",
    "Agent", "AgentState", "AgentCapability",
    "Task", "TaskStatus", "TaskPriority",
    "SharedMemory",
    "Orchestrator", "orchestrate",
    "FailurePatternStore",
]
__version__ = "0.3.0"
