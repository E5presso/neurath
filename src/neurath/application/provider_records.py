"""provider 경계에서 공유하는 실제 지원 정보와 실행 관찰 계약이다."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    """설치된 호스트에서 조회한 모델과 이 어댑터가 지원하는 명시적 정책이다.

    Attributes:
        provider: 실제 공급자.
        models: 조회 시점에 사용 가능한 구체 모델 ID.
        policies: 이 경로로 전달 가능한 명시적 권한 정책.
    """

    provider: str
    models: Sequence[str]
    policies: Sequence[str]


@dataclass(frozen=True)
class ProviderObservation:
    """원 실행 기록을 읽은 결과이며 작업 목표 달성을 뜻하지 않는다.

    Attributes:
        reference: 배정에 고정된 실행 자료 디렉터리.
        status: prepared·running·completed·failed·unknown·stopped 중 관찰 상태.
        native_session_id: 실제 호스트가 출력한 세션 ID이며 미관찰이면 None.
        output: 원 실행이 출력한 결과 본문.
        error: 실행 실패·불확실성의 설명이며 없으면 None.
    """

    reference: str
    status: str
    native_session_id: str | None = None
    output: str = ""
    error: str | None = None
