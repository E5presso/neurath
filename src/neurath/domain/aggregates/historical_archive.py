"""원본 스냅샷과 선택 재개의 연결을 보존하며 과거 소유권을 현재 권한으로 쓰지 않는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID, uuid7

from spakky.core.common.mutability import immutable, mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot
from spakky.domain.models.value_object import AbstractValueObject


@immutable
class HistoricalAdoption(AbstractValueObject):
    """같은 과거 작업을 두 번 만들지 않도록 실제 재개 대상을 연결한다.

    Attributes:
        origin: 원 저장소 계보·소유자·작업으로 구성한 식별자.
        task_id: 현재 코어에서 실제로 이어가는 작업.
    """

    origin: str
    task_id: UUID


@mutable
class HistoricalArchive(AbstractAggregateRoot[UUID]):
    """보존된 자료와 실제 선택 재개를 구분하는 이전 자료다.

    Attributes:
        directory: 명시적으로 선택한 대상 프로젝트 루트.
        source_path: 원본 위치이며 현재 작성 권한은 아니다.
        snapshot_path: 일관된 읽기 사본과 보존 파일의 위치.
        digest: 사본의 내용 식별값이며 승인 증명이 아니다.
        format: 인식한 과거 저장 형식.
        tables: 전체 테이블별 행 수. 미인식 테이블도 포함한다.
        adoptions: 실제 선택해 재개한 과거 작업의 연결.
        revision: 동시 재개를 구분하는 저장 개정.
    """

    directory: str
    source_path: str
    snapshot_path: str
    digest: str
    format: str
    tables: Sequence[tuple[str, int]]
    adoptions: Sequence[HistoricalAdoption] = ()
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """현재 권한과 무관한 자료 식별자를 생성한다.

        Returns:
            UUID: 새 자료의 UUID7 식별자.
        """
        return uuid7()

    def adopt(self, origin: str, task_id: UUID) -> None:
        """같은 원 작업의 재개 연결을 중복하지 않는다.

        Args:
            origin: 과거 원 작업의 식별자.
            task_id: 실제 현재 작업.

        Raises:
            ValueError: 같은 원 작업을 다른 현재 작업에 연결하려는 경우.
        """
        for item in self.adoptions:
            if item.origin == origin:
                if item.task_id != task_id:
                    raise ValueError("Historical work already has a current task")
                return
        self.adoptions = (*self.adoptions, HistoricalAdoption(origin=origin, task_id=task_id))
