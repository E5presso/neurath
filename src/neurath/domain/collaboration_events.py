"""현재 요구 변경을 해당 배정의 정정·중단 전파에 연결한다."""

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.delegation_records import ProviderPlan


@immutable
class TaskDefinitionChanged(AbstractDomainEvent):
    """커밋된 태스크의 최신 요구를 배정 처리자가 다시 읽게 한다.

    Attributes:
        task_id: 실제로 정정·무효화된 원 태스크.
    """

    task_id: str


@immutable
class ProviderExecutionRequested(AbstractDomainEvent):
    """고정한 계획의 외부 실행을 커밋 후 요청한다.

    Attributes:
        delegation_id: 검증하고 저장한 배정 ID.
        plan: 실제 모델·정책·작업 폴더.
        prompt: 원 지시·요구·범위가 담긴 입력.
    """

    delegation_id: str
    plan: ProviderPlan
    prompt: str


@immutable
class ProviderExecutionObserved(AbstractDomainEvent):
    """원 실행에 대한 실제 상태·출력 관찰이다.

    Attributes:
        delegation_id: 관찰한 원 배정 ID.
        reference: 원 실행 자료 위치.
        status: 실제 관찰 상태.
        native_session_id: 실제 호스트 세션 ID.
        output: 실행 결과 본문.
        error: 실패 또는 불확실성의 설명.
    """

    delegation_id: str
    reference: str
    status: str
    native_session_id: str | None
    output: str
    error: str | None


@immutable
class ProviderStopRequested(AbstractDomainEvent):
    """원 요구 변경에 영향받은 provider 실행만 중단하도록 요청한다.

    Attributes:
        delegation_id: 중단 요청이 커밋된 배정.
        sender_id: 원 배정의 책임 피어.
    """

    delegation_id: str
    sender_id: str
