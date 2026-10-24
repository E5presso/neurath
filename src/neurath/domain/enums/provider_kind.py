"""실행 어댑터가 지원하는 CLI 공급자다."""

from enum import StrEnum


class ProviderKind(StrEnum):
    """실행 어댑터가 지원하는 CLI 공급자다.

    Attributes:
        CODEX: 독립 Codex CLI 실행.
        CLAUDE: 독립 Claude CLI 실행.
    """

    CODEX = "codex"
    CLAUDE = "claude"
