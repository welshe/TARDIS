# Security Policy

## Threat Model

TARDIS is a debugging and recording tool for AI agents. It captures system-level
events including keyboard/mouse input, screen captures, DOM snapshots, and
optionally kernel-level syscalls. This creates inherent security risks that
users must understand.

### Known Risks

| Feature | Risk | Mitigation |
|---------|------|------------|
| Win32 Keyboard Hooks | Captures ALL keystrokes including passwords | Opt-in only; PII redaction enabled by default; events stored in memory-only deque zeroed on stop; never persisted to disk unless explicitly saved |
| eBPF/ETW Kernel Tracing | Requires root/admin; captures system calls | Privilege drop after session start; fail-closed design; no arbitrary filter strings; BPF verifier validation |
| DOM Snapshots | May capture page content including form data, credentials in autofill, session tokens | PII redaction by default (passwords, tokens, SSNs, credit cards, emails); URL allowlist (localhost-only); SSRF prevention with RFC 1918 blocking |
| LLM Proxy | Captures all LLM requests/responses including sensitive data | Content-addressed hashing; PII redaction in recorder; no plaintext persistence without explicit save |
| Time-Travel Replay | System state snapshots may contain secrets in environment variables | Automatic env var redaction (API keys, tokens, secrets, passwords masked before storage) |
| Semantic Cache | Cached LLM responses could contain sensitive data | Local-only cache; content-addressed via SHA-256; no external sync; TTL-based expiry |
| ML Classifier | Trained model could memorize failure patterns | No external model loading; all training data stays local; no data exfiltration |
| Tool Registry | Registered tools could be exploited | Security scanning on registration (injection, traversal, dangerous names); permission-based execution; rate limiting |
| Real-Time Dashboard | Exposes monitoring data over HTTP | Localhost-only binding by default; read-only API endpoints; no authentication (local dev only) |
| Compliance Auditor | Provides compliance checking guidance | LEGAL DISCLAIMER: This is NOT legal advice. Always consult qualified legal counsel. |
| Regression Test Generator | Writes pytest test files to disk | Output directory defaults to `.tardis/regression_tests/`; no user code execution during generation; generated tests load traces from local SQLite store only; `run_tests` subprocess uses timeout (120s) and captures output only |
| Trace Diff Viewer | Reads and compares two traces side-by-side | Read-only operation; no data mutation; HTML export is static file output; no network exposure from diff viewer |
| Natural Language Trace Search | Searches traces using expanded query terms | Read-only operation; queries expand locally (no external API calls); LanceDB queries are bounded by limit parameter; keyword fallback operates on local SQLite store only |
| Real-Time Trace Streaming | WebSocket-based trace event streaming | Localhost-only binding (127.0.0.1) by default; no authentication (local dev only); rate limiting (200 events/sec); max 50 subscribers per session; session TTL (1 hour); clients cannot mutate trace state; no network exposure unless explicitly bound to non-loopback address |

### Security Hardening Applied

- **SQL injection prevention**: All SQLite queries use parameterized statements. LanceDB operations validate trace_id against regex patterns before use.
- **Path traversal blocking**: Database paths are resolved and validated against working directory. LanceDB rejects invalid trace_id formats. Feedback loop sanitizes filenames on disk write.
- **SSRF prevention**: CDP connections restricted to localhost/127.0.0.1/::1. URL allowlist enforced. Blocked schemes: `file://`, `gopher://`, `ftp://`. Blocked IP ranges: RFC 1918, link-local.
- **PII redaction**: Passwords, tokens, SSNs, credit cards, emails are automatically redacted from recorded data via regex patterns and key-name matching. Redaction applied to: recorder dicts, DOM snapshots, environment variables, keyboard events.
- **Process isolation**: Red-team attacks and what-if simulations run in sandboxed subprocesses with resource limits (memory cap, CPU timeout, file size limit).
- **Privilege dropping**: Kernel tracers drop to minimum required privileges (nobody user) after initialization on Linux.
- **Fail-closed**: If any security-critical component fails to initialize, the operation is blocked rather than proceeding insecurely.
- **Injection pattern validation**: Autopsy plugins, repair hypotheses, swarm agent outputs, and tool registry entries are validated against injection patterns before processing.
- **SHA-256 hashing**: Used throughout for content addressing, integrity verification, and forensic logging.
- **Memory zeroing**: Keyboard/mouse event buffers are cleared on stop() to prevent crash-dump leaks.
- **Code generation safety**: Regression test generator sanitizes trace IDs and error types for safe Python code generation — prevents injection into generated test files.
- **XSS prevention**: Trace diff HTML export escapes all user-controlled values (trace IDs, step types, hashes) via `html.escape()`.
- **Input bounds**: Natural language search enforces max query length (2000 chars) and result limit caps (max 100). Streaming server enforces max message size (64 KB) and validates trace_id format against allowlist regex.
- **Non-interactive safety**: Replay engine detects non-interactive (non-TTY) environments and skips blocking `input()` calls at breakpoints.
- **Resource bounds**: Orchestrator thread pool capped at 64 workers to prevent unbounded thread creation.

## Reporting Vulnerabilities

If you discover a security vulnerability in TARDIS:

1. **Do NOT** open a public GitHub issue
2. Email security concerns to the repository maintainer
3. Include: description of vulnerability, steps to reproduce, potential impact
4. Allow reasonable time for response before public disclosure

## Production Use

**TARDIS is a debugging and observability tool, not a production security system.** Key warnings:

- Win32 hooks capture system-wide input — never enable in production environments
  without explicit user consent and appropriate data handling policies
- Kernel tracing requires elevated privileges — use only in development/testing
  environments, never in production
- The compliance auditor provides automated guidance, not legal compliance guarantees
  — always consult qualified legal counsel for compliance decisions
- LLM proxy records all model interactions — ensure your infrastructure meets
  data retention and privacy requirements before enabling
- The real-time dashboard is designed for local development use only — no
  authentication is implemented
- The semantic cache stores LLM responses locally — sensitive data may be
  retained in cache files

## Data Handling

- All captured data is stored locally in `.tardis/` with owner-only permissions on Unix
- No data is sent to external services unless you explicitly configure LLM proxy endpoints
- PII redaction is enabled by default but is heuristic-based — not guaranteed to catch all sensitive data
- You are responsible for managing `.tardis/` directory access controls and scheduled cleanup
- Environment variable redaction masks common secret patterns but custom env vars may not be caught
- Cache files in `.tardis/cache/` should be cleared regularly in production-like environments

## Secure Development

- All contributions must pass security scanning checks in CI
- New features capturing user data must implement PII redaction by default
- No eval/exec on untrusted or LLM-generated content
- All subprocess execution must use timeouts and resource limits
- API endpoints must be read-only unless explicitly authenticated
- Sensitive defaults must be opt-in (e.g., Win32 hooks, kernel tracing)
