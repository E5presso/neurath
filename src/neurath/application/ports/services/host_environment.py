"""호스트가 전달한 현재 세션 주소와 작업 폴더를 읽는 계약이다."""

from abc import ABC, abstractmethod

from spakky.core.common.mutability import immutable


@immutable
class HostEnvironment:
    """명령이 실행되는 호스트 맥락이며 별도 권한 증명으로 사용하지 않는다.

    Attributes:
        directory: 현재 작업 폴더.
        session: 호스트가 제공한 세션 또는 네이티브 자식 주소.
        provider: 명시되거나 환경에서 관찰된 호스트 이름.
    """

    directory: str
    session: str
    provider: str


class IHostEnvironmentService(ABC):
    """사용자가 내부 UUID를 조립하지 않아도 현재 호스트 맥락을 얻는다."""

    @abstractmethod
    def read(self) -> HostEnvironment:
        """현재 호출의 환경을 읽는다.

        Returns:
            HostEnvironment: 실제 환경에 없는 식별자는 빈 문자열이다.

        Raises:
            NotImplementedError: 구현하지 않은 포트를 직접 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def publish(self, provider: str, session: str) -> None:
        """호스트가 환경 파일을 제공한 경우만 관찰된 세션 주소를 전달한다.

        Args:
            provider: 실제 호스트 공급자.
            session: 실제 네이티브 세션 주소.

        Raises:
            NotImplementedError: 구현하지 않은 포트를 직접 호출한 경우.
        """
        raise NotImplementedError
