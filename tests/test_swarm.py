"""Tests for the collaborative swarm debugger."""

from tardis.swarm.swarm_debugger import (
    _INJECTION_RE,
    CollaborativeSwarmDebugger,
    SwarmAgentRole,
    SwarmReport,
)


class TestSwarmAgentRole:
    def test_dataclass(self):
        role = SwarmAgentRole(
            name="Analyst", specialty="causality", prompt_template="Analyze..."
        )
        assert role.name == "Analyst"
        assert role.specialty == "causality"


class TestSwarmReport:
    def test_dataclass(self):
        report = SwarmReport(
            root_cause="timeout",
            confidence=0.8,
            contributing_factors=["slow api"],
            recommended_fix="increase timeout",
        )
        assert report.root_cause == "timeout"
        assert report.confidence == 0.8


class TestCollaborativeSwarmDebugger:
    def test_init_no_llm(self):
        debugger = CollaborativeSwarmDebugger()
        assert debugger.llm is None
        assert len(debugger.roles) == 5

    def test_init_with_llm(self):
        debugger = CollaborativeSwarmDebugger(llm_client=lambda x: "test")
        assert debugger.llm is not None

    def test_diagnose_without_llm(self):
        debugger = CollaborativeSwarmDebugger()
        trace = "Error: timeout after 30s. Rate limit exceeded."
        report = debugger.diagnose(trace)
        assert isinstance(report, SwarmReport)
        assert report.confidence > 0
        assert len(report.contributing_factors) > 0

    def test_diagnose_with_callable_llm(self):
        def mock_llm(prompt):
            return "Root cause analysis: connection timeout"

        debugger = CollaborativeSwarmDebugger(llm_client=mock_llm)
        report = debugger.diagnose("error trace")
        assert isinstance(report, SwarmReport)

    def test_rule_based_analysis_causality(self):
        debugger = CollaborativeSwarmDebugger()
        role = SwarmAgentRole("Analyst", "causality", "template")
        result = debugger._rule_based_analysis(role, "trace with 2 errors")
        assert "error" in result.lower()

    def test_rule_based_analysis_history(self):
        debugger = CollaborativeSwarmDebugger()
        role = SwarmAgentRole("Matcher", "history", "template")
        result = debugger._rule_based_analysis(role, "trace")
        assert "LanceDB" in result

    def test_rule_based_analysis_repair_timeout(self):
        debugger = CollaborativeSwarmDebugger()
        role = SwarmAgentRole("Fixer", "repair", "template")
        result = debugger._rule_based_analysis(role, "timeout error occurred")
        assert "timeout" in result.lower() or "increase" in result.lower()

    def test_rule_based_analysis_repair_element(self):
        debugger = CollaborativeSwarmDebugger()
        role = SwarmAgentRole("Fixer", "repair", "template")
        result = debugger._rule_based_analysis(role, "element not found error")
        assert "re-location" in result.lower() or "retry" in result.lower()

    def test_rule_based_analysis_repair_rate_limit(self):
        debugger = CollaborativeSwarmDebugger()
        role = SwarmAgentRole("Fixer", "repair", "template")
        result = debugger._rule_based_analysis(role, "rate limit exceeded")
        assert "backoff" in result.lower()

    def test_synthesize_report(self):
        debugger = CollaborativeSwarmDebugger()
        results = {
            "Root Cause Analyst": "Error found: timeout in API call",
            "Fix Generator": "timeout fix: increase timeout value",
            "Coordinator": "all analyses complete",
        }
        report = debugger._synthesize_report(results)
        assert "timeout" in report.root_cause.lower()

    def test_synthesize_report_with_fix(self):
        debugger = CollaborativeSwarmDebugger()
        results = {
            "Fix Generator": "Fix: add retry logic with exponential backoff",
        }
        report = debugger._synthesize_report(results)
        assert "retry" in report.recommended_fix.lower()

    def test_confidence_calculation(self):
        debugger = CollaborativeSwarmDebugger()
        results = {
            "Analyst 1": "error found",
            "Analyst 2": "timeout detected",
            "Analyst 3": "failure in connection",
        }
        report = debugger._synthesize_report(results)
        assert 0.3 <= report.confidence <= 0.95


class TestInjectionRegex:
    def test_detects_os_system(self):
        assert _INJECTION_RE.search("os.system('cmd')")

    def test_detects_subprocess(self):
        assert _INJECTION_RE.search("subprocess.run(...)")

    def test_detects_eval(self):
        assert _INJECTION_RE.search("eval('code')")

    def test_detects_exec(self):
        assert _INJECTION_RE.search("exec(malicious)")

    def test_clean_text(self):
        assert not _INJECTION_RE.search("Increase timeout to 30 seconds")
