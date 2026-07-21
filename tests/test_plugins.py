"""Tests for the autopsy plugin system."""

import pytest

from tardis.autopsy.plugins import (
    CheckResult,
    clear_registry,
    get_registered_checks,
    register_check,
    run_all_checks,
    unregister_check,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear plugin registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


class TestCheckResult:
    def test_defaults(self):
        result = CheckResult(
            check_name="test", matched=True, confidence=0.8, evidence=["e1"]
        )
        assert result.priority == 5
        assert result.fix_suggestion == ""


class TestRegisterCheck:
    def test_register_and_get(self):
        @register_check("my_check", priority=3)
        def check(trace, steps):
            return CheckResult("my_check", True, 0.9, [])

        checks = get_registered_checks()
        assert "my_check" in checks
        assert checks["my_check"]["priority"] == 3

    def test_unregister(self):
        @register_check("to_remove")
        def check(trace, steps):
            return CheckResult("to_remove", False, 0.0, [])

        unregister_check("to_remove")
        assert "to_remove" not in get_registered_checks()

    def test_unregister_nonexistent(self):
        unregister_check("does_not_exist")  # Should not raise


class TestRunAllChecks:
    def test_run_checks_sorted_by_priority(self):
        @register_check("low_priority", priority=8)
        def low(trace, steps):
            return CheckResult("low_priority", True, 0.5, ["low"], priority=8)

        @register_check("high_priority", priority=2)
        def high(trace, steps):
            return CheckResult("high_priority", True, 0.9, ["high"], priority=2)

        results = run_all_checks("trace", [])
        assert len(results) == 2
        assert results[0].check_name == "high_priority"
        assert results[1].check_name == "low_priority"

    def test_run_checks_with_error(self):
        @register_check("broken_check")
        def broken(trace, steps):
            raise RuntimeError("plugin crashed")

        results = run_all_checks("trace", [])
        assert len(results) == 1
        assert results[0].matched is False
        assert "error" in results[0].evidence[0].lower()

    def test_run_checks_single_arg(self):
        @register_check("single_arg")
        def single(trace):
            return CheckResult("single", True, 0.7, ["single arg works"])

        results = run_all_checks("trace", [])
        assert len(results) == 1
        assert results[0].matched is True

    def test_run_checks_returns_check_result(self):
        @register_check("non_check_result")
        def bad(trace, steps):
            return "not a CheckResult"

        results = run_all_checks("trace", [])
        assert len(results) == 0  # Non-CheckResult ignored

    def test_empty_registry(self):
        results = run_all_checks("trace", [])
        assert results == []
