"""
Unit tests for DOM/accessibility snapshot capture and diff.
"""

import pytest

from tardis.capture.dom_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    _element_changes,
    _flatten_tree,
    _rect_distance,
    _simplify_cdp_node,
    accessibility_snapshot_is_available,
    capture_accessibility,
    capture_dom,
    diff_snapshots,
    dom_snapshot_is_available,
)


def test_schema_version():
    assert SNAPSHOT_SCHEMA_VERSION == "0.2.0"


def test_dom_snapshot_available():
    """Should detect available backends (websockets is a transitive dep)."""
    available = dom_snapshot_is_available()
    assert isinstance(available, bool)


def test_capture_dom_uses_available_backend():
    """Should use the available backend without raising."""
    try:
        import websockets  # noqa: F401

        has_ws = True
    except ImportError:
        has_ws = False

    try:
        import playwright  # noqa: F401

        has_pw = True
    except ImportError:
        has_pw = False

    if not has_ws and not has_pw:
        with pytest.raises(RuntimeError, match="No DOM capture backend"):
            capture_dom()
    else:
        # Should raise ConnectionRefused (no actual browser) not RuntimeError
        try:
            capture_dom(timeout=1.0)
        except RuntimeError:
            pytest.fail("capture_dom raised RuntimeError when a backend is available")
        except Exception:
            pass  # Expected: connection error from CDP or Playwright


def test_capture_accessibility_raises_without_backend():
    if accessibility_snapshot_is_available():
        pytest.skip(
            "Accessibility capture available - cannot test missing dependency path"
        )
    with pytest.raises(RuntimeError, match="uiautomation"):
        capture_accessibility()


def test_flatten_tree_empty():
    assert _flatten_tree(None) == []
    assert _flatten_tree({}) == []


def test_flatten_tree_single_element():
    elem = {"tag": "div", "id": "root"}
    flat = _flatten_tree(elem)
    assert len(flat) == 1
    assert flat[0]["_key"] == "root"


def test_flatten_tree_nested():
    elem = {
        "tag": "div",
        "children": [
            {"tag": "span", "children": [{"tag": "a", "text": "link"}]},
            {"tag": "p", "text": "para"},
        ],
    }
    flat = _flatten_tree(elem)
    # root + span + a + p = 4
    assert len(flat) == 4


def test_element_changes_text():
    before = {"text": "hello", "id": "x"}
    after = {"text": "world", "id": "x"}
    changes = _element_changes(before, after)
    assert changes is not None
    assert changes["text"] == {"before": "hello", "after": "world"}


def test_element_changes_rect():
    before = {"rect": (10, 20, 100, 50), "id": "x"}
    after = {"rect": (200, 300, 100, 50), "id": "x"}
    changes = _element_changes(before, after)
    assert changes is not None
    assert changes["rect_changed"] is True


def test_element_changes_no_change():
    before = {"text": "same", "rect": (0, 0, 10, 10), "id": "x"}
    after = {"text": "same", "rect": (0, 0, 10, 10), "id": "x"}
    assert _element_changes(before, after) is None


def test_rect_distance():
    assert _rect_distance((0, 0, 10, 10), (100, 0, 10, 10)) == pytest.approx(100.0)
    assert _rect_distance((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(0.0)
    assert _rect_distance(None, (0, 0, 10, 10)) == float("inf")


def test_diff_snapshots_identical():
    tree = {"tag": "div", "id": "r", "children": [{"tag": "p", "text": "hi"}]}
    snap = {"timestamp": 100.0, "method": "test", "elements": tree}
    diff = diff_snapshots(snap, snap)
    assert diff["added_count"] == 0
    assert diff["removed_count"] == 0
    assert diff["modified_count"] == 0


def test_diff_snapshots_added():
    before = {
        "timestamp": 100.0,
        "method": "test",
        "elements": {"tag": "div", "id": "r"},
    }
    after = {
        "timestamp": 101.0,
        "method": "test",
        "elements": {
            "tag": "div",
            "id": "r",
            "children": [{"tag": "p", "text": "new"}],
        },
    }
    diff = diff_snapshots(before, after)
    assert diff["added_count"] == 1
    assert diff["removed_count"] == 0


def test_diff_snapshots_removed():
    before = {
        "timestamp": 100.0,
        "method": "test",
        "elements": {
            "tag": "div",
            "id": "r",
            "children": [{"tag": "p", "text": "old"}],
        },
    }
    after = {
        "timestamp": 101.0,
        "method": "test",
        "elements": {"tag": "div", "id": "r"},
    }
    diff = diff_snapshots(before, after)
    assert diff["added_count"] == 0
    assert diff["removed_count"] == 1


def test_diff_snapshots_layout_shift():
    before = {
        "timestamp": 100.0,
        "method": "test",
        "elements": {
            "tag": "div",
            "id": "r",
            "children": [{"tag": "button", "id": "btn", "rect": (10, 10, 100, 40)}],
        },
    }
    after = {
        "timestamp": 101.0,
        "method": "test",
        "elements": {
            "tag": "div",
            "id": "r",
            "children": [{"tag": "button", "id": "btn", "rect": (300, 400, 100, 40)}],
        },
    }
    diff = diff_snapshots(before, after)
    assert diff["layout_shift"] is True
    assert diff["layout_shift_count"] == 1


def test_simplify_cdp_node():
    raw = {
        "nodeType": 1,
        "localName": "DIV",
        "nodeId": 42,
        "attributes": [{"name": "class", "value": "main"}],
        "children": [],
    }
    result = _simplify_cdp_node(raw)
    assert result is not None
    assert result["tag"] == "div"
    assert result["id"] == 42
    assert result["attributes"] == {"class": "main"}


def test_simplify_cdp_node_skips_non_element():
    raw = {"nodeType": 3, "localName": "#text"}
    assert _simplify_cdp_node(raw) is None


def test_grounding_check_with_snapshot_diff():
    """Verify that snapshot diffs trigger grounding failure in the classifier."""
    from tardis.autopsy.classifier import Autopsy
    from tardis.models import FailureType, Step, StepType, Trace

    trace = Trace()

    # Two snapshot steps with different element positions
    snap1 = {
        "schema": "0.2.0",
        "timestamp": 100.0,
        "method": "test",
        "elements": {
            "tag": "div",
            "id": "r",
            "children": [
                {"tag": "button", "id": "btn", "rect": (10, 10, 100, 40)},
            ],
        },
    }
    snap2 = {
        "schema": "0.2.0",
        "timestamp": 101.0,
        "method": "test",
        "elements": {
            "tag": "div",
            "id": "r",
            "children": [
                {"tag": "button", "id": "btn", "rect": (300, 400, 100, 40)},
            ],
        },
    }

    trace.add_step(
        Step(
            trace_id="test", index=0, type=StepType.dom_snapshot, input={}, output=snap1
        )
    )
    trace.add_step(
        Step(
            trace_id="test", index=1, type=StepType.dom_snapshot, input={}, output=snap2
        )
    )

    # Add a tool error to ensure the trace is marked as failed
    trace.add_step(
        Step(
            trace_id="test",
            index=2,
            type=StepType.error,
            input={},
            output={"error": "ElementNotFound: button moved"},
        )
    )

    autopsy = Autopsy(trace)
    failure_type, details, confidence = autopsy.classify()

    assert failure_type == FailureType.grounding_failure, (
        f"Got {failure_type}: {details}"
    )
    assert confidence >= 0.5
    evidence_keys = [e[0] for e in autopsy.evidence]
    assert any("layout" in k for k in evidence_keys), (
        f"No layout evidence in {evidence_keys}"
    )
