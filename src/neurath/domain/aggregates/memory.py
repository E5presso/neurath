"""출처가 있는 과거 자료와 체크포인트 보고를 현재 사실과 분리해 보존한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.memory_events import CheckpointGraphRequested


class GraphUpdateStatus(StrEnum):
    """커밋된 체크포인트에 연결된 외부 갱신 결과를 구분한다.

    Attributes:
        PENDING: 요청은 저장했으나 결과가 아직 기록되지 않은 상태.
        SUCCEEDED: 검증된 그래프 참조를 기록한 상태.
        FAILED: 외부 갱신 실패를 기록한 상태.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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
class Memory(AbstractAggregateRoot[UUID]):
    """현재 enclave를 덮어쓰거나 태스크를 완료하지 않는 출처 있는 기록이다.

    Attributes:
        project_id: 검색과 선택 조회를 제한할 프로젝트.
        session_id: 기록을 남긴 원래 세션.
        task_id: 관련 작업 또는 세션 공통 보고의 None.
        kind: 상세 자료·체크포인트·인수 보고의 구분.
        content: 1 MiB 이내의 원래 본문.
        references: 원문·산출물·이전 기록으로 돌아갈 참조.
        graph_directory: 커밋 후 갱신을 요청한 경로이며 요청이 없으면 None.
        graph_reference: 외부 갱신 성공 후 기록한 그래프 참조.
        graph_error: 외부 갱신 실패의 관찰이며 결과 미기록은 None.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID | None
    kind: MemoryKind
    content: str
    references: Sequence[str]
    graph_directory: str | None = None
    graph_reference: str | None = None
    graph_error: str | None = None

    @property
    def graph_status(self) -> GraphUpdateStatus | None:
        """요청이 없거나 결과를 기록하지 못한 상태를 성공과 구분한다.

        Returns:
            GraphUpdateStatus | None: 저장된 외부 갱신 상태이며 요청이 없으면 None.
        """
        if self.graph_directory is None:
            return None
        if self.graph_reference is not None:
            return GraphUpdateStatus.SUCCEEDED
        if self.graph_error is not None:
            return GraphUpdateStatus.FAILED
        return GraphUpdateStatus.PENDING

    def request_graph_update(self, directory: str) -> None:
        """검증된 보고에 외부 갱신 요청을 연결하고 저장 후 발행할 사건을 만든다.

        Args:
            directory: 갱신할 그래프의 프로젝트 경로.

        Raises:
            ValueError: 경로가 비어 있거나 이미 갱신 요청이 있는 경우.
        """
        if not directory.strip() or self.graph_directory is not None:
            raise ValueError("A graph update requires a nonempty, new request directory")
        self.graph_directory = directory
        self.add_event(CheckpointGraphRequested(memory_id=self.uid, directory=directory))

    def record_graph_update(self, directory: str, reference: str | None, error: str | None) -> None:
        """같은 요청의 외부 관찰만 기록하며 원래 보고 본문과 출처를 보존한다.

        Args:
            directory: 실제 갱신을 시도한 요청 경로.
            reference: 성공한 그래프 참조이며 실패면 None.
            error: 실패 관찰이며 성공이면 None.

        Raises:
            ValueError: 요청이 다르거나 이미 결과가 있거나 성공·실패 관찰이 모호한 경우.
        """
        if directory != self.graph_directory or self.graph_status is not GraphUpdateStatus.PENDING:
            raise ValueError("Graph outcome does not match a pending checkpoint request")
        if (
            (reference is None) == (error is None)
            or (reference is not None and not reference.strip())
            or (error is not None and not error.strip())
        ):
            raise ValueError("Exactly one graph reference or failure is required")
        self.graph_reference = reference
        self.graph_error = error
        if reference is not None:
            self.references = (*self.references, reference)

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """선택 조회에 사용할 기억 식별자를 생성한다.

        Returns:
            UUID: 새로운 UUID 값.
        """
        return uuid7()

    @classmethod
    def create(
        cls,
        project_id: UUID,
        session_id: UUID,
        task_id: UUID | None,
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
