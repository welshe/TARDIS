from .capture.recorder import Recorder, record
from .capture.llm_proxy import wrap
from .capture.anthropic_proxy import wrap_anthropic
from .capture.dom_snapshot import capture_dom, capture_accessibility, diff_snapshots
from .capture.win32_hooks import Win32HookManager, hook_keyboard_and_mouse
from .capture.async_recorder import AsyncRecorder, async_record
from .orchestration import Agent, AgentState, AgentCapability, Task, TaskStatus, TaskPriority, SharedMemory, Orchestrator, orchestrate
from .store.lancedb_store import FailurePatternStore
from .monitoring import AnomalyDetector, AnomalyEvent, AnomalyType, LiveMonitor, MonitorConfig
from .autopsy.plugins import register_check, CheckResult, run_all_checks, get_registered_checks
from .feedback import FeedbackLoop, FeedbackEntry

__all__ = [
    "Recorder", "record", "wrap", "wrap_anthropic",
    "capture_dom", "capture_accessibility", "diff_snapshots",
    "Win32HookManager", "hook_keyboard_and_mouse",
    "AsyncRecorder", "async_record",
    "Agent", "AgentState", "AgentCapability",
    "Task", "TaskStatus", "TaskPriority",
    "SharedMemory",
    "Orchestrator", "orchestrate",
    "FailurePatternStore",
    "AnomalyDetector", "AnomalyEvent", "AnomalyType",
    "LiveMonitor", "MonitorConfig",
    "register_check", "CheckResult", "run_all_checks", "get_registered_checks",
    "FeedbackLoop", "FeedbackEntry",
]
__version__ = "0.5.0"

# v0.6.0 Exports
from .predictive.preventer import PredictiveFailurePrevention, RiskLevel
from .repair.repair_engine import AutonomousRepairEngine
from .os_integration.kernel_tracer import KernelTracer
from .swarm.swarm_debugger import CollaborativeSwarmDebugger
from .production.shadow_mode import ProductionIntelligence, ShadowModeStatus
