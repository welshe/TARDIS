"""
Cost-Aware Dynamic Model Routing

Intelligent routing that sends simple queries to cheap models and complex 
tasks to expensive ones in real-time, potentially cutting inference costs 
by 40-60% without sacrificing quality.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class ModelTier(str, Enum):
    """Model cost/performance tiers."""
    CHEAP = "cheap"      # e.g., GPT-3.5-turbo, Claude Haiku
    MID = "mid"          # e.g., GPT-4-turbo, Claude Sonnet
    EXPENSIVE = "expensive"  # e.g., GPT-4o, Claude Opus
    SPECIALIZED = "specialized"  # Domain-specific models


@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str
    tier: ModelTier
    cost_per_1k_tokens: float
    max_context: int
    capabilities: List[str]
    latency_ms: float = 100.0
    
    def __post_init__(self):
        if isinstance(self.tier, str):
            self.tier = ModelTier(self.tier)


@dataclass
class RoutingDecision:
    """Record of a routing decision."""
    query_id: str
    original_query: str
    complexity_score: float
    selected_model: str
    tier: ModelTier
    estimated_cost: float
    estimated_latency_ms: float
    timestamp: float = field(default_factory=time.time)
    actual_cost: Optional[float] = None
    actual_latency_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "complexity_score": self.complexity_score,
            "selected_model": self.selected_model,
            "tier": self.tier.value,
            "estimated_cost": self.estimated_cost,
            "estimated_latency_ms": self.estimated_latency_ms,
            "actual_cost": self.actual_cost,
            "actual_latency_ms": self.actual_latency_ms,
            "timestamp": self.timestamp,
        }


class ComplexityAnalyzer:
    """Analyzes query complexity to determine appropriate model tier."""
    
    def __init__(self):
        self.complexity_indicators = {
            "reasoning_keywords": [
                "analyze", "compare", "evaluate", "synthesize", "derive",
                "prove", "optimize", "design", "architect", "strategize"
            ],
            "code_keywords": [
                "implement", "debug", "refactor", "optimize", "algorithm",
                "complexity", "data structure", "design pattern"
            ],
            "creative_keywords": [
                "write", "compose", "generate", "create", "imagine",
                "story", "poem", "script", "narrative"
            ],
            "technical_keywords": [
                "explain", "how does", "what is", "define", "describe",
                "tutorial", "guide", "documentation"
            ],
        }
        
        self.length_thresholds = {
            "very_short": 50,
            "short": 200,
            "medium": 500,
            "long": 1000,
        }
    
    def analyze(self, query: str) -> Tuple[float, Dict[str, Any]]:
        """
        Analyze query complexity. Returns score (0-1) and breakdown.
        
        Score interpretation:
        - 0.0-0.3: Simple queries (use cheap models)
        - 0.3-0.6: Moderate complexity (use mid-tier models)
        - 0.6-0.8: Complex queries (use expensive models)
        - 0.8-1.0: Very complex/specialized (use top-tier or specialized)
        """
        query_lower = query.lower()
        breakdown = {
            "length_score": 0.0,
            "keyword_score": 0.0,
            "structure_score": 0.0,
            "indicators_found": [],
        }
        
        # Length-based scoring
        length = len(query)
        if length < self.length_thresholds["very_short"]:
            breakdown["length_score"] = 0.1
        elif length < self.length_thresholds["short"]:
            breakdown["length_score"] = 0.3
        elif length < self.length_thresholds["medium"]:
            breakdown["length_score"] = 0.5
        elif length < self.length_thresholds["long"]:
            breakdown["length_score"] = 0.7
        else:
            breakdown["length_score"] = 0.9
        
        # Keyword-based scoring
        keyword_matches = 0
        total_keywords = 0
        
        for category, keywords in self.complexity_indicators.items():
            total_keywords += len(keywords)
            for keyword in keywords:
                if keyword in query_lower:
                    keyword_matches += 1
                    breakdown["indicators_found"].append(keyword)
        
        breakdown["keyword_score"] = min(1.0, keyword_matches / max(1, total_keywords) * 10)
        
        # Structure-based scoring (questions, multiple parts, etc.)
        structure_score = 0.0
        if "?" in query:
            structure_score += 0.2
        if query.count("\n") > 2:
            structure_score += 0.3
        if any(x in query for x in ["first,", "second,", "third,", "step 1", "step 2"]):
            structure_score += 0.3
        if "example" in query_lower or "sample" in query_lower:
            structure_score += 0.2
        
        breakdown["structure_score"] = min(1.0, structure_score)
        
        # Weighted final score
        final_score = (
            breakdown["length_score"] * 0.2 +
            breakdown["keyword_score"] * 0.5 +
            breakdown["structure_score"] * 0.3
        )
        
        return min(1.0, final_score), breakdown


class CostAwareRouter:
    """Routes queries to appropriate models based on complexity and cost."""
    
    def __init__(self, budget_limit: float = 100.0):
        self.models: Dict[str, ModelConfig] = {}
        self.routing_history: List[RoutingDecision] = []
        self.budget_limit = budget_limit
        self.current_spend = 0.0
        self.complexity_analyzer = ComplexityAnalyzer()
        self.model_clients: Dict[str, Callable] = {}
        
        # Register default models
        self._register_default_models()
    
    def _register_default_models(self):
        """Register default model configurations."""
        defaults = [
            ModelConfig(
                name="gpt-3.5-turbo",
                tier=ModelTier.CHEAP,
                cost_per_1k_tokens=0.0015,
                max_context=16385,
                capabilities=["chat", "simple_qa", "summarization"],
                latency_ms=50.0,
            ),
            ModelConfig(
                name="claude-3-haiku",
                tier=ModelTier.CHEAP,
                cost_per_1k_tokens=0.00025,
                max_context=200000,
                capabilities=["chat", "vision", "simple_qa"],
                latency_ms=40.0,
            ),
            ModelConfig(
                name="gpt-4-turbo",
                tier=ModelTier.MID,
                cost_per_1k_tokens=0.01,
                max_context=128000,
                capabilities=["chat", "reasoning", "code", "vision"],
                latency_ms=150.0,
            ),
            ModelConfig(
                name="claude-3-sonnet",
                tier=ModelTier.MID,
                cost_per_1k_tokens=0.003,
                max_context=200000,
                capabilities=["chat", "reasoning", "code", "vision"],
                latency_ms=120.0,
            ),
            ModelConfig(
                name="gpt-4o",
                tier=ModelTier.EXPENSIVE,
                cost_per_1k_tokens=0.05,
                max_context=128000,
                capabilities=["chat", "advanced_reasoning", "code", "vision", "multimodal"],
                latency_ms=200.0,
            ),
            ModelConfig(
                name="claude-3-opus",
                tier=ModelTier.EXPENSIVE,
                cost_per_1k_tokens=0.015,
                max_context=200000,
                capabilities=["chat", "advanced_reasoning", "code", "vision"],
                latency_ms=180.0,
            ),
        ]
        
        for model in defaults:
            self.register_model(model)
    
    def register_model(self, config: ModelConfig, client: Optional[Callable] = None):
        """Register a model configuration and optional client."""
        self.models[config.name] = config
        if client:
            self.model_clients[config.name] = client
    
    def select_model(self, query: str, required_capabilities: Optional[List[str]] = None) -> RoutingDecision:
        """Select the best model for a given query."""
        query_id = f"q_{int(time.time() * 1000)}"
        
        # Analyze complexity
        complexity_score, breakdown = self.complexity_analyzer.analyze(query)
        
        # Determine target tier based on complexity
        if complexity_score < 0.3:
            target_tier = ModelTier.CHEAP
        elif complexity_score < 0.6:
            target_tier = ModelTier.MID
        elif complexity_score < 0.8:
            target_tier = ModelTier.EXPENSIVE
        else:
            target_tier = ModelTier.EXPENSIVE
        
        # Filter models by capabilities if specified
        candidate_models = []
        for name, config in self.models.items():
            if required_capabilities:
                if all(cap in config.capabilities for cap in required_capabilities):
                    candidate_models.append(config)
            else:
                candidate_models.append(config)
        
        # Filter by tier preference (allow one tier up for safety margin)
        tier_order = [ModelTier.CHEAP, ModelTier.MID, ModelTier.EXPENSIVE, ModelTier.SPECIALIZED]
        target_idx = tier_order.index(target_tier)
        allowed_tiers = tier_order[target_idx:min(target_idx + 2, len(tier_order))]
        
        tier_filtered = [m for m in candidate_models if m.tier in allowed_tiers]
        
        if not tier_filtered:
            tier_filtered = candidate_models
        
        # Select cheapest model in allowed tiers
        selected = min(tier_filtered, key=lambda m: m.cost_per_1k_tokens)
        
        # Estimate cost (assume ~500 tokens for average query)
        estimated_tokens = max(100, len(query) // 4)
        estimated_cost = (estimated_tokens / 1000) * selected.cost_per_1k_tokens
        
        decision = RoutingDecision(
            query_id=query_id,
            original_query=query[:200],  # Truncate for logging
            complexity_score=complexity_score,
            selected_model=selected.name,
            tier=selected.tier,
            estimated_cost=estimated_cost,
            estimated_latency_ms=selected.latency_ms,
        )
        
        self.routing_history.append(decision)
        return decision
    
    async def route_and_execute(
        self,
        query: str,
        required_capabilities: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Route query to best model and execute."""
        decision = self.select_model(query, required_capabilities)
        
        # Check budget
        if self.current_spend + decision.estimated_cost > self.budget_limit:
            return {
                "error": "budget_exceeded",
                "message": f"Query would exceed budget. Current: ${self.current_spend:.4f}, Limit: ${self.budget_limit:.2f}",
                "decision": decision.to_dict(),
            }
        
        # Execute with selected model
        start_time = time.time()
        try:
            if decision.selected_model in self.model_clients:
                client = self.model_clients[decision.selected_model]
                if asyncio.iscoroutinefunction(client):
                    response = await client(query)
                else:
                    response = client(query)
                
                # Calculate actual cost from response tokens
                actual_tokens = getattr(response, "usage", {}).get("total_tokens", 500)
                model_config = self.models[decision.selected_model]
                actual_cost = (actual_tokens / 1000) * model_config.cost_per_1k_tokens
                
                decision.actual_cost = actual_cost
                decision.actual_latency_ms = (time.time() - start_time) * 1000
                self.current_spend += actual_cost
                
                return {
                    "response": response,
                    "decision": decision.to_dict(),
                    "cost": actual_cost,
                    "tokens": actual_tokens,
                }
            else:
                # Simulated response for testing
                await asyncio.sleep(decision.estimated_latency_ms / 1000)
                decision.actual_cost = decision.estimated_cost
                decision.actual_latency_ms = (time.time() - start_time) * 1000
                self.current_spend += decision.estimated_cost
                
                return {
                    "response": f"[Simulated response from {decision.selected_model}]",
                    "decision": decision.to_dict(),
                    "cost": decision.estimated_cost,
                    "note": "No client registered - simulated response",
                }
                
        except Exception as e:
            return {
                "error": str(e),
                "decision": decision.to_dict(),
            }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get routing statistics and cost analysis."""
        if not self.routing_history:
            return {"status": "no_routing_decisions"}
        
        by_tier = {}
        total_estimated = 0.0
        total_actual = 0.0
        
        for decision in self.routing_history:
            tier_name = decision.tier.value
            by_tier[tier_name] = by_tier.get(tier_name, 0) + 1
            
            total_estimated += decision.estimated_cost
            if decision.actual_cost:
                total_actual += decision.actual_cost
        
        avg_complexity = sum(d.complexity_score for d in self.routing_history) / len(self.routing_history)
        
        return {
            "total_queries": len(self.routing_history),
            "by_tier": by_tier,
            "total_estimated_cost": total_estimated,
            "total_actual_cost": total_actual,
            "current_spend": self.current_spend,
            "budget_limit": self.budget_limit,
            "budget_remaining": self.budget_limit - self.current_spend,
            "average_complexity_score": avg_complexity,
            "potential_savings": self._calculate_potential_savings(),
        }
    
    def _calculate_potential_savings(self) -> Dict[str, Any]:
        """Calculate potential savings vs always using expensive models."""
        expensive_model = next(
            (m for m in self.models.values() if m.tier == ModelTier.EXPENSIVE),
            None
        )
        
        if not expensive_model:
            return {"note": "No expensive model configured for comparison"}
        
        always_expensive_cost = sum(
            (len(d.original_query) // 4 / 1000) * expensive_model.cost_per_1k_tokens
            for d in self.routing_history
        )
        
        actual_cost = sum(d.actual_cost or d.estimated_cost for d in self.routing_history)
        savings = always_expensive_cost - actual_cost
        savings_pct = (savings / always_expensive_cost * 100) if always_expensive_cost > 0 else 0
        
        return {
            "always_expensive_cost": always_expensive_cost,
            "actual_cost": actual_cost,
            "savings_usd": savings,
            "savings_percentage": savings_pct,
        }


# Convenience function
def create_router(budget_limit: float = 100.0) -> CostAwareRouter:
    """Create a cost-aware router with default configuration."""
    return CostAwareRouter(budget_limit=budget_limit)
