"""
Predictive Failure Prevention (Pre-cog Mode)
Real-time vector similarity analysis to block risky actions before execution.
"""
import time
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ActionContext:
    action_type: str
    parameters: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    context_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskAssessment:
    risk_level: RiskLevel
    confidence: float  # 0.0 to 1.0
    similarity_score: float  # 0.0 to 1.0 against known failure patterns
    blocking_reason: Optional[str] = None
    suggested_alternative: Optional[str] = None
    matched_patterns: List[str] = field(default_factory=list)


class PreCogMode:
    """
    Predictive Failure Prevention system using real-time vector similarity analysis.
    
    Features:
    - Embeds current action context into vector space
    - Compares against historical failure patterns
    - Blocks high-risk actions before execution
    - Provides alternative suggestions
    - Continuously learns from new failures
    """
    
    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold  # Similarity threshold for blocking
        self._failure_patterns: Dict[str, np.ndarray] = {}
        self._action_history: List[ActionContext] = []
        self._blocked_count = 0
        self._allowed_count = 0
    
    def register_failure_pattern(self, pattern_id: str, embedding: np.ndarray):
        """Register a known failure pattern embedding."""
        self._failure_patterns[pattern_id] = embedding
    
    def assess_action(self, action: ActionContext, embedding: np.ndarray) -> RiskAssessment:
        """
        Assess the risk level of an action using vector similarity.
        
        Args:
            action: The action context to assess
            embedding: Vector embedding of the action context
        
        Returns:
            RiskAssessment with risk level and recommendations
        """
        if not self._failure_patterns:
            self._allowed_count += 1
            return RiskAssessment(
                risk_level=RiskLevel.LOW,
                confidence=0.0,
                similarity_score=0.0
            )
        
        # Calculate similarity to all known failure patterns
        similarities = {}
        for pattern_id, pattern_emb in self._failure_patterns.items():
            sim = self._cosine_similarity(embedding, pattern_emb)
            similarities[pattern_id] = sim
        
        max_similarity = max(similarities.values()) if similarities else 0.0
        matched_patterns = [
            pid for pid, sim in similarities.items() 
            if sim > self.threshold * 0.8
        ]
        
        # Determine risk level based on similarity
        if max_similarity >= 0.9:
            risk_level = RiskLevel.CRITICAL
            blocking_reason = f"Critical similarity ({max_similarity:.3f}) to known failure patterns"
        elif max_similarity >= self.threshold:
            risk_level = RiskLevel.HIGH
            blocking_reason = f"High similarity ({max_similarity:.3f}) to known failure patterns"
        elif max_similarity >= self.threshold * 0.7:
            risk_level = RiskLevel.MEDIUM
            blocking_reason = None
        else:
            risk_level = RiskLevel.LOW
            blocking_reason = None
        
        # Track statistics
        if blocking_reason:
            self._blocked_count += 1
        else:
            self._allowed_count += 1
        
        return RiskAssessment(
            risk_level=risk_level,
            confidence=max_similarity,
            similarity_score=max_similarity,
            blocking_reason=blocking_reason,
            matched_patterns=matched_patterns,
            suggested_alternative=self._suggest_alternative(action, embedding) if blocking_reason else None
        )
    
    def should_block(self, assessment: RiskAssessment) -> bool:
        """Determine if an action should be blocked based on assessment."""
        return assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def _suggest_alternative(self, action: ActionContext, embedding: np.ndarray) -> Optional[str]:
        """Suggest a safer alternative action."""
        # Simple heuristic: suggest reducing parameter magnitudes
        suggestions = []
        for key, value in action.parameters.items():
            if isinstance(value, (int, float)) and value > 100:
                suggestions.append(f"Reduce {key} from {value} to {value // 2}")
        
        if suggestions:
            return "; ".join(suggestions)
        return "Consider breaking this action into smaller steps"
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get prevention system statistics."""
        total = self._blocked_count + self._allowed_count
        return {
            "total_actions": total,
            "blocked_actions": self._blocked_count,
            "allowed_actions": self._allowed_count,
            "block_rate": self._blocked_count / total if total > 0 else 0.0,
            "registered_patterns": len(self._failure_patterns)
        }
