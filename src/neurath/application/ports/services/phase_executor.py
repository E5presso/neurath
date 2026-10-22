"""저장 트랜잭션 밖의 실행·조회와 대기 알림 계약을 정의한다."""

from abc import ABC, abstractmethod

from neurath.domain.workflow_records import PhaseDefinition, PhaseResult


class IPhaseExecutorService(ABC):
    """같은 시도 식별자로 실행을 제출하고 유실된 결과를 조회한다."""

    @property
    @abstractmethod
    def supports_deduplication(self) -> bool:
        """동일 시도 재제출의 중복 실행 방지를 외부 실행기가 보장하는지 반환한다.

        Returns:
            bool: 같은 식별자의 재제출을 안전하게 조정할 수 있는지 여부.

        Raises:
            NotImplementedError: 실행기가 보장 범위를 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, request_id: str, phase: PhaseDefinition) -> PhaseResult:
        """해당 시도의 명령 또는 위임을 실제 실행하고 관찰 결과를 반환한다.

        Args:
            request_id: run과 시도 번호를 연결한 안정적인 외부 실행 ID.
            phase: 명령·대상·검증 조건·실행 한도.

        Returns:
            PhaseResult: 실제 실행에서 확인한 결과.

        Raises:
            NotImplementedError: 실제 실행 경로가 구현되지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def lookup(self, request_id: str, phase: PhaseDefinition) -> PhaseResult | None:
        """실행을 새로 시작하지 않고 기존 시도의 외부 결과만 조회한다.

        Args:
            request_id: 결과를 찾을 같은 시도의 외부 ID.
            phase: 시도 당시의 실행 대상과 조건.

        Returns:
            PhaseResult | None: 확인한 결과. 조회할 수 없거나 아직 모르면 None.

        Raises:
            NotImplementedError: 조회 계약이 구현되지 않은 경우.
        """
        raise NotImplementedError


class IWorkflowNotifierService(ABC):
    """재실행할 수 없는 결과 불명을 호출 환경에 알린다."""

    @abstractmethod
    def waiting(self, request_id: str, reason: str) -> None:
        """같은 결과 불명으로 실행자를 반복 호출하지 않고 대기 이유를 전달한다.

        Args:
            request_id: 결과 확인이 필요한 시도 ID.
            reason: 결과 불명과 필요한 관찰의 설명.

        Raises:
            NotImplementedError: 알림 전달이 구현되지 않은 경우.
        """
        raise NotImplementedError
