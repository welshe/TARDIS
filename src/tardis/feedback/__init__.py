"""Feedback loop system for TARDIS.

Enables automatic learning from failures by generating training data,
suggested fixes, and integrating with fine-tuning pipelines.
"""

from .loop import FeedbackEntry, FeedbackLoop

__all__ = ["FeedbackLoop", "FeedbackEntry"]
