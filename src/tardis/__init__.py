from .capture.recorder import Recorder, record
from .capture.llm_proxy import wrap
from .capture.anthropic_proxy import wrap_anthropic
from .capture.dom_snapshot import capture_dom, capture_accessibility, diff_snapshots

__all__ = [
    "Recorder", "record", "wrap", "wrap_anthropic",
    "capture_dom", "capture_accessibility", "diff_snapshots",
]
__version__ = "0.2.0"
