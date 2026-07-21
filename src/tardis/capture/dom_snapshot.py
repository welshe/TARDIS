"""
DOM and accessibility tree snapshot capture for grounding analysis.

Captures structured tree snapshots from browser pages (DOM) and Windows
desktop (UI Automation accessibility tree), with tree diff for detecting
layout shifts, element changes, and grounding failures.
"""

import ipaddress
import platform as _platform
import re
import time
from typing import Any
from urllib.parse import urlparse

SNAPSHOT_SCHEMA_VERSION = "0.2.0"

_PII_PATTERNS = [
    (re.compile(r"\b(password|passwd|pwd)\s*[=:]\s*\S+", re.I), r"\1=***REDACTED***"),
    (re.compile(r"\b(token|secret|api_?key)\s*[=:]\s*\S+", re.I), r"\1=***REDACTED***"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "***SSN***"),
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "***CARD***"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "***EMAIL***"),
]

_BLOCKED_SCHEMES = {"file", "gopher", "ftp", "sftp", "ssh", "telnet"}

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("127.0.0.0/8"),
]


def _redact_pii(text: str) -> str:
    """Redact PII patterns from text content."""
    if not text:
        return text
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _validate_cdp_host(host: str) -> bool:
    """Validate CDP host is localhost-only (SSRF prevention)."""
    allowed = {"localhost", "127.0.0.1", "::1", "[::1]"}
    return host in allowed


def _validate_url(url: str, allowlist: list | None = None) -> bool:
    """Validate URL against allowlist and block dangerous schemes + private IPs.

    Default: localhost only, http/https schemes only.
    Blocks: file://, gopher://, ftp://, and RFC 1918/link-local addresses.
    """
    if allowlist is None:
        allowlist = ["localhost", "127.0.0.1", "::1"]
    try:
        parsed = urlparse(url)
        # Block non-http(s) schemes
        if parsed.scheme and parsed.scheme.lower() in _BLOCKED_SCHEMES:
            return False
        # Only allow http/https if scheme is specified
        if parsed.scheme and parsed.scheme.lower() not in ("http", "https", ""):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Check hostname against allowlist
        if hostname not in allowlist:
            return False
        # If hostname is an explicit IP, check it's not a private/link-local range
        # unless the IP is explicitly in the allowlist (e.g. 127.0.0.1 is allowed)
        try:
            ip = ipaddress.ip_address(hostname)
            if hostname not in allowlist:
                for network in _PRIVATE_NETWORKS:
                    if ip in network:
                        return False
        except ValueError:
            # hostname is not an IP address (e.g. "localhost") — fine, allowlist covers it
            pass
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Playwright-based DOM capture
# ---------------------------------------------------------------------------


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _capture_playwright(
    url: str | None = None,
    browser_type: str = "chromium",
    timeout: float = 10.0,
) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = getattr(p, browser_type).launch()
        page = browser.new_page()
        if url:
            page.goto(url, timeout=int(timeout * 1000))

        page_url = page.url
        title = page.title()

        dom_data = page.evaluate("""() => {
            function walk(node, depth) {
                if (depth > 30 || !node || node.nodeType !== 1) return null;
                const rect = node.getBoundingClientRect();
                const children = [];
                for (const child of node.children) {
                    const c = walk(child, depth + 1);
                    if (c) children.push(c);
                }
                const text = (node.textContent || '').trim().slice(0, 500);
                return {
                    tag: node.tagName.toLowerCase(),
                    id: node.id || undefined,
                    classes: node.classList.length ? Array.from(node.classList) : undefined,
                    text: text || undefined,
                    rect: (rect && (rect.width > 0 || rect.height > 0))
                        ? [roundTo(rect.left), roundTo(rect.top), roundTo(rect.width), roundTo(rect.height)]
                        : undefined,
                    attributes: node.attributes.length
                        ? Object.fromEntries(Array.from(node.attributes).map(a => [a.name, a.value]))
                        : undefined,
                    children: children.length ? children : undefined,
                };
            }
            function roundTo(v) { return Math.round(v * 10) / 10; }
            return walk(document.body, 0) || walk(document.documentElement, 0);
        }""")

        browser.close()

    return {
        "schema": SNAPSHOT_SCHEMA_VERSION,
        "timestamp": time.time(),
        "method": "playwright",
        "browser_type": browser_type,
        "url": page_url,
        "title": title,
        "elements": dom_data,
    }


# ---------------------------------------------------------------------------
# CDP-based DOM capture (lighter dependency: websockets)
# ---------------------------------------------------------------------------


def _cdp_available() -> bool:
    try:
        import websockets  # noqa: F401

        return True
    except ImportError:
        return False


def _capture_cdp(
    host: str = "localhost",
    port: int = 9222,
    timeout: float = 10.0,
) -> dict:
    import asyncio
    import json

    async def _run():
        import websockets

        uri = f"ws://{host}:{port}/devtools/browser"
        async with websockets.connect(uri) as ws:
            msg_id = 1

            async def send(method, params=None, session_id=None):
                nonlocal msg_id
                payload = {"id": msg_id, "method": method}
                if params:
                    payload["params"] = params
                if session_id:
                    payload["sessionId"] = session_id
                msg_id += 1
                await ws.send(json.dumps(payload))
                resp = json.loads(await ws.recv())
                return resp.get("result")

            # Discover page target
            result = await send("Target.getTargets")
            targets = result.get("targetInfos", [])
            page_target = None
            for t in targets:
                if t["type"] == "page":
                    page_target = t
                    break
            if not page_target:
                return {"error": "No page target found"}

            # Attach to page
            result = await send(
                "Target.attachToTarget",
                {"targetId": page_target["targetId"], "flatten": True},
            )
            session_id = result["sessionId"]

            # Get document
            result = await send("DOM.getDocument", {"depth": 4}, session_id)
            root = result.get("root", {})

            # Get URL
            result = await send(
                "Runtime.evaluate", {"expression": "window.location.href"}, session_id
            )
            page_url = result.get("result", {}).get("value", "")

            return {
                "schema": SNAPSHOT_SCHEMA_VERSION,
                "timestamp": time.time(),
                "method": "cdp",
                "url": page_url,
                "elements": _simplify_cdp_node(root),
            }

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import warnings
            warnings.warn(
                "CDP capture from a running event loop not supported "
                "in this context. Returning empty result."
            )
            return {"error": "event_loop_running", "method": "cdp"}
        return loop.run_until_complete(_run())
    except RuntimeError:
        return asyncio.run(_run())


def _simplify_cdp_node(node: dict) -> dict | None:
    """Convert the verbose CDP DOM node into our compact format."""
    if not node or node.get("nodeType") != 1:
        return None
    children = []
    for child in node.get("children") or []:
        simplified = _simplify_cdp_node(child)
        if simplified:
            children.append(simplified)
    attrs = {}
    for attr in node.get("attributes") or []:
        attrs[attr.get("name", "")] = attr.get("value", "")
    return {
        "tag": node.get("localName", "").lower(),
        "id": node.get("nodeId"),
        "text": attrs.pop("_text", None) or None,
        "attributes": attrs or None,
        "children": children or None,
    }


# ---------------------------------------------------------------------------
# High-level DOM capture
# ---------------------------------------------------------------------------


def dom_snapshot_is_available() -> bool:
    """Check whether any DOM capture backend is installed."""
    return _playwright_available() or _cdp_available()


def capture_dom(
    url: str | None = None,
    browser_type: str = "chromium",
    cdp_host: str = "localhost",
    cdp_port: int = 9222,
    timeout: float = 10.0,
    redact: bool = True,
    url_allowlist: list | None = None,
) -> dict:
    """Capture a DOM snapshot from a browser page.

    Auto-selects Playwright over CDP. Raises RuntimeError if neither is
    available.

    Args:
        redact: If True, PII (passwords, tokens, emails, SSNs, cards) is
            redacted from captured text content. Default True for safety.
        url_allowlist: Optional list of allowed hostnames for CDP connection.
            Defaults to localhost only (SSRF prevention).
    """
    if url and not _validate_url(url, url_allowlist):
        raise ValueError(
            f"URL '{url}' not in allowlist. Only localhost connections are allowed by default. "
            "Pass url_allowlist to override (only do this for trusted networks)."
        )

    if _playwright_available():
        result = _capture_playwright(url, browser_type, timeout)
    elif _cdp_available():
        if not _validate_cdp_host(cdp_host):
            raise ValueError(
                f"CDP host '{cdp_host}' not allowed. Only localhost/127.0.0.1/::1 permitted. "
                "This prevents SSRF attacks."
            )
        result = _capture_cdp(cdp_host, cdp_port, timeout)
    else:
        raise RuntimeError(
            "No DOM capture backend available. Install playwright or websockets."
        )

    if redact:
        result = _redact_snapshot(result)

    return result


def _redact_snapshot(snapshot: dict) -> dict:
    """Deep-redact PII from a DOM snapshot tree."""
    if not snapshot:
        return snapshot
    elements = snapshot.get("elements")
    if elements:
        snapshot["elements"] = _redact_element(elements)
    if snapshot.get("url"):
        snapshot["url"] = _redact_pii(snapshot["url"])
    return snapshot


def _redact_element(element: Any) -> Any:
    """Recursively redact PII from DOM element tree."""
    if not element or not isinstance(element, dict):
        return element
    if "text" in element and element["text"]:
        element["text"] = _redact_pii(element["text"])
    for child in element.get("children") or []:
        _redact_element(child)
    return element


# ---------------------------------------------------------------------------
# Windows accessibility tree (UI Automation)
# ---------------------------------------------------------------------------


def accessibility_snapshot_is_available() -> bool:
    """Check if accessibility capture is available (Windows + uiautomation)."""
    if _platform.system() != "Windows":
        return False
    try:
        import uiautomation  # noqa: F401

        return True
    except ImportError:
        return False


def capture_accessibility(max_depth: int = 10) -> dict:
    """Capture the Windows accessibility tree via UI Automation.

    Returns a dict with the root element and its recursively-walked tree.
    Raises RuntimeError if uiautomation is not available.
    """
    if not accessibility_snapshot_is_available():
        raise RuntimeError(
            "Accessibility capture requires Windows + uiautomation. "
            "Install with: pip install uiautomation"
        )

    import uiautomation as uia

    root = uia.GetRootControl()
    if not root:
        return {
            "schema": SNAPSHOT_SCHEMA_VERSION,
            "timestamp": time.time(),
            "method": "uia",
            "error": "No root control found",
        }

    tree = _walk_uia_element(root, max_depth)
    return {
        "schema": SNAPSHOT_SCHEMA_VERSION,
        "timestamp": time.time(),
        "method": "uia",
        "desktop_name": root.Name or "Desktop",
        "elements": tree,
    }


def _walk_uia_element(element, max_depth: int, depth: int = 0) -> dict | None:
    """Recursively walk a UIA element and return a serializable dict."""
    if depth > max_depth or not element:
        return None

    try:
        rect = element.BoundingRectangle
        box = (
            (rect.left, rect.top, rect.width, rect.height)
            if rect and rect.width > 0 and rect.height > 0
            else None
        )
    except Exception:
        box = None

    children = []
    try:
        for child in element.GetChildren():
            child_data = _walk_uia_element(child, max_depth, depth + 1)
            if child_data:
                children.append(child_data)
    except Exception:
        pass

    return {
        "role": element.ControlTypeName,
        "name": element.Name or "",
        "bounding_box": box,
        "automation_id": element.AutomationId or None,
        "control_type": element.ControlTypeName,
        "children": children or None,
    }


# ---------------------------------------------------------------------------
# Snapshot diff
# ---------------------------------------------------------------------------


def diff_snapshots(before: dict, after: dict) -> dict:
    """Produce a structured diff between two snapshots.

    Returns dict keys:
      - before: metadata of the first snapshot
      - after: metadata of the second snapshot
      - added: elements present in *after* but not *before*
      - removed: elements present in *before* but not *after*
      - modified: elements present in both but with attribute / position changes
      - layout_shift: whether a significant bounding-box change was detected
    """
    before_elements = _flatten_tree(before.get("elements"))
    after_elements = _flatten_tree(after.get("elements"))

    before_by_key = {e["_key"]: e for e in before_elements}
    after_by_key = {e["_key"]: e for e in after_elements}

    before_keys = set(before_by_key)
    after_keys = set(after_by_key)

    added_keys = after_keys - before_keys
    removed_keys = before_keys - after_keys
    common_keys = before_keys & after_keys

    added = [after_by_key[k] for k in sorted(added_keys)]
    removed = [before_by_key[k] for k in sorted(removed_keys)]

    modified = []
    layout_shifts = 0
    for key in sorted(common_keys):
        b = before_by_key[key]
        a = after_by_key[key]
        changes = _element_changes(b, a)
        if changes:
            changes["_key"] = key
            modified.append(changes)
            if changes.get("rect_changed"):
                layout_shifts += 1

    return {
        "before": {
            "timestamp": before.get("timestamp"),
            "method": before.get("method"),
        },
        "after": {"timestamp": after.get("timestamp"), "method": after.get("method")},
        "added": added,
        "removed": removed,
        "modified": modified,
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
        "layout_shift": layout_shifts >= max(1, int(len(common_keys) * 0.05)),
        "layout_shift_count": layout_shifts,
    }


def _flatten_tree(element: dict | None, path: str = "") -> list[dict]:
    """Flatten a nested element tree into a list of keyed elements."""
    if not element:
        return []
    result = []
    base_key = (
        element.get("id") or element.get("automation_id") or element.get("tag", "")
    )
    key = f"{base_key}@{path}" if path else (base_key or f"_idx_{len(path)}")
    tagged = {**element, "_key": key, "_path": path}
    result.append(tagged)
    for i, child in enumerate(element.get("children") or []):
        child_path = f"{path}/{child.get('tag', child.get('role', 'node'))}[{i}]"
        result.extend(_flatten_tree(child, child_path))
    return result


def _element_changes(before: dict, after: dict) -> dict | None:
    """Detect changes between two serialized element dicts."""
    changes = {}

    # Text content change
    if before.get("text") and before.get("text") != after.get("text"):
        changes["text"] = {"before": before["text"], "after": after.get("text")}

    # Name change (accessibility)
    if before.get("name") and before.get("name") != after.get("name"):
        changes["name"] = {"before": before["name"], "after": after.get("name")}

    # Role / tag change
    tag_b = before.get("tag") or before.get("role")
    tag_a = after.get("tag") or after.get("role")
    if tag_b and tag_a and tag_b != tag_a:
        changes["type"] = {"before": tag_b, "after": tag_a}

    # Bounding box change
    rect_b = before.get("rect") or before.get("bounding_box")
    rect_a = after.get("rect") or after.get("bounding_box")
    if rect_b and rect_a:
        if _rect_distance(rect_b, rect_a) > 10:
            changes["rect_changed"] = True
            changes["rect"] = {"before": rect_b, "after": rect_a}

    return changes if changes else None


def _rect_distance(a: tuple, b: tuple) -> float:
    """Approximate center-distance between two bounding boxes."""
    if not a or not b or len(a) < 4 or len(b) < 4:
        return float("inf")
    cx_a = a[0] + a[2] / 2
    cy_a = a[1] + a[3] / 2
    cx_b = b[0] + b[2] / 2
    cy_b = b[1] + b[3] / 2
    return ((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2) ** 0.5
