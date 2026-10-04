# Validation boundaries

[한국어](../../ko/contributing/validation.md) · [Core contract](core-v2-spec.md)

Run `uv run --locked python tools/check.py` for the required source gate. It checks version consistency, manifest integrity, Python diagnostics, maintained package/installation tests and the isolated core contract suite. Focused runs are partial evidence. Use `tools/run_core_regressions.py --workers 0 tests/test_domain.py` for an isolated contract subset.

Build the exact wheel and use `tools/validate_distribution.py` to execute it in an external environment, and `tools/validate_setup.py` for installation preservation. Native hook protocol fixtures test payload handling, not actual host loading. Actual-host tests must observe both skipped-phase denial and unfinished-task Stop continuation in the same Task. Keep private logs outside public docs and distributions. A passing subset, agent report or installation does not imply release readiness.
