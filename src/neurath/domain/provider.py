"""지원하는 독립 실행 공급자와 실제 실행 관찰 상태를 구분한다."""

from enum import StrEnum


class ProviderKind(StrEnum):
    """실행 어댑터가 지원하는 CLI 공급자다.

    Attributes:
        CODEX: 독립 Codex CLI 실행.
        CLAUDE: 독립 Claude CLI 실행.
    """

    CODEX = "codex"
    CLAUDE = "claude"


class ProviderStatus(StrEnum):
    """실제 provider 프로세스의 관찰이며 태스크 성공 판정은 아니다.

    Attributes:
        UNKNOWN: 시작 또는 종료를 아직 확인하지 못함.
        RUNNING: 원 실행 프로세스가 진행 중임.
        COMPLETED: 호스트 결과와 정상 종료를 관찰함.
        FAILED: 호스트 오류 또는 실패 종료를 관찰함.
        STOPPED: 요청한 실제 중단을 관찰함.
    """

    UNKNOWN = "unknown"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
