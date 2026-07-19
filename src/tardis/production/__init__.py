"""
Continuous Production Intelligence Module
Shadow mode, automated regression testing, RLHF negative pairs.
"""
import asyncio
import time
import hashlib
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import threading
import json


class ShadowModeStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPARING = "comparing"
    ANALYZING = "analyzing"


@dataclass
class ProductionEvent:
    event_id: str
    timestamp: float
    input_data: Dict[str, Any]
    model_output: Any
    actual_outcome: Optional[Any] = None
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegressionTest:
    test_id: str
    name: str
    input_snapshot: Dict[str, Any]
    expected_output: Any
    current_output: Optional[Any] = None
    passed: bool = True
    last_run: Optional[float] = None


@dataclass
class RLHFPair:
    pair_id: str
    prompt: str
    chosen_response: str
    rejected_response: str
    confidence_delta: float
    source_event_id: str
    created_at: float = field(default_factory=time.time)


class ShadowMode:
    """
    Shadow mode for continuous production intelligence.
    
    Features:
    - Run new models alongside production without affecting users
    - Compare outputs between models
    - Collect RLHF negative pairs automatically
    - Automated regression detection
    - Zero-impact deployment testing
    """
    
    def __init__(self, comparison_threshold: float = 0.95):
        self.comparison_threshold = comparison_threshold
        self._status = ShadowModeStatus.PAUSED
        self._events: List[ProductionEvent] = []
        self._regression_tests: Dict[str, RegressionTest] = {}
        self._rlhf_pairs: List[RLHFPair] = []
        self._primary_model: Optional[Callable] = None
        self._shadow_model: Optional[Callable] = None
        self._lock = threading.Lock()
        self._comparison_results: Dict[str, Dict] = {}
    
    def set_primary_model(self, model: Callable):
        """Set the primary production model."""
        self._primary_model = model
    
    def set_shadow_model(self, model: Callable):
        """Set the shadow model for comparison."""
        self._shadow_model = model
    
    def start(self):
        """Start shadow mode."""
        self._status = ShadowModeStatus.ACTIVE
    
    def stop(self):
        """Stop shadow mode."""
        self._status = ShadowModeStatus.PAUSED
    
    async def process_request(self, input_data: Dict[str, Any]) -> Tuple[Any, Optional[Any]]:
        """
        Process a request through both primary and shadow models.
        
        Args:
            input_data: The input to process
        
        Returns:
            Tuple of (primary_output, shadow_output)
        """
        if self._status != ShadowModeStatus.ACTIVE:
            if self._primary_model:
                return await self._safe_call(self._primary_model, input_data), None
            return None, None
        
        event_id = hashlib.md5(
            f"{time.time()}_{json.dumps(input_data, sort_keys=True)}".encode()
        ).hexdigest()[:16]
        
        # Run primary model
        primary_start = time.perf_counter()
        primary_output = await self._safe_call(self._primary_model, input_data)
        primary_latency = (time.perf_counter() - primary_start) * 1000
        
        # Run shadow model in parallel
        shadow_output = None
        if self._shadow_model:
            shadow_output = await self._safe_call(self._shadow_model, input_data)
            
            # Compare outputs
            similarity = self._compare_outputs(primary_output, shadow_output)
            
            with self._lock:
                self._comparison_results[event_id] = {
                    "similarity": similarity,
                    "divergence_detected": similarity < self.comparison_threshold
                }
                
                # Generate RLHF pair if there's significant divergence
                if similarity < self.comparison_threshold:
                    self._generate_rlhf_pair(
                        event_id=event_id,
                        prompt=json.dumps(input_data),
                        response_a=str(primary_output),
                        response_b=str(shadow_output),
                        confidence_delta=1.0 - similarity
                    )
        
        # Record event
        event = ProductionEvent(
            event_id=event_id,
            timestamp=time.time(),
            input_data=input_data,
            model_output=primary_output,
            actual_outcome=shadow_output,
            latency_ms=primary_latency
        )
        
        with self._lock:
            self._events.append(event)
            # Limit buffer
            if len(self._events) > 10000:
                self._events = self._events[-5000:]
        
        return primary_output, shadow_output
    
    async def _safe_call(self, model: Callable, input_data: Dict) -> Any:
        """Safely call a model with error handling."""
        try:
            if asyncio.iscoroutinefunction(model):
                return await model(input_data)
            else:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, lambda: model(input_data))
        except Exception as e:
            return {"error": str(e)}
    
    def _compare_outputs(self, output_a: Any, output_b: Any) -> float:
        """Compare two outputs and return similarity score."""
        if output_a == output_b:
            return 1.0
        
        str_a, str_b = str(output_a), str(output_b)
        
        # Simple string similarity (in production would use embeddings)
        common_tokens = set(str_a.split()) & set(str_b.split())
        total_tokens = set(str_a.split()) | set(str_b.split())
        
        if not total_tokens:
            return 0.0
        
        return len(common_tokens) / len(total_tokens)
    
    def _generate_rlhf_pair(self, event_id: str, prompt: str, 
                           response_a: str, response_b: str, 
                           confidence_delta: float):
        """Generate an RLHF negative pair from divergent outputs."""
        pair = RLHFPair(
            pair_id=f"rlhf_{event_id}",
            prompt=prompt,
            chosen_response=response_a,  # Primary is assumed better
            rejected_response=response_b,
            confidence_delta=confidence_delta,
            source_event_id=event_id
        )
        
        with self._lock:
            self._rlhf_pairs.append(pair)
            # Limit stored pairs
            if len(self._rlhf_pairs) > 1000:
                self._rlhf_pairs = self._rlhf_pairs[-500:]
    
    def register_regression_test(self, test: RegressionTest):
        """Register a regression test."""
        with self._lock:
            self._regression_tests[test.test_id] = test
    
    async def run_regression_tests(self) -> Dict[str, bool]:
        """Run all registered regression tests."""
        results = {}
        
        for test_id, test in self._regression_tests.items():
            if self._primary_model:
                output = await self._safe_call(self._primary_model, test.input_snapshot)
                test.current_output = output
                test.passed = output == test.expected_output
                test.last_run = time.time()
                results[test_id] = test.passed
        
        return results
    
    def get_rlhf_pairs(self, limit: int = 100) -> List[RLHFPair]:
        """Get collected RLHF negative pairs."""
        with self._lock:
            return self._rlhf_pairs[-limit:]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get shadow mode statistics."""
        with self._lock:
            event_count = len(self._events)
            divergence_count = sum(
                1 for r in self._comparison_results.values() 
                if r.get("divergence_detected", False)
            )
            
            return {
                "status": self._status.value,
                "total_events": event_count,
                "divergence_count": divergence_count,
                "divergence_rate": divergence_count / event_count if event_count > 0 else 0.0,
                "rlhf_pairs_collected": len(self._rlhf_pairs),
                "regression_tests": len(self._regression_tests)
            }
