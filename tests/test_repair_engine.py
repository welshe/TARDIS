"""Tests for the autonomous repair engine."""

from tardis.repair.repair_engine import (
    _INJECTION_PATTERNS,
    AutonomousRepairEngine,
    RepairHypothesis,
)


class TestRepairHypothesis:
    def test_defaults(self):
        h = RepairHypothesis(strategy="test", description="desc", confidence=0.5)
        assert h.simulated_success is False
        assert h.simulation_result is None


class TestAutonomousRepairEngine:
    def test_init_without_llm(self):
        engine = AutonomousRepairEngine()
        assert not engine._has_llm

    def test_init_with_llm(self):
        engine = AutonomousRepairEngine(agent_executor=lambda x: "[]")
        assert engine._has_llm

    def test_generate_hypotheses_advisory_fallback(self):
        engine = AutonomousRepairEngine()
        hypotheses = engine.generate_hypotheses("timeout error", "trace_data")
        assert len(hypotheses) == 4
        assert all(h.confidence == 0.3 for h in hypotheses)
        assert all(h.strategy in engine.strategies for h in hypotheses)

    def test_generate_hypotheses_with_llm_success(self):
        import json

        def mock_llm(prompt):
            return json.dumps(
                [
                    {
                        "strategy": "parameter_adjustment",
                        "description": "Fix params",
                        "confidence": 0.8,
                    },
                    {
                        "strategy": "wait_insertion",
                        "description": "Add wait",
                        "confidence": 0.6,
                    },
                ]
            )

        engine = AutonomousRepairEngine(agent_executor=mock_llm)
        hypotheses = engine.generate_hypotheses("rate limit", "trace")
        assert len(hypotheses) == 2
        assert hypotheses[0].confidence == 0.8

    def test_generate_hypotheses_with_llm_injection_redaction(self):
        import json

        def mock_llm(prompt):
            return json.dumps(
                [
                    {
                        "strategy": "test",
                        "description": "os.system('evil')",
                        "confidence": 0.9,
                    },
                ]
            )

        engine = AutonomousRepairEngine(agent_executor=mock_llm)
        hypotheses = engine.generate_hypotheses("test", "trace")
        assert hypotheses[0].confidence == 0.0
        assert "redacted" in hypotheses[0].description.lower()

    def test_generate_hypotheses_llm_exception_falls_back(self):
        def bad_llm(prompt):
            raise RuntimeError("LLM unavailable")

        engine = AutonomousRepairEngine(agent_executor=bad_llm)
        hypotheses = engine.generate_hypotheses("error", "trace")
        assert len(hypotheses) == 4
        assert all(h.confidence == 0.3 for h in hypotheses)

    def test_simulate_fix_valid(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="parameter_adjustment",
            description="Adjust timeout parameter",
            confidence=0.8,
        )
        result = engine.simulate_fix(h, "timeout error in step 5")
        assert result is True
        assert h.simulated_success is True

    def test_simulate_fix_injection_blocked(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="test",
            description="os.system('rm -rf /')",
            confidence=0.5,
        )
        result = engine.simulate_fix(h, "trace")
        assert result is False

    def test_simulate_fix_unknown_strategy(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="unknown_strategy",
            description="Do something",
            confidence=0.5,
        )
        result = engine.simulate_fix(h, "trace")
        assert result is False

    def test_simulate_fix_empty_description(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="parameter_adjustment",
            description="   ",
            confidence=0.5,
        )
        result = engine.simulate_fix(h, "trace")
        assert result is False

    def test_apply_fix_blocked_without_confirm(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(strategy="test", description="fix", confidence=0.8)
        result = engine.apply_fix(h, confirm=False)
        assert result["status"] == "blocked"
        assert "confirm=True" in result["reason"]

    def test_apply_fix_rejects_injection(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="test",
            description="eval('malicious code')",
            confidence=0.9,
        )
        result = engine.apply_fix(h, confirm=True)
        assert result["status"] == "rejected"
        assert "injection" in result["reason"].lower()

    def test_apply_fix_rejects_low_confidence(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(strategy="test", description="weak fix", confidence=0.3)
        result = engine.apply_fix(h, confirm=True)
        assert result["status"] == "rejected"
        assert "confidence" in result["reason"].lower()

    def test_apply_fix_skipped_without_simulation(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(strategy="test", description="good fix", confidence=0.8)
        result = engine.apply_fix(h, confirm=True)
        assert result["status"] == "skipped"
        assert "not run" in result["reason"].lower()

    def test_apply_fix_success_with_simulation(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="parameter_adjustment",
            description="fix params",
            confidence=0.8,
            simulated_success=True,
        )
        result = engine.apply_fix(h, confirm=True)
        assert result["status"] == "applied"

    def test_apply_fix_failed_simulation(self):
        engine = AutonomousRepairEngine()
        h = RepairHypothesis(
            strategy="test",
            description="bad fix",
            confidence=0.8,
            simulated_success=False,
            simulation_result={"valid": False},
        )
        result = engine.apply_fix(h, confirm=True)
        assert result["status"] == "skipped"
        assert "did not pass" in result["reason"].lower()


class TestInjectionPatterns:
    def test_detects_eval(self):
        assert _INJECTION_PATTERNS.search("eval('code')")

    def test_detects_exec(self):
        assert _INJECTION_PATTERNS.search("exec(malicious)")

    def test_detects_os_system(self):
        assert _INJECTION_PATTERNS.search("os.system(cmd)")

    def test_detects_subprocess(self):
        assert _INJECTION_PATTERNS.search("subprocess.run(...)")

    def test_detects_import(self):
        assert _INJECTION_PATTERNS.search("__import__('os')")

    def test_clean_text_not_flagged(self):
        assert not _INJECTION_PATTERNS.search("Adjust timeout parameter to 30s")
