"""호스트 입력 경계에서 확인한 지원 훅 사건을 구분한다."""

from enum import StrEnum


class HookEvent(StrEnum):
    """호스트 입력 경계에서 확인한 지원 훅 사건을 구분한다.

    Attributes:
        SESSION_START: SessionStart 호스트 사건.
        SUBAGENT_START: SubagentStart 호스트 사건.
        USER_PROMPT_SUBMIT: UserPromptSubmit 호스트 사건.
        SESSION_END: SessionEnd 호스트 사건.
        PRE_TOOL_USE: PreToolUse 호스트 사건.
        INTERRUPT: Interrupt 호스트 사건.
        STOP_FAILURE: StopFailure 호스트 사건.
        STOP: Stop 호스트 사건.
        SUBAGENT_STOP: SubagentStop 호스트 사건.
        POST_TOOL_USE: PostToolUse 호스트 사건.
        POST_TOOL_USE_FAILURE: PostToolUseFailure 호스트 사건.
    """

    SESSION_START = "SessionStart"
    SUBAGENT_START = "SubagentStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    SESSION_END = "SessionEnd"
    PRE_TOOL_USE = "PreToolUse"
    INTERRUPT = "Interrupt"
    STOP_FAILURE = "StopFailure"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
