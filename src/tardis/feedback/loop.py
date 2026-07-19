"""Feedback loop system for TARDIS.

Enables automatic learning from failures by generating training data,
suggested fixes, and integrating with fine-tuning pipelines.
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path


@dataclass
class FeedbackEntry:
    """A single feedback entry for learning."""
    trace_id: str
    failure_type: str
    step_index: int
    original_prompt: str
    original_response: str
    suggested_fix: str
    corrected_prompt: Optional[str] = None
    corrected_response: Optional[str] = None
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_training_pair(self) -> dict:
        """Convert to a contrastive training pair format."""
        return {
            "trace_id": self.trace_id,
            "failure_type": self.failure_type,
            "input": {
                "original_prompt": self.original_prompt,
                "context": self.metadata.get("context", ""),
            },
            "output": {
                "original_response": self.original_response,
                "corrected_response": self.corrected_response or self.suggested_fix,
            },
            "metadata": {
                "step_index": self.step_index,
                "confidence": self.confidence,
                "evidence": self.evidence,
                "created_at": self.created_at.isoformat(),
            }
        }
    
    def to_negative_pair(self) -> dict:
        """Convert to RLHF negative pair format."""
        return {
            "prompt": self.original_prompt,
            "chosen": self.corrected_response or self.suggested_fix,
            "rejected": self.original_response,
            "metadata": {
                "failure_type": self.failure_type,
                "trace_id": self.trace_id,
            }
        }


class FeedbackLoop:
    """Manages feedback collection and export for model improvement."""
    
    def __init__(self, storage_dir: str = ".tardis/feedback"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: List[FeedbackEntry] = []
        self._index: Dict[str, List[FeedbackEntry]] = {}
    
    def add_entry(self, entry: FeedbackEntry):
        """Add a feedback entry."""
        self._entries.append(entry)
        if entry.trace_id not in self._index:
            self._index[entry.trace_id] = []
        self._index[entry.trace_id].append(entry)
        self._save_entry(entry)
    
    def add_from_autopsy(self, trace_id: str, autopsy_result: dict, trace_steps: List[Any]):
        """Create feedback entries from an autopsy result."""
        failure_type = autopsy_result.get("failure_type", "unknown")
        fix_suggestion = autopsy_result.get("fix_suggestion", "")
        evidence = autopsy_result.get("evidence", [])
        confidence = autopsy_result.get("confidence", 0.0)
        
        failing_step_idx = len(trace_steps) - 1
        original_prompt = ""
        original_response = ""
        
        for i, step in enumerate(trace_steps):
            if hasattr(step, 'step_type'):
                if step.step_type.value == "llm_call":
                    original_prompt = getattr(step, 'prompt', '')
                    original_response = getattr(step, 'completion', '')
                    failing_step_idx = i
        
        entry = FeedbackEntry(
            trace_id=trace_id,
            failure_type=failure_type,
            step_index=failing_step_idx,
            original_prompt=original_prompt,
            original_response=original_response,
            suggested_fix=fix_suggestion,
            confidence=confidence,
            evidence=evidence,
            metadata={"autopsy_summary": autopsy_result.get("summary", ""), "total_steps": len(trace_steps)}
        )
        
        self.add_entry(entry)
        return entry
    
    def _save_entry(self, entry: FeedbackEntry):
        """Save a single entry to disk."""
        filename = f"{entry.trace_id}_{entry.step_index}.json"
        filepath = self.storage_dir / filename
        with open(filepath, 'w') as f:
            json.dump({
                "trace_id": entry.trace_id,
                "failure_type": entry.failure_type,
                "step_index": entry.step_index,
                "original_prompt": entry.original_prompt,
                "original_response": entry.original_response,
                "suggested_fix": entry.suggested_fix,
                "corrected_prompt": entry.corrected_prompt,
                "corrected_response": entry.corrected_response,
                "confidence": entry.confidence,
                "evidence": entry.evidence,
                "metadata": entry.metadata,
                "created_at": entry.created_at.isoformat(),
            }, f, indent=2)
    
    def get_entries_for_trace(self, trace_id: str) -> List[FeedbackEntry]:
        """Get all feedback entries for a specific trace."""
        return self._index.get(trace_id, [])
    
    def export_training_data(self, output_path: str, format: str = "jsonl") -> str:
        """Export all feedback as training data."""
        output_file = Path(output_path)
        
        if format == "jsonl":
            with open(output_file, 'w') as f:
                for entry in self._entries:
                    f.write(json.dumps(entry.to_training_pair()) + '\n')
        elif format == "json":
            data = [entry.to_training_pair() for entry in self._entries]
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2)
        elif format == "negative-pair":
            with open(output_file, 'w') as f:
                for entry in self._entries:
                    if entry.corrected_response or entry.suggested_fix:
                        f.write(json.dumps(entry.to_negative_pair()) + '\n')
        else:
            raise ValueError(f"Unknown format: {format}")
        
        return str(output_file)
    
    def export_fine_tuning_dataset(self, output_path: str, model_format: str = "openai") -> str:
        """Export feedback as a fine-tuning dataset."""
        output_file = Path(output_path)
        
        if model_format == "openai":
            examples = []
            for entry in self._entries:
                if entry.corrected_response or entry.suggested_fix:
                    examples.append({
                        "messages": [
                            {"role": "system", "content": f"You are a helpful assistant. Avoid {entry.failure_type} errors."},
                            {"role": "user", "content": entry.original_prompt},
                            {"role": "assistant", "content": entry.corrected_response or entry.suggested_fix},
                        ]
                    })
            with open(output_file, 'w') as f:
                for ex in examples:
                    f.write(json.dumps(ex) + '\n')
        elif model_format == "anthropic":
            examples = []
            for entry in self._entries:
                if entry.corrected_response or entry.suggested_fix:
                    examples.append({
                        "system": f"Avoid {entry.failure_type} errors.",
                        "messages": [
                            {"role": "user", "content": entry.original_prompt},
                            {"role": "assistant", "content": entry.corrected_response or entry.suggested_fix},
                        ]
                    })
            with open(output_file, 'w') as f:
                json.dump(examples, f, indent=2)
        elif model_format == "raw":
            data = []
            for entry in self._entries:
                data.append({
                    "prompt": entry.original_prompt,
                    "completion": entry.corrected_response or entry.suggested_fix,
                    "metadata": {"failure_type": entry.failure_type, "original_response": entry.original_response}
                })
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2)
        else:
            raise ValueError(f"Unknown model format: {model_format}")
        
        return str(output_file)
    
    def get_statistics(self) -> dict:
        """Get statistics about collected feedback."""
        by_type: Dict[str, int] = {}
        total_confidence = 0.0
        for entry in self._entries:
            by_type[entry.failure_type] = by_type.get(entry.failure_type, 0) + 1
            total_confidence += entry.confidence
        avg_confidence = total_confidence / len(self._entries) if self._entries else 0.0
        return {
            "total_entries": len(self._entries),
            "by_failure_type": by_type,
            "average_confidence": avg_confidence,
            "traces_with_feedback": len(self._index),
        }
    
    def clear(self):
        """Clear all feedback entries."""
        self._entries.clear()
        self._index.clear()
        for f in self.storage_dir.glob("*.json"):
            f.unlink()
