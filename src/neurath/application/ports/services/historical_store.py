"""과거 SQLite의 읽기·일관된 사본·기능별 자료 해석을 외부 기술로 분리한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from spakky.core.common.mutability import immutable


@immutable
class HistoricalInspection:
    """인식 여부와 전체 자료 수를 실제 관찰로 반환한다.

    Attributes:
        source_path: 관찰한 파일.
        format: 인식한 형식 또는 unknown.
        tables: 빠뜨리지 않은 테이블별 행 수.
        wal_present: 관찰 당시 WAL 파일 유무.
    """

    source_path: str
    format: str
    tables: Sequence[tuple[str, int]]
    wal_present: bool


@immutable
class HistoricalSnapshot:
    """일관된 SQLite 사본과 원본 파일 보존 위치다.

    Attributes:
        inspection: 복제한 저장소의 실제 관찰.
        path: 일관된 사본 파일.
        digest: 사본의 내용 식별값.
    """

    inspection: HistoricalInspection
    path: str
    digest: str


@immutable
class HistoricalRecord:
    """과거 상태를 현재 실행 권한과 구분해 읽는 자료다.

    Attributes:
        key: 자료 안에서 선택할 원 식별자.
        category: 원문·태스크·절차·사실·메시지·학습·미인식 구분.
        status: 원래 상태이며 해석할 수 없으면 None.
        origin: 중복 재개를 구분할 계보 식별자.
        data: 원본 필드와 명시적으로 해석한 자료.
        references: 원 테이블·행·내장 archive로 돌아갈 참조.
    """

    key: str
    category: str
    status: str | None
    origin: str
    data: dict[str, Any]
    references: Sequence[str]


@immutable
class HistoricalPage:
    """선택한 범위만 읽고 나머지 의미 해석을 완료로 표시하지 않는다.

    Attributes:
        records: 요청한 페이지.
        total: 끝까지 읽었을 때만 확인한 전체 수.
        next_offset: 이어 읽을 위치.
    """

    records: Sequence[HistoricalRecord]
    total: int | None
    next_offset: int | None


class IHistoricalStoreService(ABC):
    """원본을 바꾸지 않고 저장 형식과 보존 자료를 읽는다."""

    @abstractmethod
    def inspect(self, source: str) -> HistoricalInspection:
        """원본 SQLite를 읽기 전용으로 관찰한다.

        Args:
            source: 관찰할 원본 파일.

        Returns:
            HistoricalInspection: 형식·전체 테이블 수·WAL 관찰.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def snapshot(
        self, source: str, archive_directory: str, configs: Sequence[str]
    ) -> HistoricalSnapshot:
        """일관된 사본과 명시한 설정·원본/WAL 바이트를 보존한다.

        Args:
            source: 읽을 원본 SQLite.
            archive_directory: 새 사본을 둘 폴더.
            configs: 함께 보존할 명시적 설정 파일.

        Returns:
            HistoricalSnapshot: 원본을 변경하지 않은 사본.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def read(
        self, snapshot: str, category: str, offset: int = 0, limit: int = 20, key: str | None = None
    ) -> HistoricalPage:
        """명시한 기능 자료를 원문과 상태 그대로 해석한다.

        Args:
            snapshot: 보존된 SQLite 사본.
            category: 조회할 기능 구분.
            offset: 이전 페이지 다음 위치.
            limit: 최대 출력 수.
            key: 특정 자료만 선택할 원 식별자.

        Returns:
            HistoricalPage: 원문·참조·미상과 후속 조회 위치.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def recover(self, source: str, destination: str) -> HistoricalSnapshot:
        """새 자료를 포함한 현재 코어를 덮어쓰기 없는 호환 복구 사본으로 만든다.

        Args:
            source: 새 기록을 포함한 현재 코어.
            destination: 아직 존재하지 않는 복구 파일.

        Returns:
            HistoricalSnapshot: 현재 버전으로 검증한 복구 사본.

        Raises:
            NotImplementedError: 미구현 포트를 호출한 경우.
        """
        raise NotImplementedError
