"""실제 provider의 모델 조회·실행·관찰·중단을 위한 외부 경계다."""

from abc import ABC, abstractmethod
from uuid import UUID

from neurath.application.provider_records import ProviderCapabilities, ProviderObservation
from neurath.domain.delegation_records import ProviderPlan
from neurath.domain.provider import ProviderKind


class IProviderService(ABC):
    """계획 확인과 실제 실행을 구분하고 원 실행 ID로만 복구한다."""

    @abstractmethod
    def discover(self, provider: ProviderKind) -> ProviderCapabilities:
        """모델을 실행하지 않고 현재 호스트의 지원 정보를 조회한다.

        Args:
            provider: 조회할 설치 공급자.

        Returns:
            ProviderCapabilities: 실제 조회한 모델과 지원 정책.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def start(self, delegation_id: UUID, plan: ProviderPlan, prompt: str) -> ProviderObservation:
        """같은 배정의 실행을 한 번 시작하고 재호출은 기존 기록을 반환한다.

        Args:
            delegation_id: 중복 실행을 막는 원 배정 ID.
            plan: 고정된 모델·정책·실행 폴더.
            prompt: 원 지시와 맡긴 범위.

        Returns:
            ProviderObservation: 실제 제출 상태. 완료와 구분한다.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def observe(self, delegation_id: UUID) -> ProviderObservation:
        """기존 실행만 관찰하며 프로세스나 모델 턴을 새로 만들지 않는다.

        Args:
            delegation_id: 관찰할 원 배정 ID.

        Returns:
            ProviderObservation: 현재 실제 실행 자료의 상태.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel(self, delegation_id: UUID) -> ProviderObservation:
        """이 어댑터가 만든 실행만 중단하고 실제 종료는 별도 관찰한다.

        Args:
            delegation_id: 중단할 원 배정 ID.

        Returns:
            ProviderObservation: 중단 확인 또는 아직 불명인 실제 상태.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError
