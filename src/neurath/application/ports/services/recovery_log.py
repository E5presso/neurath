"""DB 장애와 호스트 출력 실패를 독립적인 복구 기록에 노출한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.core.common.mutability import immutable


@immutable
class RecoveryReceipt:
    """기록·호스트 제출과 실제 사용자 전달을 구분한 결과다.

    Attributes:
        record_path: 로컬 기록이 성공한 경로이며 실패하면 None.
        host_submitted: stderr 출력이 반환됐는지 여부이며 사용자 수신과 다르다.
        error: 각 출력·저장 경로의 실제 실패 원인.
        delivery: 사용자 수신을 검증하지 않았음을 나타내는 상태.
    """

    record_path: str | None
    host_submitted: bool
    error: str
    delivery: str = "unverified"


@immutable
class RecoveryRecord:
    """독립 journal의 원문과 안정된 출처를 코어에 연결할 관찰이다.

    Attributes:
        origin: 같은 원문 행을 중복 연결하지 않는 내용 식별자.
        detail: 원래 장애 증상.
        reference: 실패한 원 호출의 참조.
        journal_reference: 원문 파일과 행의 위치.
    """

    origin: str
    detail: str
    reference: str
    journal_reference: str


class IRecoveryLogService(ABC):
    """업무 DB가 고장나도 원인·남은 상태를 한 번 기록하는 계약이다."""

    @abstractmethod
    def record(self, detail: str, reference: str) -> RecoveryReceipt:
        """호스트 오류 출력과 로컬 복구 기록을 각각 한 번 시도한다.

        Args:
            detail: 실패 원인과 남은 일에 대한 설명.
            reference: 원 사건·호출·출처 참조.

        Returns:
            RecoveryReceipt: 실제 기록·제출 여부이며 수신은 미확인.

        Raises:
            NotImplementedError: 구현체가 추상 계약에 잘못 위임한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def read(self, path: str | None = None) -> Sequence[RecoveryRecord]:
        """복구 뒤 원 journal을 변경하지 않고 유효한 원문 행을 읽는다.

        Args:
            path: 선택한 journal 또는 사용자 기본 파일의 None.

        Returns:
            Sequence[RecoveryRecord]: 전체 형식을 확인한 원문과 출처.

        Raises:
            NotImplementedError: 구현하지 않은 계약을 호출한 경우.
        """
        raise NotImplementedError
