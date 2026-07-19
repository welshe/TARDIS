"""Plugin system for TARDIS autopsy failure checks.

Allows users to register custom failure detection plugins that integrate
seamlessly with the built-in classifier.
"""

import inspect
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
import threading


@dataclass
class CheckResult:
    """Result from a failure check plugin."""
    check_name: str
    matched: bool
    confidence: float  # 0.0 to 1.0
    evidence: List[str]
    fix_suggestion: str = ""
    priority: int = 5  # 1=highest, 10=lowest


# Global plugin registry
_registry: Dict[str, Callable] = {}
_lock = threading.Lock()


def register_check(name: str, priority: int = 5):
    """Decorator to register a custom failure check plugin.
    
    Args:
        name: Unique name for the check
        priority: 1=highest priority, 10=lowest (default 5)
    
    Example:
        @register_check("my_custom_failure", priority=3)
        def check_my_failure(trace, steps):
            if ...:
                return CheckResult(
                    check_name="my_custom_failure",
                    matched=True,
                    confidence=0.8,
                    evidence=["error message X found"],
                    fix_suggestion="Do Y to fix"
                )
            return CheckResult("my_custom_failure", False, 0.0, [])
    """
    def decorator(func: Callable) -> Callable:
        with _lock:
            _registry[name] = {
                "func": func,
                "priority": priority,
            }
        return func
    return decorator


def unregister_check(name: str):
    """Unregister a failure check plugin."""
    with _lock:
        _registry.pop(name, None)


def get_registered_checks() -> Dict[str, dict]:
    """Get all registered checks with their metadata."""
    with _lock:
        return dict(_registry)


def run_all_checks(trace, steps: List[Any]) -> List[CheckResult]:
    """Run all registered checks and return results sorted by priority.
    
    Args:
        trace: The trace being analyzed
        steps: List of steps in the trace
    
    Returns:
        List of CheckResult objects sorted by priority (lowest number first)
    """
    results = []
    
    with _lock:
        checks = dict(_registry)
    
    for name, metadata in checks.items():
        try:
            func = metadata["func"]
            sig = inspect.signature(func)
            
            # Support both old and new signature styles
            if len(sig.parameters) == 2:
                result = func(trace, steps)
            else:
                result = func(trace)
            
            if isinstance(result, CheckResult):
                results.append(result)
        except Exception as e:
            # Never let a plugin crash the classifier
            results.append(CheckResult(
                check_name=name,
                matched=False,
                confidence=0.0,
                evidence=[f"Plugin error: {str(e)}"],
                priority=10,
            ))
    
    # Sort by priority (lower number = higher priority)
    results.sort(key=lambda r: r.priority)
    return results


def clear_registry():
    """Clear all registered plugins (useful for testing)."""
    with _lock:
        _registry.clear()
