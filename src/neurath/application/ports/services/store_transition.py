"""SQLite 작성 경로의 실제 퇴역과 전환 중 사건 보존을 제공한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from spakky.core.common.mutability import immutable


@immutable
class StoreFence:
    """원래 SQLite 경로가 실제로 차단된 기술 결과다.

    Attributes:
        source: 원래 접속 경로.
        directory: 퇴역 파일·전환 사건을 보관한 폴더.
        snapshot: 작성 정지 전에 확보한 일관된 사본.
        retired: 원래 데이터 파일의 보존 위치.
    """

    source: str
    directory: str
    snapshot: str
    retired: str


@immutable
class TransitionEvent:
    """전환 도중 받은 실제 정규화 사건과 원 입력이다.

    Attributes:
        uid: 중복 재생을 구분하는 내부 사건 ID.
        command: 기존 훅 계약으로 정규화한 입력.
        payload: 호스트가 준 원 JSON 입력.
    """

    uid: UUID
    command: dict[str, Any]
    payload: dict[str, Any]


class IStoreTransitionService(ABC):
    """사용자 승인 표지가 아닌 SQLite·파일 시스템의 실제 전환 경계다."""

    @abstractmethod
    def fence(self, source: str, archive_directory: str) -> StoreFence:
        """열린 연결 관찰과 SQLite 쓰기 잠금 후 원 접속 경로를 퇴역한다.

        Args:
            source: 실제 차단할 SQLite 경로.
            archive_directory: 원본/WAL 사본 보관 폴더.

        Returns:
            StoreFence: 실제 파일 경로 차단 결과.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def enqueue(self, command: dict[str, Any], payload: dict[str, Any]) -> UUID | None:
        """현재 코어가 전환 중일 때만 받은 실제 사건을 순서대로 보존한다.

        Args:
            command: 정규화한 기존 훅 입력.
            payload: 원 호스트 JSON.

        Returns:
            UUID | None: 보존한 사건이며 정상 코어는 None.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def pending(self, directory: str) -> Sequence[TransitionEvent]:
        """적용을 확인하지 못한 사건을 원래 접수 순서로 읽는다.

        Args:
            directory: 실제 전환 폴더.

        Returns:
            Sequence[TransitionEvent]: 아직 처리하지 않은 원 사건.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def acknowledge(self, directory: str, event_id: UUID) -> None:
        """코어 트랜잭션 완료 후에만 해당 사건의 적용을 기록한다.

        Args:
            directory: 전환 사건 폴더.
            event_id: 실제 적용한 사건.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError
