# Contributing to TARDIS

## Code of Conduct

This project follows an open, respectful contribution model. Be constructive,
professional, and inclusive in all interactions.

## Development Setup

```bash
git clone https://github.com/welshe/TARDIS
cd TARDIS
pip install -e ".[dev]"
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Code Style

- **Formatting**: Ruff with default rules (`ruff check src/tardis/ tests/`)
- **Line length**: 88 characters (Black-compatible)
- **Imports**: Standard library first, then third-party, then TARDIS internal
- **Types**: Type annotations required on all public functions
- **Docstrings**: Google-style docstrings, include SECURITY sections for security-sensitive code

## Pull Request Process

1. Ensure all tests pass before submitting
2. Add tests for new functionality
3. Run `ruff check src/tardis/ tests/` and fix any issues
4. Update README.md if adding new features
5. Add security warnings to docstrings for any feature that captures or processes data
6. Update the feature status table if applicable

## Security Requirements

All contributions that capture or process user data MUST:

1. Implement PII redaction (passwords, tokens, SSNs, emails, credit cards)
2. Include SECURITY NOTICE docstring at the top of new modules
3. Be opt-in by default (never auto-enable data capture)
4. Use SHA-256 hashing for content addressing
5. Validate all inputs against injection patterns (SQL, shell, path traversal)
6. Use parameterized queries for all database operations
7. Implement fail-closed error handling for security-critical components
8. Add `SECURITY:` section to function/class docstrings explaining mitigations

## Feature Checklist for New Modules

- [ ] Module-level docstring with security notice
- [ ] Docstrings on all public classes and methods
- [ ] Type annotations on all function signatures
- [ ] PII redaction (if applicable)
- [ ] Tests covering: expected behavior, edge cases, security boundaries
- [ ] Registered in `src/tardis/__init__.py` exports
- [ ] Added to README feature status table
- [ ] Ruff-clean (no errors or warnings)

## Versioning

This project follows SemVer (vMAJOR.MINOR.PATCH). Features that break backward
compatibility require a major version bump.

## License

By contributing, you agree that your contributions will be licensed under the
project's MIT License.
