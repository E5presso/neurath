"""호스트가 유지·계속·중지해야 할 동작이며 태스크 성공을 뜻하지 않는다."""

from enum import StrEnum


class HookAction(StrEnum):
    """호스트가 유지·계속·중지해야 할 동작이며 태스크 성공을 뜻하지 않는다.

    Attributes:
        ALLOW: 네이티브 권한 판단을 유지하며 이 훅의 추가 제한이 없음.
        CONTINUE: 남은 일을 계속하도록 한 번 피드백함.
        PAUSE: 모델 재시도 없이 호스트에 제어권을 반환함.
    """

    ALLOW = "allow"
    CONTINUE = "continue"
    PAUSE = "pause"
