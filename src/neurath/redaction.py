"""Credential redaction for persisted and displayed diagnostic text."""

import re


def clean(value):
    """Redact common credential forms before they reach SQLite or its journal."""
    text = str(value)
    text = re.sub(
        r"(?i)(\b(?:[\w-]*(?:api[_-]?key|password|secret|access[_-]?token)|authorization)\s*[=:]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})\b", "[REDACTED]", text)
    return text
