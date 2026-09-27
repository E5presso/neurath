"""Canonical review taxonomy shared by validators and delegation preparation."""

REVIEW_CODE_ROWS = (
    ("C01", "architecture-boundary", "critical"),
    ("C02", "type-discipline", "warning"),
    ("C03", "yagni", "warning"),
    ("C04", "domain-boundary", "critical"),
    ("C05", "naming", "warning"),
    ("C06", "test-gate", "critical"),
    ("C07", "readability", "warning"),
    ("C08", "api-contract", "warning"),
    ("C09", "persistence", "warning"),
    ("C10", "transaction-integrity", "critical"),
    ("C11", "pattern-consistency", "warning"),
    ("C12", "defensive-helper", "warning"),
    ("C13", "operations-consistency", "warning"),
    ("C14", "spec-completeness", "critical"),
)
