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
from .prevention import PreCogMode, RiskLevel, ActionContext, RiskAssessment
from .repair import AutonomousRepair, ProblemReport, ProposedFix, SimulationResult, FixStatus
from .tracing import KernelTracer, TraceBackend, TraceEvent, TraceConfig
from .swarm import SwarmDebugger, AgentRole, DebugIssue, DebugReport, DebugStatus
from .production import ShadowMode, ShadowModeStatus, ProductionEvent, RegressionTest, RLHFPair
from .redteam import RedTeamAgent as RedTeamEngine, AttackType, AttackResult, AdversarialDefense as DefenseStrategy
from .routing import CostAwareRouter, ModelConfig as ModelRoute, RoutingDecision
from .replay.time_travel import TimeTravelReplay, SystemState as ReplayCheckpoint, KernelTracer as Breakpoint
from .compliance import ComplianceAuditor, ComplianceChecker as ComplianceCheck, ComplianceViolation as ComplianceReport, Regulation
from .memory import KnowledgeGraph, KnowledgeNode as GraphNode, KnowledgeEdge as GraphEdge, SharedMemory as SharedMemoryLayer

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
    # v0.6.0 features
    "PreCogMode", "RiskLevel", "ActionContext", "RiskAssessment",
    "AutonomousRepair", "ProblemReport", "ProposedFix", "SimulationResult", "FixStatus",
    "KernelTracer", "TraceBackend", "TraceEvent", "TraceConfig",
    "SwarmDebugger", "AgentRole", "DebugIssue", "DebugReport", "DebugStatus",
    "ShadowMode", "ShadowModeStatus", "ProductionEvent", "RegressionTest", "RLHFPair",
    # v0.7.0 features
    "RedTeamEngine", "AttackType", "AttackResult", "DefenseStrategy",
    "CostAwareRouter", "ModelRoute", "RoutingDecision",
    "TimeTravelReplay", "ReplayCheckpoint", "Breakpoint",
    "ComplianceAuditor", "ComplianceCheck", "ComplianceReport", "Regulation",
    "KnowledgeGraph", "GraphNode", "GraphEdge", "SharedMemoryLayer",
]
__version__ = "0.7.0"
