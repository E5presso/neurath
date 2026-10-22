"""출처가 있는 과거 자료와 체크포인트 보고를 현재 사실과 분리해 보존한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Self, override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot


class MemoryKind(StrEnum):
    """기억 기록의 목적을 구분한다.

    Attributes:
        ARTIFACT: enclave가 참조하는 상세 자료.
        CHECKPOINT: 결과·판단·남은 일과 다음 행동을 적은 보고.
        HANDOFF: 실제 인수로 변경한 소유 범위의 기록.
    """

    ARTIFACT = "artifact"
    CHECKPOINT = "checkpoint"
    HANDOFF = "handoff"


@mutable
class Memory(AbstractAggregateRoot[str]):
    """현재 enclave를 덮어쓰거나 태스크를 완료하지 않는 출처 있는 기록이다.

    Attributes:
        project_id: 검색과 선택 조회를 제한할 프로젝트.
        session_id: 기록을 남긴 원래 세션.
        task_id: 관련 작업 또는 세션 공통 보고의 None.
        kind: 상세 자료·체크포인트·인수 보고의 구분.
        content: 1 MiB 이내의 원래 본문.
        references: 원문·산출물·이전 기록으로 돌아갈 참조.
    """

    project_id: str
    session_id: str
    task_id: str | None
    kind: MemoryKind
    content: str
    references: Sequence[str]

    @classmethod
    @override
    def next_id(cls) -> str:
        """선택 조회에 사용할 기억 식별자를 생성한다.

        Returns:
            str: 새로운 UUID 문자열.
        """
        return str(uuid4())

    @classmethod
    def create(
        cls,
        project_id: str,
        session_id: str,
        task_id: str | None,
        kind: MemoryKind,
        content: str,
        references: Sequence[str],
    ) -> Self:
        """원문과 관련 범위를 가진 보고를 만든다.

        Args:
            project_id: 확인된 프로젝트.
            session_id: 보고를 남긴 세션.
            task_id: 관련 태스크 또는 None.
            kind: 보고 종류.
            content: 보존할 전체 본문.
            references: 출처와 산출물 참조.

        Returns:
            Self: 작업 성공 판정과 독립적인 기록.
        """
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            session_id=session_id,
            task_id=task_id,
            kind=kind,
            content=content,
            references=references,
        )

    @override
    def validate(self) -> None:
        """빈 본문·근거와 저장 한도를 넘는 본문을 거절한다.

        Raises:
            ValueError: 내용·출처가 없거나 UTF-8 본문이 1 MiB를 넘는 경우.
        """
        if not self.content.strip() or len(self.content.encode("utf-8")) > 1048576:
            raise ValueError("Memory content must be nonempty and at most 1 MiB")
        if not self.references or any(not item.strip() for item in self.references):
            raise ValueError("Memory source references are required")
