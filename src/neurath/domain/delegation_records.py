"""배정 경로·실행 정책·보고 역할을 명시적인 값으로 표현한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


class DelegationRoute(StrEnum):
    """실제 피어·네이티브 자식·독립 실행의 관계를 구분한다.

    Attributes:
        PEER: 기존 피어에게 전달.
        CHILD: 실제 부모 관계가 있는 네이티브 자식에게 전달.
        PROVIDER: 별도 provider 실행.
    """

    PEER = "peer"
    CHILD = "child"
    PROVIDER = "provider"


class DelegationRole(StrEnum):
    """수행 보고와 검토 보고의 책임을 구분한다.

    Attributes:
        EXECUTOR: 맡은 범위의 수행자.
        REVIEWER: 기존 산출물의 독립 검토자.
    """

    EXECUTOR = "executor"
    REVIEWER = "reviewer"


class DelegationStatus(StrEnum):
    """배정 준비부터 실제 결과·중단 관찰까지의 상태다.

    Attributes:
        PREPARED: 계획만 저장했고 아직 전달하지 않음.
        ASSIGNED: 수신 경로에 배정을 제출함.
        ACCEPTED: 수신자가 최신 배정을 수락함.
        RUNNING: 수신자가 실제 작업 시작을 보고함.
        COMPLETED: 수신자의 결과 보고를 받음. 태스크 성공과 별개.
        STOP_REQUESTED: 정정·취소를 반영했으나 실제 중단은 미확인.
        STOPPED: 해당 실행이 중단됐다는 관찰이 있음.
    """

    PREPARED = "prepared"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"


@immutable
class ProviderPlan(AbstractValueObject):
    """실행 전에 확정한 실제 provider 모델과 정책이다.

    Attributes:
        provider: 지원 공급자 이름.
        model: 공급자 조회에서 확인한 모델 ID.
        policy: 지원되는 명시적 실행 권한 정책.
        directory: 실행할 작업 디렉터리.
        parent_session_id: 배정한 Neurath 세션. 네이티브 부모 관계를 뜻하지 않는다.
    """

    provider: str
    model: str
    policy: str
    directory: str
    parent_session_id: str

    @override
    def validate(self) -> None:
        """빈 계획과 암묵적 권한 상속을 거부한다.

        Raises:
            ValueError: 계획 필드가 비어 있거나 상속을 명시한 경우.
        """
        if (
            not all(
                value.strip()
                for value in (
                    self.provider,
                    self.model,
                    self.policy,
                    self.directory,
                    self.parent_session_id,
                )
            )
            or self.policy == "inherit"
        ):
            raise ValueError("Provider plan requires an explicit model and supported policy")


@immutable
class DelegationReport(AbstractValueObject):
    """수행자 또는 검토자가 실제 관찰 근거와 함께 제출한 보고다.

    Attributes:
        summary: 수행 또는 검토 결과의 원문.
        references: 산출물·검사·검토 후보의 참조.
        remaining_work: 아직 해결하지 못한 범위이며 없으면 None.
    """

    summary: str
    references: Sequence[str]
    remaining_work: str | None = None

    @override
    def validate(self) -> None:
        """근거 없는 결과 보고와 공백 남은 일을 거부한다.

        Raises:
            ValueError: 본문·근거·남은 일 표현이 잘못된 경우.
        """
        if (
            not self.summary.strip()
            or not self.references
            or any(not r.strip() for r in self.references)
        ):
            raise ValueError("Delegation report requires summary and evidence")
        if self.remaining_work is not None and not self.remaining_work.strip():
            raise ValueError("Remaining work must be non-empty when present")
