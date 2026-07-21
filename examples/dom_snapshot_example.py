"""
Example: capturing DOM and accessibility snapshots with TARDIS.

Shows how to capture structured snapshots of browser pages (via Playwright
or CDP) and Windows desktop (via UI Automation), then diff them for layout
shift detection and grounding analysis.
"""

import tardis
from tardis.capture.dom_snapshot import (
    capture_dom,
    capture_accessibility,
    dom_snapshot_is_available,
    accessibility_snapshot_is_available,
    diff_snapshots,
)

# 1. Start recorder
rec = tardis.Recorder().start()
print("Recording started — TARDIS will capture every step.\n")

# 2. Capture a DOM snapshot (if a backend is available)
if dom_snapshot_is_available():
    print("[ DOM ] Capturing browser page...")
    try:
        dom = capture_dom(url="https://example.com")
        rec.log_dom_snapshot(dom)
        print(f"  Captured DOM: {dom.get('url')} ({len(str(dom))} bytes)")
    except Exception as e:
        print(f"  DOM capture skipped: {e}")
else:
    # Simulate a DOM snapshot for demonstration
    print("[ DOM ] No browser backend found — using simulated snapshot.")
    simulated_dom = {
        "schema": "0.2.0",
        "timestamp": 100.0,
        "method": "simulated",
        "url": "https://example.com",
        "title": "Example",
        "elements": {
            "tag": "div",
            "id": "root",
            "children": [
                {"tag": "h1", "text": "Example Domain"},
                {
                    "tag": "p",
                    "text": "This domain is for use in illustrative examples.",
                },
            ],
        },
    }
    rec.log_dom_snapshot(simulated_dom)
    print("  Logged simulated DOM snapshot.")

# 3. Capture an accessibility snapshot (Windows only)
if accessibility_snapshot_is_available():
    print("\n[ ACCESSIBILITY ] Capturing Windows UI tree...")
    try:
        acc = capture_accessibility()
        rec.log_accessibility_snapshot(acc)
        print("  Captured accessibility tree")
    except Exception as e:
        print(f"  Accessibility capture skipped: {e}")
else:
    # Simulate an accessibility snapshot
    print(
        "\n[ ACCESSIBILITY ] Not on Windows or uiautomation missing — using simulated snapshot."
    )
    simulated_acc = {
        "schema": "0.2.0",
        "timestamp": 101.0,
        "method": "simulated",
        "desktop_name": "Desktop",
        "elements": {
            "role": "Pane",
            "name": "Desktop",
            "children": [
                {
                    "role": "Window",
                    "name": "Example App",
                    "children": [
                        {
                            "role": "Button",
                            "name": "Submit",
                            "bounding_box": (100, 200, 80, 30),
                        },
                    ],
                },
            ],
        },
    }
    rec.log_accessibility_snapshot(simulated_acc)
    print("  Logged simulated accessibility snapshot.")

# 4. Simulate a second snapshot with different positions (layout shift)
print("\n[ DIFF ] Simulating layout shift for grounding analysis...")
snapshot_before = {
    "elements": {
        "tag": "div",
        "children": [
            {"tag": "button", "id": "submit", "rect": (100, 200, 80, 30)},
        ],
    },
}
snapshot_after = {
    "elements": {
        "tag": "div",
        "children": [
            {"tag": "button", "id": "submit", "rect": (300, 450, 80, 30)},
        ],
    },
}
diff = diff_snapshots(snapshot_before, snapshot_after)
print(f"  Layout shift detected: {diff['layout_shift']}")
print(f"  Modified elements: {diff['modified_count']}")
for mod in diff["modified"][:3]:
    print(f"    Element {mod['_key']}: rect changed {mod.get('rect')}")

# 5. Stop and summarize
trace = rec.stop()
print("\n=== TRACE SUMMARY ===")
print(f"Trace ID: {trace.id}")
print(f"Total steps: {len(trace.steps)}")
print(f"Success: {trace.success}")

# Show step breakdown
from collections import Counter

step_types = Counter(s.type.value for s in trace.steps)
print("\nStep breakdown:")
for step_type, count in step_types.most_common():
    print(f"  {step_type}: {count}")

print(f"\nRun: tardis replay {trace.id}")
print(f"Run: tardis autopsy {trace.id}")
print(f"Run: tardis show {trace.id}")
